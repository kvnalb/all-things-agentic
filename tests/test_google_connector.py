import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studyagent.api.google import create_google_router
from studyagent.connectors.google import (
    GOOGLE_OAUTH_SCOPES,
    STUDY_CALENDAR_MARKER,
    STUDY_CALENDAR_NAME,
    GoogleApiGateway,
    GoogleConnector,
    GoogleConnection,
    GoogleConnectionStore,
    GoogleIdentity,
    GoogleOAuthClient,
    InMemoryOAuthStateStore,
    OAuthAuthorizationRequest,
    OAuthTokenBundle,
    SecretStore,
)


class FakeOAuth(GoogleOAuthClient):
    def __init__(self, token: OAuthTokenBundle) -> None:
        self.token = token
        self.last_request: OAuthAuthorizationRequest | None = None

    def authorization_url(self, request: OAuthAuthorizationRequest) -> str:
        self.last_request = request
        query = urlencode({"state": request.state, "scope": " ".join(request.scopes)})
        return f"https://accounts.google.test/o/oauth2/v2/auth?{query}"

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenBundle:
        if code == "bad-code":
            raise ValueError("provider included sensitive detail")
        return self.token


class FakeSecrets(SecretStore):
    def __init__(self) -> None:
        self.tokens: list[OAuthTokenBundle] = []

    def put_google_token(self, token: OAuthTokenBundle) -> str:
        self.tokens.append(token)
        return "projects/demo/secrets/google-oauth/versions/1"


class FakeConnections(GoogleConnectionStore):
    def __init__(self) -> None:
        self.connection: GoogleConnection | None = None

    def load(self) -> GoogleConnection | None:
        return self.connection

    def save(self, connection: GoogleConnection) -> None:
        self.connection = connection


class FakeGoogleApi(GoogleApiGateway):
    def __init__(self, calendar_id: str | None = None) -> None:
        self.calendar_id = calendar_id
        self.created = 0
        self.sent_to: list[str] = []

    def get_identity(self, secret_ref: str) -> GoogleIdentity:
        return GoogleIdentity(email="student@example.com")

    def calendar_exists(self, secret_ref: str, *, calendar_id: str) -> bool:
        return calendar_id == self.calendar_id

    def create_calendar(
        self,
        secret_ref: str,
        *,
        summary: str,
        marker: str,
        time_zone: str,
    ) -> str:
        self.assert_calendar_identity(summary, marker)
        self.created += 1
        self.calendar_id = "calendar-created"
        return self.calendar_id

    def assert_calendar_identity(self, summary: str, marker: str) -> None:
        if summary != STUDY_CALENDAR_NAME or marker != STUDY_CALENDAR_MARKER:
            raise AssertionError("unexpected calendar identity")


class GoogleConnectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.token = OAuthTokenBundle(
            access_token="access-secret",
            refresh_token="refresh-secret",
            scopes=frozenset(GOOGLE_OAUTH_SCOPES),
        )
        self.oauth = FakeOAuth(self.token)
        self.secrets = FakeSecrets()
        self.connections = FakeConnections()
        self.google = FakeGoogleApi()
        self.connector = GoogleConnector(
            oauth=self.oauth,
            secrets=self.secrets,
            connections=self.connections,
            api=self.google,
            states=InMemoryOAuthStateStore(),
            redirect_uri="https://studyagent.test/api/auth/google/callback",
            allowed_email="student@example.com",
        )
        app = FastAPI()
        app.include_router(create_google_router(self.connector))
        self.client = TestClient(app)

    def begin(self) -> str:
        response = self.client.get("/api/auth/google/start")
        self.assertEqual(response.status_code, 200)
        authorization_url = response.json()["authorization_url"]
        return parse_qs(urlparse(authorization_url).query)["state"][0]

    def test_start_requests_only_required_scopes_and_offline_access(self) -> None:
        self.begin()
        request = self.oauth.last_request
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.scopes, GOOGLE_OAUTH_SCOPES)
        self.assertEqual(request.access_type, "offline")
        self.assertEqual(request.prompt, "consent")
        self.assertTrue(request.include_granted_scopes)

    def test_callback_stores_token_and_creates_calendar_without_leaking_token(self) -> None:
        state = self.begin()
        response = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["identity_label"], "student@example.com")
        self.assertNotIn("access-secret", response.text)
        self.assertNotIn("refresh-secret", response.text)
        self.assertEqual(self.secrets.tokens, [self.token])
        self.assertEqual(self.google.created, 1)
        self.assertEqual(self.connector.calendar_id, "calendar-created")

    def test_callback_recovers_existing_calendar(self) -> None:
        self.google.calendar_id = "calendar-existing"
        self.connections.connection = GoogleConnection(
            secret_ref="projects/demo/secrets/old/versions/1",
            identity=GoogleIdentity(email="student@example.com"),
            calendar_id="calendar-existing",
        )
        state = self.begin()
        response = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.google.created, 0)
        self.assertEqual(self.connector.calendar_id, "calendar-existing")

    def test_callback_rejects_unknown_and_replayed_state_before_exchange(self) -> None:
        response = self.client.get(
            "/api/auth/google/callback",
            params={"code": "valid-code", "state": "attacker-state"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.secrets.tokens, [])

        state = self.begin()
        first = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )
        replay = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 400)

    def test_expired_state_is_rejected(self) -> None:
        now = datetime(2026, 8, 28, tzinfo=UTC)
        current = [now]
        states = InMemoryOAuthStateStore(
            ttl=timedelta(minutes=10), now=lambda: current[0]
        )
        connector = GoogleConnector(
            oauth=self.oauth,
            secrets=self.secrets,
            connections=self.connections,
            api=self.google,
            states=states,
            redirect_uri="https://studyagent.test/api/auth/google/callback",
            allowed_email="student@example.com",
        )
        app = FastAPI()
        app.include_router(create_google_router(connector))
        client = TestClient(app)
        authorization_url = client.get("/api/auth/google/start").json()[
            "authorization_url"
        ]
        state = parse_qs(urlparse(authorization_url).query)["state"][0]
        current[0] += timedelta(minutes=11)

        response = client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.secrets.tokens, [])

    def test_missing_refresh_token_fails_without_persisting_credentials(self) -> None:
        self.oauth.token = OAuthTokenBundle(
            access_token="short-lived",
            refresh_token=None,
            scopes=frozenset(GOOGLE_OAUTH_SCOPES),
        )
        state = self.begin()
        response = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.secrets.tokens, [])
        self.assertNotIn("short-lived", response.text)

    def test_missing_scope_fails_without_persisting_credentials(self) -> None:
        self.oauth.token = OAuthTokenBundle(
            access_token="under-scoped",
            refresh_token="refresh-secret",
            scopes=frozenset({"openid", "email", "profile"}),
        )
        state = self.begin()
        response = self.client.get(
            "/api/auth/google/callback", params={"code": "valid-code", "state": state}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.secrets.tokens, [])
        self.assertNotIn("under-scoped", response.text)

    def test_provider_failure_is_redacted(self) -> None:
        state = self.begin()
        response = self.client.get(
            "/api/auth/google/callback", params={"code": "bad-code", "state": state}
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("sensitive detail", response.text)

    def test_test_email_route_is_absent(self) -> None:
        self.assertEqual(self.client.post("/api/connectors/google/test-email").status_code, 404)


if __name__ == "__main__":
    unittest.main()

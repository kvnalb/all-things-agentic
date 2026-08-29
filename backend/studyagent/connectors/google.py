from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from studyagent.models import ConnectionState, ConnectorResult, ProviderName


GOOGLE_OAUTH_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.app.created",
    "https://www.googleapis.com/auth/gmail.send",
)
STUDY_CALENDAR_NAME = "StudyAgent — Fall 2026"
STUDY_CALENDAR_MARKER = "studyagent:fall-2026"
STUDY_TIME_ZONE = "America/Los_Angeles"


class GoogleConnectionError(Exception):
    """Safe, user-facing failure from the Google connection flow."""


@dataclass(frozen=True)
class OAuthAuthorizationRequest:
    state: str
    redirect_uri: str
    scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES
    access_type: str = "offline"
    prompt: str = "consent"
    include_granted_scopes: bool = True


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    scopes: frozenset[str]
    expires_at: datetime | None = None


@dataclass(frozen=True)
class GoogleIdentity:
    email: str


@dataclass(frozen=True)
class GoogleConnection:
    secret_ref: str
    identity: GoogleIdentity
    calendar_id: str


class GoogleOAuthClient(Protocol):
    def authorization_url(self, request: OAuthAuthorizationRequest) -> str: ...

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenBundle: ...


class SecretStore(Protocol):
    def put_google_token(self, token: OAuthTokenBundle) -> str: ...


class GoogleConnectionStore(Protocol):
    """Persists non-secret connection metadata, such as in Firestore."""

    def load(self) -> GoogleConnection | None: ...

    def save(self, connection: GoogleConnection) -> None: ...


class GoogleApiGateway(Protocol):
    """Uses a secret reference; implementations fetch credentials internally."""

    def get_identity(self, secret_ref: str) -> GoogleIdentity: ...

    def calendar_exists(self, secret_ref: str, *, calendar_id: str) -> bool: ...

    def create_calendar(
        self,
        secret_ref: str,
        *,
        summary: str,
        marker: str,
        time_zone: str,
    ) -> str: ...

    def send_test_email(self, secret_ref: str, *, recipient: str) -> None: ...


class OAuthStateStore(Protocol):
    def issue(self) -> str: ...

    def consume(self, state: str) -> bool: ...


class InMemoryOAuthStateStore:
    """One-time OAuth states for local/single-instance use.

    Production should use the same contract backed by Firestore so state remains
    valid when Cloud Run routes the callback to another instance.
    """

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=10),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ttl = ttl
        self._now = now
        self._states: dict[str, datetime] = {}

    @staticmethod
    def _digest(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def issue(self) -> str:
        state = secrets.token_urlsafe(32)
        self._states[self._digest(state)] = self._now() + self._ttl
        return state

    def consume(self, state: str) -> bool:
        if not state:
            return False
        expires_at = self._states.pop(self._digest(state), None)
        return expires_at is not None and self._now() <= expires_at


class GoogleConnector:
    def __init__(
        self,
        *,
        oauth: GoogleOAuthClient,
        secrets: SecretStore,
        connections: GoogleConnectionStore,
        api: GoogleApiGateway,
        states: OAuthStateStore,
        redirect_uri: str,
    ) -> None:
        self._oauth = oauth
        self._secrets = secrets
        self._connections = connections
        self._api = api
        self._states = states
        self._redirect_uri = redirect_uri

    def begin_auth(self) -> str:
        state = self._states.issue()
        return self._oauth.authorization_url(
            OAuthAuthorizationRequest(state=state, redirect_uri=self._redirect_uri)
        )

    def complete_auth(self, *, code: str, state: str) -> ConnectorResult:
        if not self._states.consume(state):
            raise GoogleConnectionError("Google sign-in expired or could not be verified")
        if not code:
            raise GoogleConnectionError("Google did not return an authorization code")

        try:
            token = self._oauth.exchange_code(code, self._redirect_uri)
        except Exception as exc:
            raise GoogleConnectionError("Google sign-in could not be completed") from exc

        if not token.refresh_token:
            raise GoogleConnectionError(
                "Google did not grant offline access; reconnect and approve access"
            )
        if not set(GOOGLE_OAUTH_SCOPES).issubset(token.scopes):
            raise GoogleConnectionError("Google did not grant every required permission")

        try:
            secret_ref = self._secrets.put_google_token(token)
            identity = self._api.get_identity(secret_ref)
            previous = self._connections.load()
            calendar_id = previous.calendar_id if previous is not None else None
            if calendar_id is not None and not self._api.calendar_exists(
                secret_ref, calendar_id=calendar_id
            ):
                calendar_id = None
            if calendar_id is None:
                calendar_id = self._api.create_calendar(
                    secret_ref,
                    summary=STUDY_CALENDAR_NAME,
                    marker=STUDY_CALENDAR_MARKER,
                    time_zone=STUDY_TIME_ZONE,
                )
            connection = GoogleConnection(
                secret_ref=secret_ref,
                identity=identity,
                calendar_id=calendar_id,
            )
            self._connections.save(connection)
        except Exception as exc:
            raise GoogleConnectionError("Google account setup could not be completed") from exc

        return ConnectorResult(
            provider=ProviderName.GOOGLE,
            state=ConnectionState.CONNECTED,
            identity_label=identity.email,
            message=f"{STUDY_CALENDAR_NAME} is ready",
        )

    def send_test_email(self) -> ConnectorResult:
        connection = self._connections.load()
        if connection is None:
            raise GoogleConnectionError("Connect Google before sending a test email")
        try:
            self._api.send_test_email(
                connection.secret_ref, recipient=connection.identity.email
            )
        except Exception as exc:
            raise GoogleConnectionError("Google could not send the test email") from exc
        return ConnectorResult(
            provider=ProviderName.GOOGLE,
            state=ConnectionState.CONNECTED,
            identity_label=connection.identity.email,
            message="Test email sent",
        )

    @property
    def calendar_id(self) -> str | None:
        connection = self._connections.load()
        return connection.calendar_id if connection is not None else None

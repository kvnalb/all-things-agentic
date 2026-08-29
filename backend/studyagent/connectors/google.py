from __future__ import annotations

import hashlib
import os
import secrets
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from studyagent.models import ConnectionState, ConnectorResult, ProviderName

GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile", "https://www.googleapis.com/auth/calendar.app.created", "https://www.googleapis.com/auth/calendar.readonly")
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
    calendar_id: str = ""

class GoogleOAuthClient(Protocol):
    def authorization_url(self, request: OAuthAuthorizationRequest) -> str: ...
    def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenBundle: ...

class SecretStore(Protocol):
    def put_google_token(self, token: OAuthTokenBundle) -> str: ...

class GoogleConnectionStore(Protocol):
    def load(self) -> GoogleConnection | None: ...
    def save(self, connection: GoogleConnection) -> None: ...

class GoogleApiGateway(Protocol):
    def get_identity(self, secret_ref: str) -> GoogleIdentity: ...
    def calendar_exists(self, secret_ref: str, *, calendar_id: str) -> bool: ...
    def find_calendar_by_marker(self, secret_ref: str, *, marker: str) -> str | None: ...
    def create_calendar(self, secret_ref: str, *, summary: str, marker: str, time_zone: str) -> str: ...

class OAuthStateStore(Protocol):
    def issue(self, session_id: str) -> str: ...
    def consume(self, state: str, session_id: str) -> bool: ...

class InMemoryOAuthStateStore:
    def __init__(self, *, ttl: timedelta = timedelta(minutes=10), now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._ttl, self._now = ttl, now
        self._states: dict[str, tuple[datetime, str]] = {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def issue(self, session_id: str = "default") -> str:
        state = secrets.token_urlsafe(32)
        self._states[self._digest(state)] = (self._now() + self._ttl, self._digest(session_id))
        return state

    def consume(self, state: str, session_id: str = "default") -> bool:
        item = self._states.pop(self._digest(state), None) if state else None
        return item is not None and self._now() <= item[0] and item[1] == self._digest(session_id)

class GoogleConnector:
    def __init__(self, *, oauth: GoogleOAuthClient, secrets: SecretStore, connections: GoogleConnectionStore,
                 api: GoogleApiGateway, states: OAuthStateStore, redirect_uri: str, allowed_email: str | None = None) -> None:
        self._oauth, self._secrets, self._connections = oauth, secrets, connections
        self._api, self._states, self._redirect_uri = api, states, redirect_uri
        self._allowed_email = (allowed_email or os.getenv("STUDYAGENT_ALLOWED_EMAIL", "")).strip().lower()

    def begin_auth(self, session_id: str = "default") -> str:
        state = self._states.issue(session_id)
        return self._oauth.authorization_url(OAuthAuthorizationRequest(state=state, redirect_uri=self._redirect_uri))

    def complete_auth(self, *, code: str, state: str, session_id: str = "default") -> ConnectorResult:
        if not self._states.consume(state, session_id):
            raise GoogleConnectionError("Google sign-in expired or could not be verified")
        if not code:
            raise GoogleConnectionError("Google did not return an authorization code")
        try:
            token = self._oauth.exchange_code(code, self._redirect_uri)
        except Exception as exc:
            raise GoogleConnectionError("Google sign-in could not be completed") from exc
        if not token.refresh_token:
            raise GoogleConnectionError("Google did not grant offline access; reconnect and approve access")
        if not set(GOOGLE_OAUTH_SCOPES).issubset(token.scopes):
            raise GoogleConnectionError("Google did not grant every required permission")
        try:
            secret_ref = self._secrets.put_google_token(token)
            identity = self._api.get_identity(secret_ref)
            if not self._allowed_email or identity.email.lower() != self._allowed_email:
                raise GoogleConnectionError("This Google account is not allowed")
            previous = self._connections.load()
            calendar_id = previous.calendar_id if previous else ""
            if calendar_id and not self._api.calendar_exists(secret_ref, calendar_id=calendar_id):
                calendar_id = ""
            if not calendar_id:
                finder = getattr(self._api, "find_calendar_by_marker", None)
                calendar_id = finder(secret_ref, marker=STUDY_CALENDAR_MARKER) if finder else None
            self._connections.save(GoogleConnection(secret_ref, identity, calendar_id or ""))
            if not calendar_id:
                calendar_id = self._api.create_calendar(secret_ref, summary=STUDY_CALENDAR_NAME, marker=STUDY_CALENDAR_MARKER, time_zone=STUDY_TIME_ZONE)
                self._connections.save(GoogleConnection(secret_ref, identity, calendar_id))
        except GoogleConnectionError:
            raise
        except Exception as exc:
            raise GoogleConnectionError("Google account setup could not be completed") from exc
        return ConnectorResult(provider=ProviderName.GOOGLE, state=ConnectionState.CONNECTED, identity_label=identity.email, message=f"{STUDY_CALENDAR_NAME} is ready")

    @property
    def calendar_id(self) -> str | None:
        connection = self._connections.load()
        return connection.calendar_id if connection and connection.calendar_id else None


class GoogleOAuthWebClient:
    """Google's supported OAuth web flow, with client config kept in Secret Manager."""
    def __init__(self, client_config: dict, scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES) -> None:
        self._config, self._scopes = client_config, scopes

    def authorization_url(self, request: OAuthAuthorizationRequest) -> str:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(self._config, scopes=list(request.scopes), redirect_uri=request.redirect_uri)
        url, _ = flow.authorization_url(access_type=request.access_type, prompt=request.prompt,
                                         include_granted_scopes=str(request.include_granted_scopes).lower(), state=request.state)
        return url

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenBundle:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(self._config, scopes=list(self._scopes), redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        return OAuthTokenBundle(creds.token, creds.refresh_token, frozenset(creds.scopes or ()), creds.expiry)


class SecretManagerGoogleTokenStore:
    def __init__(self, secret_name: str, client=None) -> None:
        from google.cloud import secretmanager
        self._client = client or secretmanager.SecretManagerServiceClient()
        self._secret_name = secret_name

    def put_google_token(self, token: OAuthTokenBundle) -> str:
        payload = json.dumps({"refresh_token": token.refresh_token, "scopes": sorted(token.scopes),
                              "expires_at": token.expires_at.isoformat() if token.expires_at else None}).encode()
        result = self._client.add_secret_version(parent=self._secret_name, payload={"data": payload})
        return result.name


class SecretManagerCredentialsProvider:
    """Loads only the latest refresh-token version and never exposes its value."""
    def __init__(self, token_secret: str, client=None) -> None:
        from google.cloud import secretmanager
        self._client = client or secretmanager.SecretManagerServiceClient()
        self._token_secret = token_secret

    def __call__(self, secret_ref: str):
        from google.oauth2.credentials import Credentials
        name = f"{self._token_secret}/versions/latest"
        raw = self._client.access_secret_version(name=name).payload.data
        data = json.loads(raw)
        return Credentials(token=None, refresh_token=data["refresh_token"],
                           token_uri="https://oauth2.googleapis.com/token", scopes=data["scopes"])


class FirestoreGoogleConnectionStore:
    def __init__(self, collection: str = "studyagent", document: str = "google", client=None) -> None:
        from google.cloud import firestore
        self._client = client or firestore.Client()
        self._ref = self._client.collection(collection).document(document)

    def load(self) -> GoogleConnection | None:
        data = self._ref.get().to_dict()
        if not data:
            return None
        return GoogleConnection(data["secret_ref"], GoogleIdentity(data["email"]), data.get("calendar_id", ""))

    def save(self, connection: GoogleConnection) -> None:
        self._ref.set({"secret_ref": connection.secret_ref, "email": connection.identity.email,
                       "calendar_id": connection.calendar_id})


class FirestoreOAuthStateStore(InMemoryOAuthStateStore):
    """Firestore-backed one-time state; only digests, expiry, and session binding are stored."""
    def __init__(self, collection: str = "studyagent_oauth_states", client=None, **kwargs) -> None:
        from google.cloud import firestore
        super().__init__(**kwargs)
        self._states_ref = (client or firestore.Client()).collection(collection)

    def issue(self, session_id: str = "default") -> str:
        state = super().issue(session_id)
        digest = self._digest(state)
        self._states_ref.document(digest).set({"expires_at": self._states[digest][0], "session_digest": self._states[digest][1]})
        return state

    def consume(self, state: str, session_id: str = "default") -> bool:
        digest = self._digest(state)
        doc = self._states_ref.document(digest)
        snap = doc.get()
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        doc.delete()
        return self._now() <= data["expires_at"] and data["session_digest"] == self._digest(session_id)


class GoogleCalendarGateway:
    """Calendar and OpenID calls through google-api-python-client."""
    def __init__(self, credentials_for: Callable[[str], object]) -> None:
        self._credentials_for = credentials_for

    def _service(self, secret_ref: str):
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=self._credentials_for(secret_ref), cache_discovery=False)

    def get_identity(self, secret_ref: str) -> GoogleIdentity:
        from googleapiclient.discovery import build
        data = build("oauth2", "v2", credentials=self._credentials_for(secret_ref), cache_discovery=False).userinfo().get().execute()
        return GoogleIdentity(data["email"])

    def calendar_exists(self, secret_ref: str, *, calendar_id: str) -> bool:
        try:
            self._service(secret_ref).calendars().get(calendarId=calendar_id).execute()
            return True
        except Exception:
            return False

    def find_calendar_by_marker(self, secret_ref: str, *, marker: str) -> str | None:
        page = None
        while True:
            result = self._service(secret_ref).calendarList().list(pageToken=page).execute()
            for item in result.get("items", []):
                if marker in item.get("description", ""):
                    return item.get("id")
            page = result.get("nextPageToken")
            if not page:
                return None

    def create_calendar(self, secret_ref: str, *, summary: str, marker: str, time_zone: str) -> str:
        result = self._service(secret_ref).calendars().insert(body={"summary": summary, "description": marker, "timeZone": time_zone}).execute()
        return result["id"]

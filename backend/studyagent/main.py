from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import json
import os

from .api.google import create_google_router
from .connectors.google import (FirestoreGoogleConnectionStore, FirestoreOAuthStateStore,
                                 GoogleCalendarGateway, GoogleConnector, GoogleOAuthWebClient,
                                 SecretManagerCredentialsProvider, SecretManagerGoogleTokenStore)
from .models import ConnectionStatus, ProviderName


app = FastAPI(title="StudyAgent", version="0.1.0")


def _google_connector_from_env() -> GoogleConnector | None:
    required = ("GOOGLE_OAUTH_CLIENT_JSON", "GOOGLE_TOKEN_SECRET", "GOOGLE_REDIRECT_URI", "STUDYAGENT_ALLOWED_EMAIL")
    if not all(os.getenv(name) for name in required):
        return None
    client_config = json.loads(os.environ["GOOGLE_OAUTH_CLIENT_JSON"])
    token_store = SecretManagerGoogleTokenStore(os.environ["GOOGLE_TOKEN_SECRET"])
    credentials = SecretManagerCredentialsProvider(os.environ["GOOGLE_TOKEN_SECRET"])
    return GoogleConnector(oauth=GoogleOAuthWebClient(client_config), secrets=token_store,
                           connections=FirestoreGoogleConnectionStore(), api=GoogleCalendarGateway(credentials),
                           states=FirestoreOAuthStateStore(), redirect_uri=os.environ["GOOGLE_REDIRECT_URI"],
                           allowed_email=os.environ["STUDYAGENT_ALLOWED_EMAIL"])


_google = _google_connector_from_env()
if _google is not None:
    app.include_router(create_google_router(_google))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/status", response_model=list[ConnectionStatus])
def setup_status() -> list[ConnectionStatus]:
    return [ConnectionStatus(provider=provider) for provider in ProviderName]


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    assets = frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        candidate = frontend_dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")

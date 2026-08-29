from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl

from studyagent.connectors.google import GoogleConnectionError, GoogleConnector
from studyagent.models import ConnectorResult


class GoogleAuthStart(BaseModel):
    authorization_url: HttpUrl


def create_google_router(connector: GoogleConnector) -> APIRouter:
    router = APIRouter(tags=["google"])

    @router.get("/api/auth/google/start", response_model=GoogleAuthStart)
    def start_google_auth() -> GoogleAuthStart:
        return GoogleAuthStart(authorization_url=connector.begin_auth())

    @router.get("/api/auth/google/callback", response_model=ConnectorResult)
    def finish_google_auth(
        code: str = Query(min_length=1), state: str = Query(min_length=1)
    ) -> ConnectorResult:
        try:
            return connector.complete_auth(code=code, state=state)
        except GoogleConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/connectors/google/test-email", response_model=ConnectorResult)
    def send_google_test_email() -> ConnectorResult:
        try:
            return connector.send_test_email()
        except GoogleConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

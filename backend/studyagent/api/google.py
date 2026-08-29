import secrets

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, HttpUrl

from studyagent.connectors.google import GoogleConnectionError, GoogleConnector
from studyagent.models import ConnectorResult


class GoogleAuthStart(BaseModel):
    authorization_url: HttpUrl


def create_google_router(connector: GoogleConnector) -> APIRouter:
    router = APIRouter(tags=["google"])

    @router.get("/api/auth/google/start", response_model=GoogleAuthStart)
    def start_google_auth(response: Response, request: Request) -> GoogleAuthStart:
        session_id = request.cookies.get("studyagent_setup_session") or secrets.token_urlsafe(24)
        response.set_cookie("studyagent_setup_session", session_id, httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=600)
        return GoogleAuthStart(authorization_url=connector.begin_auth(session_id))

    @router.get("/api/auth/google/callback", response_model=ConnectorResult)
    def finish_google_auth(
        request: Request, code: str = Query(min_length=1), state: str = Query(min_length=1)
    ) -> ConnectorResult:
        try:
            session_id = request.cookies.get("studyagent_setup_session", "")
            return connector.complete_auth(code=code, state=state, session_id=session_id)
        except GoogleConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

from __future__ import annotations

import asyncio
from functools import lru_cache

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .calibration import load_profile, profile_summary, record_feedback
from .canvas import Canvas
from .cloud import Settings, State
from .google import Google
from .models import EffortFeedback, UserConfig
from .store import load_daily_view, load_task_list
from .service import TaskmasterService


router = APIRouter(tags=["taskmaster"])


def require_owner(studyagent_session: str | None = Cookie(default=None)) -> None:
    if not State().valid_session(studyagent_session): raise HTTPException(401, "owner session required")


@router.get("/api/auth/google/start")
async def auth_start() -> RedirectResponse:
    return RedirectResponse(await asyncio.to_thread(Google().start_url))


@router.get("/api/auth/google/callback")
async def auth_callback(state: str, code: str) -> Response:
    try: session = await asyncio.to_thread(Google().callback, state, code)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    response = RedirectResponse("/?connected=1"); response.set_cookie("studyagent_session", session, secure=Settings.base_url.startswith("https://"), httponly=True, samesite="lax", max_age=604800)
    return response


@router.get("/api/status", dependencies=[Depends(require_owner)])
async def status() -> dict:
    return await asyncio.to_thread(State().status)


@router.post("/api/connectors/canvas", dependencies=[Depends(require_owner)])
async def connect_canvas() -> dict:
    identity, courses = await asyncio.to_thread(Canvas().discover)
    return {"identity_label": identity, "courses": courses}


@router.post("/api/config", dependencies=[Depends(require_owner)])
async def save_config(config: UserConfig) -> dict[str, str]:
    await asyncio.to_thread(State().save_config, config); return {"status": "saved"}


@router.post("/api/sync", dependencies=[Depends(require_owner)])
async def sync() -> dict:
    return await TaskmasterService().sync_semester("manual")


@router.get("/api/tasks", dependencies=[Depends(require_owner)])
async def tasks() -> dict:
    return await asyncio.to_thread(load_task_list)


@router.get("/api/daily", dependencies=[Depends(require_owner)])
async def daily() -> dict:
    return await asyncio.to_thread(load_daily_view)


@router.get("/api/calibration", dependencies=[Depends(require_owner)])
async def calibration() -> dict:
    return await asyncio.to_thread(lambda: profile_summary(load_profile()))


@router.post("/api/feedback", dependencies=[Depends(require_owner)])
async def feedback(body: EffortFeedback) -> dict:
    profile = await asyncio.to_thread(record_feedback, body)
    return {"status": "saved", "calibration": profile_summary(profile)}


@router.get("/api/activity", dependencies=[Depends(require_owner)])
async def activity() -> list[dict]:
    return await asyncio.to_thread(State().activity)


@router.post("/internal/sync")
async def scheduled_sync(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "scheduler token required")
    audience = f"{Settings.base_url}/internal/sync"
    try: claims = await asyncio.to_thread(id_token.verify_oauth2_token, authorization.removeprefix("Bearer "), google_requests.Request(), audience)
    except Exception as exc: raise HTTPException(401, "invalid scheduler token") from exc
    if claims.get("email") != f"studyagent-scheduler@{Settings.project}.iam.gserviceaccount.com": raise HTTPException(403, "unexpected scheduler identity")
    return await TaskmasterService().sync_semester("scheduler")

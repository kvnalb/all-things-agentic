from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from studyagent.connectors.canvas import (
    CanvasAPIError,
    CanvasAuthenticationError,
    CanvasClient,
    CanvasCourseActivity,
    CanvasSelectionError,
)
from studyagent.models import ConnectionState, ConnectorResult, Course, ProviderName


router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class CanvasConnectRequest(BaseModel):
    token: SecretStr
    term: str = Field(default="Fall 2026", min_length=1, max_length=80)
    selected_course_ids: list[str] = Field(default_factory=list, max_length=12)


class CanvasConnectResponse(BaseModel):
    connection: ConnectorResult
    courses: list[Course]
    activity: list[CanvasCourseActivity] = Field(default_factory=list)


@router.post("/canvas", response_model=CanvasConnectResponse)
def connect_canvas(request: CanvasConnectRequest) -> CanvasConnectResponse:
    try:
        with CanvasClient(request.token.get_secret_value()) as canvas:
            discovery = canvas.discover_courses(term=request.term)
            selected = set(request.selected_course_ids)
            courses = [
                course.to_course(selected=str(course.id) in selected)
                for course in discovery.courses
            ]
            activity = canvas.selected_activity(discovery, request.selected_course_ids)
    except CanvasAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except CanvasSelectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CanvasAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return CanvasConnectResponse(
        connection=ConnectorResult(
            provider=ProviderName.CANVAS,
            state=ConnectionState.CONNECTED,
            identity_label=discovery.profile.identity_label,
            discovered_course_ids=[str(course.id) for course in discovery.courses],
            message=f"Discovered {len(discovery.courses)} courses for {request.term}",
        ),
        courses=courses,
        activity=activity,
    )

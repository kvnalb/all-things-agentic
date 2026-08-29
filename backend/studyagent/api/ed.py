from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from studyagent.connectors.ed import (
    EdConnector,
    EdConnectorError,
    EdCourse,
    EdCourseMatch,
    EdStaffThread,
    match_courses,
)
from studyagent.models import ConnectionState, ConnectorResult, Course, ProviderName


router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class EdConnectRequest(BaseModel):
    token: SecretStr
    canvas_courses: list[Course] = Field(default_factory=list)
    overrides: dict[str, str] = Field(default_factory=dict)


class EdConnectResponse(BaseModel):
    result: ConnectorResult
    courses: list[EdCourse] = Field(default_factory=list)
    matches: list[EdCourseMatch] = Field(default_factory=list)
    staff_threads: list[EdStaffThread] = Field(default_factory=list)


@router.post("/ed", response_model=EdConnectResponse)
def connect_ed(request: EdConnectRequest) -> EdConnectResponse:
    return connect_ed_with(request, EdConnector())


def connect_ed_with(request: EdConnectRequest, connector: EdConnector) -> EdConnectResponse:
    """Run optional Ed setup without leaking connector failures into other providers."""
    try:
        token = request.token.get_secret_value()
        user = connector.validate_user(token)
        courses = connector.discover_active_courses(token)
        matches = match_courses(request.canvas_courses, courses, request.overrides)
        matched_ids = {match.ed_course_id for match in matches if match.ed_course_id}
        threads = [
            thread
            for course_id in sorted(matched_ids)
            for thread in connector.relevant_staff_threads(token, course_id)
        ]
        return EdConnectResponse(
            result=ConnectorResult(
                provider=ProviderName.ED,
                state=ConnectionState.CONNECTED,
                identity_label=user.name,
                discovered_course_ids=[course.id for course in courses],
                message="Ed connected",
            ),
            courses=courses,
            matches=matches,
            staff_threads=threads,
        )
    except EdConnectorError as exc:
        return EdConnectResponse(
            result=ConnectorResult(
                provider=ProviderName.ED,
                state=ConnectionState.ERROR,
                message=str(exc),
            )
        )

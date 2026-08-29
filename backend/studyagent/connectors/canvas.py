from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError

from studyagent.models import AcademicEventCandidate, Course, EventKind


BCOURSES_BASE_URL = "https://bcourses.berkeley.edu"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CanvasError(RuntimeError):
    """Safe base exception for Canvas failures."""


class CanvasAuthenticationError(CanvasError):
    """Raised when Canvas rejects an access token."""


class CanvasAPIError(CanvasError):
    """Raised when Canvas cannot satisfy a request safely."""


class CanvasSelectionError(CanvasError):
    """Raised when a requested course is not in the current discovery result."""


class CanvasTerm(BaseModel):
    id: int | str | None = None
    name: str = "Unknown term"
    start_at: datetime | None = None
    end_at: datetime | None = None


class CanvasProfile(BaseModel):
    id: int | str
    name: str | None = None
    short_name: str | None = None

    @property
    def identity_label(self) -> str:
        return self.short_name or self.name or f"Canvas user {self.id}"


class CanvasCourse(BaseModel):
    id: int | str
    name: str
    course_code: str | None = None
    workflow_state: str | None = None
    term: CanvasTerm | None = None
    syllabus_body: str | None = None

    def to_course(self, *, selected: bool = False) -> Course:
        return Course(
            id=f"canvas:course:{self.id}",
            canvas_id=str(self.id),
            code=self.course_code or self.name,
            title=self.name,
            term=self.term.name if self.term else "Unknown term",
            selected=selected,
        )


class CanvasSubmission(BaseModel):
    workflow_state: str | None = None
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    attempt: int | None = None

    @property
    def submitted(self) -> bool:
        return bool(
            self.submitted_at
            or self.graded_at
            or self.workflow_state in {"submitted", "graded", "pending_review"}
        )


class CanvasAssignment(BaseModel):
    id: int | str
    name: str
    due_at: datetime | None = None
    html_url: AnyHttpUrl | None = None
    submission_types: list[str] = Field(default_factory=list)
    submission: CanvasSubmission | None = None

    @property
    def is_quiz(self) -> bool:
        return "online_quiz" in self.submission_types


class CanvasQuiz(BaseModel):
    id: int | str
    title: str
    due_at: datetime | None = None
    html_url: AnyHttpUrl | None = None
    assignment_id: int | str | None = None


class CanvasCalendarEvent(BaseModel):
    id: int | str
    title: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool = False
    all_day_date: date | None = None
    location_name: str | None = None
    html_url: AnyHttpUrl | None = None


class CanvasCourseActivity(BaseModel):
    course: Course
    syllabus_body: str | None = None
    assignments: list[CanvasAssignment] = Field(default_factory=list)
    quizzes: list[CanvasQuiz] = Field(default_factory=list)
    calendar_events: list[CanvasCalendarEvent] = Field(default_factory=list)
    candidates: list[AcademicEventCandidate] = Field(default_factory=list)


class CanvasDiscovery(BaseModel):
    profile: CanvasProfile
    courses: list[CanvasCourse]


def _term_matches(actual: str, requested: str) -> bool:
    def normalize(value: str) -> str:
        normalized = value.casefold().replace("’", "'").replace("'", "")
        normalized = re.sub(r"\b26\b", "2026", normalized)
        return " ".join(normalized.split())

    actual_normalized = normalize(actual)
    requested_normalized = normalize(requested)
    return requested_normalized in actual_normalized


def _event_kind(title: str) -> EventKind:
    normalized = title.casefold()
    matches = (
        (("quiz",), EventKind.QUIZ),
        (("project",), EventKind.PROJECT),
        (("midterm", "exam", "final"), EventKind.EXAM),
        (("lecture",), EventKind.LECTURE),
        (("discussion",), EventKind.DISCUSSION),
        (("lab",), EventKind.LAB),
        (("office hour",), EventKind.OFFICE_HOURS),
    )
    return next((kind for words, kind in matches if any(word in normalized for word in words)), EventKind.OTHER)


class CanvasClient:
    """Small read-only bCourses adapter with bounded network behavior."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token.strip():
            raise CanvasAuthenticationError("Canvas token is required")
        if max_retries < 0 or max_retries > 3:
            raise ValueError("max_retries must be between 0 and 3")

        self._base_url = BCOURSES_BASE_URL
        self._origin = urlparse(self._base_url)
        self._max_retries = max_retries
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    def __enter__(self) -> CanvasClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def validate(self) -> CanvasProfile:
        payload = self._get_json("/api/v1/users/self/profile")
        try:
            return CanvasProfile.model_validate(payload)
        except ValidationError as exc:
            raise CanvasAPIError("Canvas returned an unexpected response schema") from exc

    def discover_courses(self, *, term: str = "Fall 2026") -> CanvasDiscovery:
        profile = self.validate()
        courses = self._get_paginated(
            "/api/v1/courses",
            params={
                "enrollment_state": "active",
                "include[]": ["term", "syllabus_body"],
                "per_page": 100,
            },
            model=CanvasCourse,
        )
        matching_courses = [
            course
            for course in courses
            if course.term is not None and _term_matches(course.term.name, term)
        ]
        return CanvasDiscovery(profile=profile, courses=matching_courses)

    def list_assignments(self, course_id: int | str) -> list[CanvasAssignment]:
        return self._get_paginated(
            f"/api/v1/courses/{quote(str(course_id), safe='')}/assignments",
            params={"include[]": "submission", "per_page": 100},
            model=CanvasAssignment,
        )

    def list_quizzes(self, course_id: int | str) -> list[CanvasQuiz]:
        return self._get_paginated(
            f"/api/v1/courses/{quote(str(course_id), safe='')}/quizzes",
            params={"per_page": 100},
            model=CanvasQuiz,
        )

    def list_calendar_events(self, course_id: int | str) -> list[CanvasCalendarEvent]:
        return self._get_paginated(
            "/api/v1/calendar_events",
            params={
                "context_codes[]": f"course_{course_id}",
                "all_events": "true",
                "per_page": 100,
            },
            model=CanvasCalendarEvent,
        )

    def get_course(self, course_id: int | str) -> CanvasCourse:
        payload = self._get_json(
            f"/api/v1/courses/{quote(str(course_id), safe='')}",
            params={"include[]": "syllabus_body"},
        )
        try:
            return CanvasCourse.model_validate(payload)
        except ValidationError as exc:
            raise CanvasAPIError("Canvas returned an unexpected response schema") from exc

    def fetch_course_activity(self, course: CanvasCourse) -> CanvasCourseActivity:
        course_id = course.id
        detailed_course = self.get_course(course_id)
        assignments = self.list_assignments(course_id)
        quizzes = self.list_quizzes(course_id)
        calendar_events = self.list_calendar_events(course_id)
        candidates = self.to_event_candidates(
            course_id=course_id,
            assignments=assignments,
            quizzes=quizzes,
            calendar_events=calendar_events,
        )
        return CanvasCourseActivity(
            course=detailed_course.to_course(selected=True),
            syllabus_body=detailed_course.syllabus_body,
            assignments=assignments,
            quizzes=quizzes,
            calendar_events=calendar_events,
            candidates=candidates,
        )

    def selected_activity(
        self, discovery: CanvasDiscovery, selected_course_ids: list[str]
    ) -> list[CanvasCourseActivity]:
        selected_in_order = list(dict.fromkeys(selected_course_ids))
        selected = set(selected_in_order)
        known = {str(course.id): course for course in discovery.courses}
        unknown = selected - known.keys()
        if unknown:
            raise CanvasSelectionError("One or more selected Canvas courses were not discovered")
        return [self.fetch_course_activity(known[course_id]) for course_id in selected_in_order]

    @staticmethod
    def to_event_candidates(
        *,
        course_id: int | str,
        assignments: list[CanvasAssignment],
        quizzes: list[CanvasQuiz],
        calendar_events: list[CanvasCalendarEvent],
    ) -> list[AcademicEventCandidate]:
        shared_course_id = f"canvas:course:{course_id}"
        quiz_assignment_ids = {
            str(quiz.assignment_id) for quiz in quizzes if quiz.assignment_id is not None
        }
        assignments_by_id = {str(assignment.id): assignment for assignment in assignments}
        candidates: list[AcademicEventCandidate] = []

        for assignment in assignments:
            if assignment.due_at is None or str(assignment.id) in quiz_assignment_ids:
                continue
            inferred_kind = _event_kind(assignment.name)
            candidates.append(
                AcademicEventCandidate(
                    id=f"canvas:assignment:{assignment.id}",
                    course_id=shared_course_id,
                    source_id=f"canvas:assignment:{assignment.id}",
                    kind=(
                        EventKind.QUIZ
                        if assignment.is_quiz
                        else inferred_kind
                        if inferred_kind is not EventKind.OTHER
                        else EventKind.ASSIGNMENT
                    ),
                    title=assignment.name,
                    start_at=assignment.due_at,
                    source_url=assignment.html_url,
                    evidence=f"Canvas structured due_at: {assignment.due_at.isoformat()}",
                    confidence=1.0,
                    submitted=bool(assignment.submission and assignment.submission.submitted),
                )
            )

        for quiz in quizzes:
            linked_assignment = (
                assignments_by_id.get(str(quiz.assignment_id))
                if quiz.assignment_id is not None
                else None
            )
            due_at = linked_assignment.due_at if linked_assignment else quiz.due_at
            if due_at is None:
                continue
            candidates.append(
                AcademicEventCandidate(
                    id=f"canvas:quiz:{quiz.id}",
                    course_id=shared_course_id,
                    source_id=f"canvas:quiz:{quiz.id}",
                    kind=EventKind.QUIZ,
                    title=quiz.title,
                    start_at=due_at,
                    source_url=quiz.html_url,
                    evidence=f"Canvas structured due_at: {due_at.isoformat()}",
                    confidence=1.0,
                    submitted=bool(
                        linked_assignment
                        and linked_assignment.submission
                        and linked_assignment.submission.submitted
                    ),
                )
            )

        for event in calendar_events:
            if event.start_at is None and event.all_day_date is None:
                continue
            candidates.append(
                AcademicEventCandidate(
                    id=f"canvas:calendar-event:{event.id}",
                    course_id=shared_course_id,
                    source_id=f"canvas:calendar-event:{event.id}",
                    kind=_event_kind(event.title),
                    title=event.title,
                    start_at=None if event.all_day_date else event.start_at,
                    end_at=None if event.all_day_date else event.end_at,
                    all_day_date=event.all_day_date,
                    location=event.location_name,
                    source_url=event.html_url,
                    evidence=(
                        f"Canvas structured all_day_date: {event.all_day_date.isoformat()}"
                        if event.all_day_date
                        else f"Canvas structured start_at: {event.start_at.isoformat()}"
                    ),
                    confidence=1.0,
                )
            )

        return candidates

    def _get_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        model: type[BaseModel],
    ) -> list[Any]:
        results: list[Any] = []
        url: str | None = path
        request_params = params
        page_count = 0
        while url:
            page_count += 1
            if page_count > 100:
                raise CanvasAPIError("Canvas pagination exceeded the safety limit")
            response = self._get(url, params=request_params)
            request_params = None
            try:
                payload = response.json()
            except ValueError as exc:
                raise CanvasAPIError("Canvas returned invalid JSON") from exc
            if not isinstance(payload, list):
                raise CanvasAPIError("Canvas returned an unexpected paginated response")
            try:
                results.extend(model.model_validate(item) for item in payload)
            except ValidationError as exc:
                raise CanvasAPIError("Canvas returned an unexpected response schema") from exc
            url = self._next_url(response)
        return results

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._get(path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise CanvasAPIError("Canvas returned invalid JSON") from exc

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self._max_retries:
                    raise CanvasAPIError("Canvas is temporarily unreachable") from exc
                self._sleep(0.25 * (2**attempt))
                continue

            if response.status_code in {401, 403}:
                raise CanvasAuthenticationError("Canvas rejected the access token")
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                self._sleep(0.25 * (2**attempt))
                continue
            if response.is_error:
                raise CanvasAPIError(f"Canvas request failed with status {response.status_code}")
            return response
        raise AssertionError("retry loop did not return")

    def _next_url(self, response: httpx.Response) -> str | None:
        next_link = response.links.get("next")
        if not next_link:
            return None
        next_url = urljoin(str(response.request.url), next_link["url"])
        try:
            parsed = urlparse(next_url)
            expected_port = self._origin.port or 443
            actual_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise CanvasAPIError("Canvas returned an unsafe pagination link") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != self._origin.hostname
            or actual_port != expected_port
        ):
            raise CanvasAPIError("Canvas returned an unsafe pagination link")
        return next_url

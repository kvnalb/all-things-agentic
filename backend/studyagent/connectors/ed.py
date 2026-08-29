from __future__ import annotations

import json
import re
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from studyagent.models import Course


DEFAULT_BASE_URL = "https://us.edstem.org/api"
STAFF_ROLES = frozenset({"admin", "instructor", "moderator", "staff", "tutor"})
ACTIVE_STATES = frozenset({"active", "current", "open"})
INACTIVE_STATES = frozenset({"archived", "closed", "inactive", "past"})


class EdConnectorError(RuntimeError):
    """A safe, user-displayable Ed connector failure."""


class EdAuthenticationError(EdConnectorError):
    pass


class EdResponseError(EdConnectorError):
    pass


class EdTransport(Protocol):
    def get(
        self, path: str, *, token: str, params: Mapping[str, str | int] | None = None
    ) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class UrllibEdTransport:
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_delay_seconds: float = 0.25
    opener: Callable[..., Any] = urlopen
    sleeper: Callable[[float], None] = time.sleep

    def get(
        self, path: str, *, token: str, params: Mapping[str, str | int] | None = None
    ) -> Mapping[str, Any]:
        if not token.strip():
            raise EdAuthenticationError("Ed token is required")

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "StudyAgent/0.1",
            },
        )

        for attempt in range(self.max_retries + 1):
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise EdResponseError("Ed returned an unexpected response")
                return payload
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise EdAuthenticationError("Ed rejected the token") from None
                if exc.code != 429 and exc.code < 500:
                    raise EdConnectorError(f"Ed request failed with status {exc.code}") from None
                if attempt == self.max_retries:
                    raise EdConnectorError("Ed is temporarily unavailable") from None
            except (TimeoutError, socket.timeout, URLError):
                if attempt == self.max_retries:
                    raise EdConnectorError("Ed could not be reached") from None
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise EdResponseError("Ed returned an unreadable response") from None

            self.sleeper(self.retry_delay_seconds * (2**attempt))

        raise AssertionError("retry loop exhausted")


class EdUser(BaseModel):
    id: str
    name: str


class EdCourse(BaseModel):
    id: str
    code: str
    name: str


class MatchMethod(StrEnum):
    MANUAL = "manual"
    EXACT_CODE = "exact_code"
    EXACT_NAME = "exact_name"
    CONTAINED = "contained"
    SIMILAR_NAME = "similar_name"
    UNMATCHED = "unmatched"


class EdCourseMatch(BaseModel):
    canvas_course_id: str
    ed_course_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: MatchMethod


class EdStaffThread(BaseModel):
    id: str
    course_id: str
    title: str
    content: str = ""
    kind: str
    pinned: bool = False
    created_at: datetime
    updated_at: datetime


class EdConnector:
    def __init__(
        self,
        transport: EdTransport | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        recent_days: int = 14,
        max_thread_pages: int = 3,
        thread_page_size: int = 30,
    ) -> None:
        self._transport = transport or UrllibEdTransport()
        self._now = now or (lambda: datetime.now(UTC))
        self._recent_days = recent_days
        self._max_thread_pages = max_thread_pages
        self._thread_page_size = thread_page_size

    def validate_user(self, token: str) -> EdUser:
        payload = self._transport.get("/user", token=token)
        raw_user = payload.get("user")
        if not isinstance(raw_user, Mapping):
            raise EdResponseError("Ed user response is missing user details")
        try:
            return EdUser(
                id=str(raw_user["id"]),
                name=str(raw_user.get("name") or raw_user.get("email") or "Ed user"),
            )
        except (KeyError, ValidationError):
            raise EdResponseError("Ed user response is missing required fields") from None

    def discover_active_courses(self, token: str) -> list[EdCourse]:
        payload = self._transport.get("/user", token=token)
        raw_user = payload.get("user")
        nested_courses = raw_user.get("courses") if isinstance(raw_user, Mapping) else None
        raw_courses = nested_courses if isinstance(nested_courses, list) else payload.get("courses")
        if not isinstance(raw_courses, list):
            raise EdResponseError("Ed user response is missing courses")

        courses: list[EdCourse] = []
        for raw in raw_courses:
            if not isinstance(raw, Mapping) or not _course_is_active(raw):
                continue
            try:
                courses.append(
                    EdCourse(
                        id=str(raw["id"]),
                        code=str(raw.get("code") or raw.get("short_name") or "").strip(),
                        name=str(raw.get("name") or raw.get("title") or "").strip(),
                    )
                )
            except (KeyError, ValidationError):
                raise EdResponseError("Ed course response is missing required fields") from None
        return courses

    def relevant_staff_threads(self, token: str, course_id: str) -> list[EdStaffThread]:
        cutoff = self._now().astimezone(UTC) - timedelta(days=self._recent_days)
        selected: list[EdStaffThread] = []

        for page in range(self._max_thread_pages):
            payload = self._transport.get(
                f"/courses/{course_id}/threads",
                token=token,
                params={"limit": self._thread_page_size, "offset": page * self._thread_page_size},
            )
            raw_threads = payload.get("threads")
            if not isinstance(raw_threads, list):
                raise EdResponseError("Ed thread response is missing threads")

            for raw in raw_threads:
                thread = _select_staff_thread(raw, course_id=course_id, cutoff=cutoff)
                if thread is not None:
                    selected.append(thread)

            if len(raw_threads) < self._thread_page_size:
                break

        return selected


def match_courses(
    canvas_courses: list[Course],
    ed_courses: list[EdCourse],
    overrides: Mapping[str, str] | None = None,
) -> list[EdCourseMatch]:
    overrides = overrides or {}
    ed_by_id = {course.id: course for course in ed_courses}
    matches: list[EdCourseMatch] = []

    for canvas in canvas_courses:
        override = overrides.get(canvas.id)
        if override is not None:
            if override not in ed_by_id:
                raise EdResponseError(f"Manual Ed course mapping is invalid for {canvas.code}")
            matches.append(
                EdCourseMatch(
                    canvas_course_id=canvas.id,
                    ed_course_id=override,
                    confidence=1,
                    method=MatchMethod.MANUAL,
                )
            )
            continue

        scored = [_score_course_match(canvas, ed) for ed in ed_courses]
        viable = [match for match in scored if match.ed_course_id is not None]
        best = max(viable, key=lambda match: match.confidence, default=None)
        if best is None or best.confidence < 0.88:
            matches.append(
                EdCourseMatch(
                    canvas_course_id=canvas.id,
                    confidence=0,
                    method=MatchMethod.UNMATCHED,
                )
            )
        else:
            matches.append(best)

    return matches


def _score_course_match(canvas: Course, ed: EdCourse) -> EdCourseMatch:
    canvas_code = _normalize_course_code(canvas.code)
    ed_code = _normalize_course_code(ed.code)
    canvas_name = _normalize(canvas.title)
    ed_name = _normalize(ed.name)

    if canvas_code and canvas_code == ed_code:
        score, method = 1.0, MatchMethod.EXACT_CODE
    elif canvas_name and canvas_name == ed_name:
        score, method = 1.0, MatchMethod.EXACT_NAME
    elif min(len(canvas_code), len(ed_code)) >= 4 and (
        canvas_code in ed_code or ed_code in canvas_code
    ):
        score, method = 0.95, MatchMethod.CONTAINED
    else:
        score = SequenceMatcher(None, canvas_name, ed_name).ratio()
        method = MatchMethod.SIMILAR_NAME

    return EdCourseMatch(
        canvas_course_id=canvas.id,
        ed_course_id=ed.id,
        confidence=score,
        method=method,
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _normalize_course_code(value: str) -> str:
    normalized = value.casefold().replace("computer science", "cs").replace("compsci", "cs")
    normalized = _normalize(normalized)
    return re.sub(r"(?<=[a-z])c(?=\d)", "", normalized)


def _course_is_active(raw: Mapping[str, Any]) -> bool:
    state = str(raw.get("status") or raw.get("state") or "").casefold()
    if state in INACTIVE_STATES:
        return False
    if state in ACTIVE_STATES:
        return True
    if "is_active" in raw:
        return bool(raw["is_active"])
    if "archived" in raw:
        return not bool(raw["archived"])
    return True


def _select_staff_thread(
    raw: Any, *, course_id: str, cutoff: datetime
) -> EdStaffThread | None:
    if not isinstance(raw, Mapping):
        return None
    author = raw.get("user") or raw.get("author")
    if not isinstance(author, Mapping):
        return None
    role = str(author.get("role") or "").casefold()
    if not bool(author.get("is_staff")) and role not in STAFF_ROLES:
        return None
    if bool(raw.get("is_private") or raw.get("private")):
        return None

    kind = str(raw.get("type") or raw.get("kind") or "post").casefold()
    is_announcement = bool(raw.get("is_announcement")) or kind == "announcement"
    is_pinned = bool(raw.get("is_pinned") or raw.get("pinned"))
    try:
        created_at = _parse_datetime(raw["created_at"])
        updated_at = _parse_datetime(raw.get("updated_at") or raw["created_at"])
        recent = max(created_at, updated_at) >= cutoff
        if not (is_announcement or is_pinned or recent):
            return None
        return EdStaffThread(
            id=str(raw["id"]),
            course_id=course_id,
            title=str(raw.get("title") or "Untitled staff post"),
            content=_thread_content(raw),
            kind="announcement" if is_announcement else kind,
            pinned=is_pinned,
            created_at=created_at,
            updated_at=updated_at,
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise EdResponseError("Ed thread response contains an invalid staff thread") from None


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _thread_content(raw: Mapping[str, Any]) -> str:
    content = raw.get("content")
    if isinstance(content, str):
        return content
    document = raw.get("document")
    if isinstance(document, str):
        return document
    return ""

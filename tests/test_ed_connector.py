from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError

from studyagent.api.ed import EdConnectRequest, connect_ed_with
from studyagent.connectors.ed import (
    EdAuthenticationError,
    EdConnector,
    EdCourse,
    EdResponseError,
    MatchMethod,
    UrllibEdTransport,
    match_courses,
)
from studyagent.models import ConnectionState, Course


FIXTURES = Path(__file__).parent / "fixtures" / "ed"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class FakeTransport:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, object]] = []
        self.error: Exception | None = None

    def get(self, path: str, *, token: str, params: object = None) -> dict[str, Any]:
        self.calls.append((path, token, params))
        if self.error:
            raise self.error
        return self.responses[path]


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def canvas_course(course_id: str = "canvas-189") -> Course:
    return Course(
        id=course_id,
        code="COMPSCI 189",
        title="Introduction to Machine Learning",
        term="Fall 2026",
        selected=True,
    )


class EdConnectorTests(unittest.TestCase):
    def test_validates_user_and_discovers_only_active_courses(self) -> None:
        transport = FakeTransport({"/user": fixture("user.json")})
        connector = EdConnector(transport)

        user = connector.validate_user("secret-token")
        courses = connector.discover_active_courses("secret-token")

        self.assertEqual(user.name, "Sample Student")
        self.assertEqual([course.id for course in courses], ["501", "502"])
        self.assertEqual(
            transport.calls,
            [
                ("/user", "secret-token", None),
                ("/user", "secret-token", None),
            ],
        )

    def test_course_matching_is_conservative_and_manual_override_wins(self) -> None:
        canvas = [canvas_course(), canvas_course("canvas-data")]
        canvas[1].code = "DATA 100"
        canvas[1].title = "A renamed class that should not fuzzy-match"
        ed = [
            EdCourse(id="501", code="CS189", name="Introduction to Machine Learning"),
            EdCourse(id="502", code="DATA C100", name="Principles of Data Science"),
        ]

        matches = match_courses(canvas, ed, {"canvas-data": "502"})

        self.assertEqual(matches[0].ed_course_id, "501")
        self.assertIs(matches[0].method, MatchMethod.EXACT_CODE)
        self.assertEqual(matches[1].ed_course_id, "502")
        self.assertIs(matches[1].method, MatchMethod.MANUAL)

    def test_normalizes_common_berkeley_course_code_variants(self) -> None:
        canvas = canvas_course()
        canvas.title = "A differently named course"
        ed = [EdCourse(id="501", code="CS 189", name="Machine Learning")]

        match = match_courses([canvas], ed)[0]

        self.assertEqual(match.ed_course_id, "501")
        self.assertIs(match.method, MatchMethod.EXACT_CODE)

    def test_rejects_unknown_manual_override(self) -> None:
        with self.assertRaisesRegex(EdResponseError, "Manual Ed course mapping is invalid"):
            match_courses([canvas_course()], [], {"canvas-189": "missing"})

    def test_transport_retries_transient_failure_with_explicit_timeout(self) -> None:
        outcomes: list[Exception | FakeResponse] = [
            URLError("temporary"),
            FakeResponse(b'{"user":{"id":42}}'),
        ]
        timeouts: list[float] = []
        delays: list[float] = []

        def opener(request: object, *, timeout: float) -> FakeResponse:
            timeouts.append(timeout)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        transport = UrllibEdTransport(
            timeout_seconds=3,
            max_retries=1,
            retry_delay_seconds=0.1,
            opener=opener,
            sleeper=delays.append,
        )

        payload = transport.get("/user", token="secret-token")

        self.assertEqual(payload["user"]["id"], 42)
        self.assertEqual(timeouts, [3, 3])
        self.assertEqual(delays, [0.1])

    def test_keeps_only_public_staff_announcements_pinned_and_recent_threads(self) -> None:
        transport = FakeTransport(
            {
                "/courses/501/threads": fixture("threads.json"),
            }
        )
        connector = EdConnector(
            transport,
            now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
            thread_page_size=30,
        )

        threads = connector.relevant_staff_threads("secret-token", "501")

        self.assertEqual([thread.id for thread in threads], ["1001", "1002", "1003"])
        self.assertEqual({thread.kind for thread in threads}, {"announcement", "post"})
        self.assertIn("midterm room list", threads[0].content)
        returned_content = " ".join(thread.content for thread in threads)
        self.assertNotIn("private content", returned_content)
        self.assertNotIn("student content", returned_content)
        self.assertEqual(len(transport.calls), 1)

    def test_optional_api_failure_is_safe_and_never_returns_token(self) -> None:
        transport = FakeTransport()
        transport.error = EdAuthenticationError("Ed rejected the token")
        request = EdConnectRequest(token="do-not-expose", canvas_courses=[canvas_course()])

        response = connect_ed_with(request, EdConnector(transport))

        self.assertIs(response.result.state, ConnectionState.ERROR)
        self.assertEqual(response.result.message, "Ed rejected the token")
        self.assertEqual(response.courses, [])
        self.assertNotIn("do-not-expose", response.model_dump_json())

    def test_successful_api_connect_maps_and_fetches_only_matched_courses(self) -> None:
        transport = FakeTransport(
            {
                "/user": fixture("user.json"),
                "/courses/501/threads": fixture("threads.json"),
            }
        )
        connector = EdConnector(
            transport,
            now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
            thread_page_size=30,
        )

        response = connect_ed_with(
            EdConnectRequest(token="secret-token", canvas_courses=[canvas_course()]),
            connector,
        )

        self.assertIs(response.result.state, ConnectionState.CONNECTED)
        self.assertEqual(response.result.discovered_course_ids, ["501", "502"])
        self.assertEqual(response.matches[0].ed_course_id, "501")
        self.assertEqual(len(response.staff_threads), 3)
        self.assertTrue(all("/courses/502/threads" != call[0] for call in transport.calls))

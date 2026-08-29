from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from studyagent.api.canvas import CanvasConnectRequest
from studyagent.connectors.canvas import (
    BCOURSES_BASE_URL,
    CanvasAPIError,
    CanvasAuthenticationError,
    CanvasClient,
    CanvasSelectionError,
)
from studyagent.models import EventKind


FIXTURES = Path(__file__).parent / "fixtures" / "canvas"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def json_response(request: httpx.Request, data: object, **kwargs: object) -> httpx.Response:
    return httpx.Response(200, request=request, json=data, **kwargs)


class CanvasClientTests(unittest.TestCase):
    def client(self, handler: httpx.MockTransport, *, max_retries: int = 2) -> CanvasClient:
        http_client = httpx.Client(
            base_url=BCOURSES_BASE_URL,
            headers={"Authorization": "Bearer test-token"},
            transport=handler,
        )
        self.addCleanup(http_client.close)
        return CanvasClient(
            "test-token", client=http_client, max_retries=max_retries, sleep=lambda _: None
        )

    def test_invalid_token_fails_without_exposing_it(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")
            return httpx.Response(401, request=request, json={"message": "bad token"})

        with self.assertRaisesRegex(CanvasAuthenticationError, "rejected") as caught:
            self.client(httpx.MockTransport(handler)).validate()

        self.assertNotIn("test-token", str(caught.exception))
        self.assertNotIn("bad token", str(caught.exception))

    def test_discovers_fall_courses_across_opaque_link_pagination(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            if request.url.params.get("page") == "opaque-second":
                return json_response(request, fixture("courses-page-2.json"))
            return json_response(
                request,
                fixture("courses-page-1.json"),
                headers={
                    "Link": (
                        f'<{BCOURSES_BASE_URL}/api/v1/courses?page=opaque-second>; rel="next"'
                    )
                },
            )

        discovery = self.client(httpx.MockTransport(handler)).discover_courses()

        self.assertEqual([str(course.id) for course in discovery.courses], ["101", "202"])
        self.assertEqual(discovery.profile.identity_label, "Demo")
        self.assertEqual(requests[1].url.params.get("enrollment_state"), "active")
        self.assertEqual(requests[1].url.params.get_list("include[]"), ["term", "syllabus_body"])
        self.assertEqual(requests[2].url.params.get("page"), "opaque-second")
        self.assertIsNone(requests[2].url.params.get("include[]"))

    def test_rejects_cross_origin_pagination_before_forwarding_token(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            if request.url.path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            return json_response(
                request,
                fixture("courses-page-1.json"),
                headers={"Link": '<https://attacker.invalid/steal>; rel="next"'},
            )

        with self.assertRaisesRegex(CanvasAPIError, "unsafe pagination"):
            self.client(httpx.MockTransport(handler)).discover_courses()
        self.assertEqual(request_count, 2)

    def test_malformed_pagination_port_is_canvas_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            return json_response(
                request,
                fixture("courses-page-1.json"),
                headers={
                    "Link": f'<{BCOURSES_BASE_URL}:not-a-port/api/v1/courses?page=2>; rel="next"'
                },
            )

        with self.assertRaises(CanvasAPIError):
            self.client(httpx.MockTransport(handler)).discover_courses()

    def test_course_ids_are_percent_encoded_in_path_segments(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return json_response(request, fixture("assignments.json"))

        self.client(httpx.MockTransport(handler)).list_assignments("course/id with spaces?")
        self.assertEqual(
            requests[0].url.raw_path.split(b"?", 1)[0].decode(),
            "/api/v1/courses/course%2Fid%20with%20spaces%3F/assignments",
        )

    def test_selected_activity_uses_structured_dates_and_submission_state(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            if path == "/api/v1/courses":
                return json_response(request, fixture("courses-page-1.json"))
            if path == "/api/v1/courses/101":
                return json_response(request, fixture("course.json"))
            if path == "/api/v1/courses/101/assignments":
                return json_response(request, fixture("assignments.json"))
            if path == "/api/v1/courses/101/quizzes":
                return json_response(request, fixture("quizzes.json"))
            if path == "/api/v1/calendar_events":
                return json_response(request, fixture("calendar-events.json"))
            return httpx.Response(404, request=request)

        canvas = self.client(httpx.MockTransport(handler))
        discovery = canvas.discover_courses()
        activity = canvas.selected_activity(discovery, ["101"])[0]

        self.assertTrue(activity.course.selected)
        self.assertIn("Pacific time", activity.syllabus_body or "")
        self.assertEqual(len(activity.candidates), 4)
        candidates = {candidate.id: candidate for candidate in activity.candidates}
        self.assertTrue(candidates["canvas:assignment:501"].eligible_for_auto_import)
        self.assertTrue(candidates["canvas:quiz:601"].submitted)
        self.assertFalse(candidates["canvas:quiz:601"].eligible_for_auto_import)
        self.assertEqual(candidates["canvas:calendar-event:701"].kind, EventKind.EXAM)
        self.assertEqual(
            str(candidates["canvas:calendar-event:701"].source_url),
            "https://bcourses.berkeley.edu/calendar?event_id=701",
        )
        self.assertEqual(
            candidates["canvas:calendar-event:702"].all_day_date.isoformat(), "2026-11-11"
        )

    def test_unknown_course_selection_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            return json_response(request, fixture("courses-page-1.json"))

        canvas = self.client(httpx.MockTransport(handler))
        discovery = canvas.discover_courses()
        with self.assertRaisesRegex(CanvasSelectionError, "not discovered"):
            canvas.selected_activity(discovery, ["999"])

    def test_duplicate_course_selection_fetches_once_in_first_seen_order(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if path == "/api/v1/users/self/profile":
                return json_response(request, fixture("profile.json"))
            if path == "/api/v1/courses":
                return json_response(request, fixture("courses-page-1.json"))
            if path == "/api/v1/courses/101":
                return json_response(request, fixture("course.json"))
            if path == "/api/v1/courses/101/assignments":
                return json_response(request, fixture("assignments.json"))
            if path == "/api/v1/courses/101/quizzes":
                return json_response(request, fixture("quizzes.json"))
            if path == "/api/v1/calendar_events":
                return json_response(request, fixture("calendar-events.json"))
            return httpx.Response(404, request=request)

        canvas = self.client(httpx.MockTransport(handler))
        discovery = canvas.discover_courses()
        activities = canvas.selected_activity(discovery, ["101", "101"])

        self.assertEqual(len(activities), 1)
        self.assertEqual(
            [request.url.path for request in requests if request.url.path.startswith("/api/v1/courses/101")],
            [
                "/api/v1/courses/101",
                "/api/v1/courses/101/assignments",
                "/api/v1/courses/101/quizzes",
            ],
        )

    def test_selection_order_is_preserved_after_deduplication(self) -> None:
        canvas = self.client(httpx.MockTransport(lambda request: httpx.Response(500, request=request)))
        discovery = CanvasClientTests._discovery_for_order_test()
        with patch.object(canvas, "fetch_course_activity", side_effect=lambda course: course) as fetch:
            activities = canvas.selected_activity(discovery, ["202", "101", "202"])

        self.assertEqual([activity.id for activity in activities], [202, 101])
        self.assertEqual(
            [call.args[0].id for call in fetch.call_args_list],
            [202, 101],
        )

    @staticmethod
    def _discovery_for_order_test():
        return CanvasClientTests._discovery_from_payloads(
            fixture("profile.json"), fixture("courses-page-1.json") + fixture("courses-page-2.json")
        )

    @staticmethod
    def _discovery_from_payloads(profile_payload: object, courses_payload: object):
        from studyagent.connectors.canvas import CanvasCourse, CanvasDiscovery, CanvasProfile

        return CanvasDiscovery(
            profile=CanvasProfile.model_validate(profile_payload),
            courses=[CanvasCourse.model_validate(course) for course in courses_payload],
        )

    def test_retries_transient_failure_with_a_strict_bound(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, request=request)
            return json_response(request, fixture("profile.json"))

        profile = self.client(httpx.MockTransport(handler)).validate()
        self.assertEqual(profile.id, 4242)
        self.assertEqual(attempts, 3)

    def test_retry_exhaustion_raises_canvas_api_error(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, request=request)

        with self.assertRaises(CanvasAPIError):
            self.client(httpx.MockTransport(handler), max_retries=1).validate()
        self.assertEqual(attempts, 2)

    def test_api_request_masks_token_in_serialized_diagnostics(self) -> None:
        request = CanvasConnectRequest(token="test-token")
        self.assertNotIn("test-token", repr(request))
        self.assertNotIn("test-token", request.model_dump_json())


if __name__ == "__main__":
    unittest.main()

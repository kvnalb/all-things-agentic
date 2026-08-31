import asyncio
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from studyagent.main import app
from studyagent.taskmaster.canvas import Canvas
from studyagent.taskmaster.donor.agent import apply_effort_estimate, estimate_and_score, parse_task_event
from studyagent.taskmaster.donor.daily_view import build_daily_view
from studyagent.taskmaster.donor.models import Task as DonorTask
from studyagent.taskmaster.donor.taskmaster_calendar import (
    COLOR_PRIORITY,
    _budget_hours,
    _is_priority_course,
    _pick_color,
    _rank_value,
)
from studyagent.taskmaster.google import CalendarWriter, Google
from studyagent.taskmaster.models import CalibrationProfile, UserConfig
from studyagent.taskmaster.service import TaskmasterService


LA = ZoneInfo("America/Los_Angeles")


def _cfg_dict(config: UserConfig) -> dict:
    return {
        "selected_course_ids": list(config.selected_course_ids),
        "priority_mode": config.priority_mode,
        "lead_time_days": config.lead_time_days,
        "reminder_style": config.reminder_style,
        "work_day_start": config.work_day_start,
        "work_day_end": config.work_day_end,
        "off_days": list(config.off_days),
        "priority_courses": list(config.priority_courses),
        "excluded_courses": list(config.excluded_courses),
        "non_canvas_courses": "",
        "daily_cap_hours": config.daily_cap_hours,
        "effort_padding": config.effort_padding,
    }


class DonorParityTest(unittest.TestCase):
    def test_preferences_drive_rank_blocks_and_daily_tiers(self) -> None:
        now = datetime(2026, 9, 2, 9, tzinfo=LA)
        config = UserConfig(
            priority_mode="grade",
            lead_time_days=3,
            daily_cap_hours=4,
            priority_courses=["MATH 110"],
            off_days=["Sun"],
        )
        cfg = _cfg_dict(config)
        math_task = DonorTask(
            source="canvas",
            source_ref="1",
            title="Problem Set",
            course="MATH 110",
            due_at=datetime(2026, 9, 5, 17, tzinfo=LA),
            points_possible=20,
            course_total_points=100,
            estimated_hours=6,
        )
        reading_task = DonorTask(
            source="syllabus",
            source_ref="2",
            title="Reading",
            course="DATA 101",
            due_at=datetime(2026, 9, 12, 17, tzinfo=LA),
            estimated_hours=2,
        )
        self.assertGreater(_rank_value(math_task, cfg), _rank_value(reading_task, cfg))
        self.assertEqual(
            _pick_color(math_task, cfg, math_task.due_at.astimezone()),
            COLOR_PRIORITY,
        )
        briefing = [
            {
                "title": math_task.title,
                "course": math_task.course,
                "due": f"{math_task.due_at.astimezone():%a %b %d %I:%M %p}",
                "_due_dt": math_task.due_at.astimezone(),
                "rank": _rank_value(math_task, cfg),
                "budgeted_hours": _budget_hours(math_task, cfg),
                "from_syllabus": False,
                "priority_course": _is_priority_course(math_task, cfg),
            },
            {
                "title": reading_task.title,
                "course": reading_task.course,
                "due": f"{reading_task.due_at.astimezone():%a %b %d %I:%M %p}",
                "_due_dt": reading_task.due_at.astimezone(),
                "rank": _rank_value(reading_task, cfg),
                "budgeted_hours": _budget_hours(reading_task, cfg),
                "from_syllabus": True,
                "priority_course": _is_priority_course(reading_task, cfg),
            },
        ]
        view = build_daily_view(briefing, cfg, now=now)
        self.assertEqual(view["active"][0]["title"], "Problem Set")
        self.assertEqual(view["active"][0]["tier"], "HIGH")

    def test_graph_preserves_task_across_effort_node(self) -> None:
        ctx = SimpleNamespace(state={})
        task = DonorTask(
            source="canvas",
            source_ref="42",
            title="Essay",
            course="HISTORY",
            due_at=datetime(2026, 9, 4, 17, tzinfo=LA),
        )
        parsed = parse_task_event(json.dumps({"data": json.loads(task.model_dump_json())}), ctx)
        self.assertEqual(parsed.output["title"], "Essay")
        estimated = apply_effort_estimate('{"estimated_hours": 8, "confidence": "high"}', ctx)
        self.assertEqual(estimated.output["source_ref"], "42")
        scored = estimate_and_score(estimated.output, ctx)
        self.assertEqual(scored.output["estimated_hours"], 8)
        self.assertIn(getattr(scored.actions, "route", None), {"QUIET", "HIGH_PRIORITY"})

    def test_canvas_role_normalization(self) -> None:
        self.assertEqual(Canvas.role({"enrollments": [{"type": "TaEnrollment"}]}), "ta")
        self.assertEqual(Canvas.role({"enrollments": [{"type": "StudentEnrollment"}]}), "student")

    def test_canvas_file_download_follows_provider_redirect(self) -> None:
        canvas = Canvas.__new__(Canvas)
        canvas.token = "not-a-real-token"
        response = MagicMock(status_code=200)
        with patch("studyagent.taskmaster.canvas.httpx.get", return_value=response) as request:
            self.assertIs(canvas.download("https://bcourses.berkeley.edu/files/1/download"), response)
        self.assertTrue(request.call_args.kwargs["follow_redirects"])

    def test_optional_canvas_endpoint_treats_404_as_empty(self) -> None:
        for status in (403, 404):
            with self.subTest(status=status):
                response = MagicMock(status_code=status)
                client = MagicMock()
                client.__enter__.return_value.get.return_value = response
                canvas = Canvas.__new__(Canvas)
                canvas.token = "not-a-real-token"
                with patch("studyagent.taskmaster.canvas.httpx.Client", return_value=client):
                    self.assertEqual(canvas.get("courses/1/quizzes", optional=True), [])

    def test_calendar_binding_skips_unchanged_and_patches_changed(self) -> None:
        binding = {"google_event_id": "event-1", "desired_hash": ""}
        ref = MagicMock()
        ref.get.return_value.to_dict.return_value = binding
        db = MagicMock()
        db.collection.return_value.document.return_value = ref
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.db = db
        service = MagicMock()
        service.events.return_value.patch.return_value.execute.return_value = {"id": "event-1"}
        body = {
            "summary": "Work",
            "start": {"dateTime": "2026-09-02T10:00:00-07:00"},
            "end": {"dateTime": "2026-09-02T11:00:00-07:00"},
        }
        self.assertEqual(writer._write(service, "calendar", "stable", body.copy(), "run-1"), "updated")
        saved_hash = ref.set.call_args.args[0]["desired_hash"]
        ref.get.return_value.to_dict.return_value = {"google_event_id": "event-1", "desired_hash": saved_hash}
        self.assertEqual(writer._write(service, "calendar", "stable", body.copy(), "run-2"), "skipped")

    def test_calendar_reconciliation_deletes_only_stale_managed_bindings(self) -> None:
        stale = MagicMock()
        stale.to_dict.return_value = {"key": "work:old:0", "google_event_id": "old-event"}
        current = MagicMock()
        current.to_dict.return_value = {"key": "work:current:0", "google_event_id": "current-event"}
        db = MagicMock()
        db.collection.return_value.stream.return_value = [stale, current]
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.db = db
        service = MagicMock()
        self.assertEqual(writer._delete_stale(service, "calendar", {"work:current:0"}, "run"), (1, 0))
        service.events.return_value.delete.assert_called_once_with(calendarId="calendar", eventId="old-event")

    def test_private_api_and_scheduler_require_authentication(self) -> None:
        client = TestClient(app)
        with patch("studyagent.taskmaster.api.State") as state:
            state.return_value.valid_session.return_value = False
            self.assertEqual(client.get("/api/status").status_code, 401)
        self.assertEqual(client.post("/internal/sync").status_code, 401)

    def test_oauth_pkce_verifier_survives_stateless_redirect(self) -> None:
        google = Google.__new__(Google)
        google.state = MagicMock()
        google.secrets = MagicMock()
        google.state.create_oauth_state.return_value = ("state", "verifier")
        google.state.consume_oauth_state.return_value = "verifier"
        google.state.create_session.return_value = "session"
        google.secrets.read.return_value = json.dumps(
            {
                "web": {
                    "client_id": "id",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.example/auth",
                    "token_uri": "https://accounts.example/token",
                }
            }
        )
        google.secrets.add.return_value = "projects/p/secrets/token/versions/1"
        start_flow = MagicMock()
        start_flow.authorization_url.return_value = ("https://accounts.example/authorize", "state")
        callback_flow = MagicMock()
        callback_flow.credentials.token = "access-token"
        callback_flow.credentials.to_json.return_value = "{}"
        userinfo = MagicMock()
        userinfo.json.return_value = {"email": "owner@example.com"}
        userinfo.raise_for_status.return_value = None
        with (
            patch("studyagent.taskmaster.google.Settings.allowed_email", "owner@example.com"),
            patch("studyagent.taskmaster.google.Flow.from_client_config", side_effect=[start_flow, callback_flow]) as factory,
            patch("studyagent.taskmaster.google.httpx.get", return_value=userinfo),
            patch.object(google, "_calendar", return_value="calendar"),
        ):
            self.assertEqual(google.start_url(), "https://accounts.example/authorize")
            self.assertEqual(google.callback("state", "code"), "session")
        self.assertEqual(factory.call_args_list[0].kwargs["code_verifier"], "verifier")
        self.assertEqual(factory.call_args_list[1].kwargs["code_verifier"], "verifier")


class ServiceEstimateTest(unittest.IsolatedAsyncioTestCase):
    async def test_estimate_failure_falls_back_to_default_hours(self) -> None:
        service = TaskmasterService.__new__(TaskmasterService)
        service.runner = MagicMock()
        service.runner.process.side_effect = RuntimeError("graph failed")
        task = DonorTask(
            source="canvas",
            source_ref="1",
            title="Quiz",
            course="DATA 101",
            due_at=datetime(2026, 9, 4, 17, tzinfo=LA),
        )
        updated, failed, _raw = await service._estimate(
            task, _cfg_dict(UserConfig()), CalibrationProfile(), asyncio.Semaphore(1)
        )
        self.assertEqual(failed, 1)
        self.assertEqual(updated.estimated_hours, 2.0)


if __name__ == "__main__":
    unittest.main()

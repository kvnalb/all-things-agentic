import unittest
from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch

from googleapiclient.errors import HttpError

from studyagent.taskmaster.canonical_tasks import (
    busy_intervals_from_timed_events,
    canonical_to_donor_tasks,
)
from studyagent.taskmaster.donor.taskmaster_calendar import LA, _advance_to_workable, _overlaps_busy, _place_blocks
from studyagent.taskmaster.donor.models import Task as DonorTask
from studyagent.taskmaster.google import CalendarWriter, _execute_calendar, _is_rate_limited
from studyagent.taskmaster.models import (
    AcademicClaim,
    CanonicalScheduleItem,
    ClaimProvenance,
    ClaimStatus,
    EventKind,
    TimedScheduleItem,
)


class CanonicalTasksTest(unittest.TestCase):
    def test_canonical_to_donor_tasks_keeps_ready_items_only(self) -> None:
        due = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
        canonical = [
            CanonicalScheduleItem(
                id="ready-1",
                group_key="g1",
                title="Lab 1",
                course_label="DATA 144",
                due_at=due,
                status=ClaimStatus.READY,
                chosen_claim_id="claim-1",
            ),
            CanonicalScheduleItem(
                id="review-1",
                group_key="g2",
                title="PS 1",
                course_label="DATA 144",
                due_at=due,
                status=ClaimStatus.REVIEW_REQUIRED,
            ),
        ]
        claims = [
            AcademicClaim(
                id="claim-1",
                course_label="DATA 144",
                title="Lab 1",
                provenance=ClaimProvenance.MANUAL,
                source_ref="1",
                points_possible=10.0,
            )
        ]
        kept, skipped = canonical_to_donor_tasks(canonical, claims, {})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].source_ref, "ready-1")
        self.assertEqual(kept[0].points_possible, 10.0)
        self.assertEqual(skipped, [])

    def test_busy_intervals_skip_optional_events(self) -> None:
        start = datetime(2026, 10, 5, 17, 0, tzinfo=UTC)
        intervals = busy_intervals_from_timed_events(
            [
                TimedScheduleItem(
                    id="e1",
                    event_id="1",
                    occurrence_id="1",
                    course_label="ECON 136",
                    title="Midterm 1",
                    kind=EventKind.EXAM,
                    start_at=start,
                    end_at=datetime(2026, 10, 5, 19, 0, tzinfo=UTC),
                    optional=False,
                    is_mine=True,
                ),
                TimedScheduleItem(
                    id="e2",
                    event_id="2",
                    occurrence_id="2",
                    course_label="DATA 101",
                    title="Optional review",
                    kind=EventKind.QUIZ,
                    start_at=start,
                    optional=True,
                    is_mine=True,
                ),
            ]
        )
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0][0], start)


class CalendarPlacementTest(unittest.TestCase):
    def test_advance_to_workable_moves_early_morning_to_work_window(self) -> None:
        cursor = datetime(2026, 8, 30, 3, 0, tzinfo=LA)
        cfg = {"work_day_start": 9, "work_day_end": 21, "off_days": []}
        result = _advance_to_workable(cursor, cfg)
        self.assertEqual(result.tzinfo, LA)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 0)

    def test_advance_to_workable_normalizes_utc_cursor_to_pacific(self) -> None:
        # 10:00 UTC is 03:00 Pacific in late August — should land at 09:00 Pacific.
        cursor = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
        cfg = {"work_day_start": 9, "work_day_end": 21, "off_days": []}
        result = _advance_to_workable(cursor, cfg)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.tzinfo, LA)

    def test_overlaps_busy_returns_end_of_blocking_interval(self) -> None:
        busy_start = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
        busy_end = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
        start = datetime(2026, 9, 8, 13, 0, tzinfo=UTC)
        end = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
        self.assertEqual(_overlaps_busy(start, end, [(busy_start, busy_end)]), busy_end)

    def test_place_blocks_never_overlap(self) -> None:
        due = datetime(2026, 9, 15, 17, 0, tzinfo=LA)
        tasks = [
            DonorTask(
                source="canonical",
                source_ref="a",
                title="Lab A",
                course="DATA 144",
                due_at=due,
                estimated_hours=4,
                priority_score=2.0,
            ),
            DonorTask(
                source="canonical",
                source_ref="b",
                title="Lab B",
                course="ECON 136",
                due_at=due,
                estimated_hours=4,
                priority_score=1.5,
            ),
        ]
        placements: list[dict] = []
        cfg = {
            "work_day_start": 9,
            "work_day_end": 21,
            "off_days": [],
            "daily_cap_hours": 8,
            "lead_time_days": 5,
            "effort_padding": 1.0,
        }
        _place_blocks(
            None,
            None,
            tasks,
            cfg,
            block_writer=lambda **kwargs: placements.append(kwargs),
        )
        ordered = sorted(placements, key=lambda row: row["start"])
        self.assertGreaterEqual(len(ordered), 2)
        for left, right in zip(ordered, ordered[1:], strict=False):
            self.assertLessEqual(left["end"], right["start"])


class CalendarWriterRegistrySyncTest(unittest.TestCase):
    def test_sync_registry_calendar_writes_work_due_and_academic_keys(self) -> None:
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.state = MagicMock()
        writer.state.connection.return_value = {"calendar_id": "cal-1"}
        writer.db = MagicMock()
        written_keys: list[str] = []

        def fake_write(service, calendar_id, key, body, run_id, *, audit=None):
            written_keys.append(key)
            return "created"

        writer._write = fake_write  # type: ignore[method-assign]
        writer._delete_stale = MagicMock(return_value=(0, 0))  # type: ignore[method-assign]

        due = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
        task = MagicMock()
        task.source = "canonical"
        task.source_ref = "ready-1"
        task.title = "Lab 1"
        task.course = "DATA 144"
        task.due_at = due
        task.priority_score = 1.2

        with patch("studyagent.taskmaster.google.build"):
            with patch("studyagent.taskmaster.google.Google") as google:
                google.return_value.credentials.return_value = MagicMock()
                counts = writer.sync_registry_calendar(
                    placements=[
                        {
                            "task": task,
                            "start": datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
                            "end": datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
                            "color_id": "10",
                            "block_index": 0,
                        }
                    ],
                    canonical=[
                        CanonicalScheduleItem(
                            id="ready-1",
                            group_key="g1",
                            title="Lab 1",
                            course_label="DATA 144",
                            due_at=due,
                            status=ClaimStatus.READY,
                        )
                    ],
                    timed_events=[
                        TimedScheduleItem(
                            id="exam-1",
                            event_id="1",
                            occurrence_id="1",
                            course_label="ECON 136",
                            title="Midterm 1",
                            kind=EventKind.EXAM,
                            start_at=datetime(2026, 10, 5, 17, 0, tzinfo=UTC),
                            end_at=datetime(2026, 10, 5, 19, 0, tzinfo=UTC),
                        )
                    ],
                    run_id="run-1",
                )

        self.assertIn("work:canonical:ready-1:0", written_keys)
        self.assertIn("deadline:canonical:ready-1", written_keys)
        self.assertIn("academic:exam-1", written_keys)
        self.assertEqual(counts["created"], 3)


class CalendarRateLimitTest(unittest.TestCase):
    def test_is_rate_limited_detects_403_usage_limits(self) -> None:
        exc = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
        )
        self.assertTrue(_is_rate_limited(exc))

    def test_execute_calendar_retries_then_succeeds(self) -> None:
        calls = {"count": 0}

        def request() -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                raise HttpError(
                    resp=MagicMock(status=403),
                    content=b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
                )
            return "ok"

        with patch("studyagent.taskmaster.google.time.sleep"):
            self.assertEqual(_execute_calendar(request), "ok")
        self.assertEqual(calls["count"], 2)

    def test_delete_stale_defers_remaining_bindings_after_rate_limit(self) -> None:
        stale_one = MagicMock()
        stale_one.to_dict.return_value = {"key": "work:old:0", "google_event_id": "old-event-1"}
        stale_two = MagicMock()
        stale_two.to_dict.return_value = {"key": "work:old:1", "google_event_id": "old-event-2"}
        db = MagicMock()
        db.collection.return_value.stream.return_value = [stale_one, stale_two]
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.db = db
        service = MagicMock()
        service.events.return_value.delete.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
        )

        with (
            patch("studyagent.taskmaster.google._execute_calendar", side_effect=lambda fn: fn()),
            patch("studyagent.taskmaster.google.time.sleep"),
        ):
            deleted, deferred = writer._delete_stale(service, "calendar", set(), "run")

        self.assertEqual(deleted, 0)
        self.assertEqual(deferred, 2)
        stale_one.reference.set.assert_called_with(
            {"state": "delete_deferred", "run_id": "run", "attempted_at": ANY},
            merge=True,
        )
        stale_one.reference.delete.assert_not_called()


class CalendarEventEditsTest(unittest.TestCase):
    def test_create_event_inserts_on_app_calendar(self) -> None:
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.state = MagicMock()
        writer.state.connection.return_value = {"calendar_id": "cal-1"}
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {"items": []}
        service.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt-1",
            "summary": "Office hours",
        }
        start = datetime(2026, 9, 3, 10, tzinfo=UTC)
        end = datetime(2026, 9, 3, 11, tzinfo=UTC)
        with (
            patch("studyagent.taskmaster.google.Google") as google,
            patch("studyagent.taskmaster.google.build", return_value=service),
            patch("studyagent.taskmaster.google._execute_calendar", side_effect=lambda fn: fn()),
        ):
            google.return_value.credentials.return_value = MagicMock()
            result = writer.create_event(summary="Office hours", start=start, end=end)
        self.assertEqual(result["id"], "evt-1")
        service.events.return_value.insert.assert_called_once()

    def test_patch_event_requires_a_field(self) -> None:
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.state = MagicMock()
        writer.state.connection.return_value = {"calendar_id": "cal-1"}
        with self.assertRaises(ValueError):
            writer.patch_event("evt-1")

    def test_client_passes_http_with_timeout(self) -> None:
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.state = MagicMock()
        writer.state.connection.return_value = {"calendar_id": "cal-1"}
        with (
            patch("studyagent.taskmaster.google.Google") as google,
            patch("studyagent.taskmaster.google.build") as build,
        ):
            google.return_value.credentials.return_value = MagicMock()
            writer._client()
        http = build.call_args.kwargs.get("http")
        self.assertIsNotNone(http)
        inner = getattr(http, "http", http)
        self.assertTrue(getattr(inner, "timeout", None))

    def test_create_event_reuses_existing_for_same_identity(self) -> None:
        writer = CalendarWriter.__new__(CalendarWriter)
        writer.state = MagicMock()
        writer.state.connection.return_value = {"calendar_id": "cal-1"}
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "evt-1", "summary": "Office hours"}],
        }
        start = datetime(2026, 9, 3, 10, tzinfo=UTC)
        end = datetime(2026, 9, 3, 11, tzinfo=UTC)
        with (
            patch("studyagent.taskmaster.google.Google") as google,
            patch("studyagent.taskmaster.google.build", return_value=service),
            patch("studyagent.taskmaster.google._execute_calendar", side_effect=lambda fn: fn()),
        ):
            google.return_value.credentials.return_value = MagicMock()
            result = writer.create_event(summary="Office hours", start=start, end=end)
        self.assertEqual(result["id"], "evt-1")
        service.events.return_value.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()

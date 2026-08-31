import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from studyagent.taskmaster.canonical_tasks import (
    busy_intervals_from_timed_events,
    canonical_to_donor_tasks,
)
from studyagent.taskmaster.donor.taskmaster_calendar import _overlaps_busy
from studyagent.taskmaster.google import CalendarWriter
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
    def test_overlaps_busy_returns_end_of_blocking_interval(self) -> None:
        busy_start = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
        busy_end = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
        start = datetime(2026, 9, 8, 13, 0, tzinfo=UTC)
        end = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
        self.assertEqual(_overlaps_busy(start, end, [(busy_start, busy_end)]), busy_end)


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
        writer._delete_stale = MagicMock(return_value=0)  # type: ignore[method-assign]

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


if __name__ == "__main__":
    unittest.main()

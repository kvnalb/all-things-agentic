import unittest
from unittest.mock import patch

from studyagent.taskmaster.daily_board import enrich_daily_view
from studyagent.taskmaster.voice import _trim_context


class DailyBoardTest(unittest.TestCase):
    def test_enrich_daily_view_adds_calendar_and_courses(self) -> None:
        base = {
            "date": "2026-08-30",
            "daily_cap_hours": 4,
            "active": [{"title": "Lab 1", "course": "DATA 144", "hours": 2, "days_left": 3}],
            "upcoming": [],
        }
        with patch("studyagent.taskmaster.daily_board._fetch_calendar_events") as fetch:
            fetch.return_value = {
                "events": [],
                "deadlines": [{"title": "Lab 1", "course": "DATA 144", "due_label": "Wed Sep 03 05:00 PM"}],
                "has_calendar_access": True,
            }
            with patch("studyagent.taskmaster.daily_board._exam_events_for_calendar", return_value=[]):
                with patch("studyagent.taskmaster.daily_board.load_coverage") as coverage:
                    coverage.return_value = {
                        "courses": [
                            {
                                "course_label": "DATA 144",
                                "canonical_ready": 2,
                                "review_required": 0,
                            }
                        ]
                    }
                    view = enrich_daily_view(base)
        self.assertIn("calendar", view)
        self.assertEqual(len(view["courses"]), 1)
        self.assertEqual(view["courses"][0]["course"], "DATA 144")

    def test_trim_context_keeps_active_tasks(self) -> None:
        trimmed = _trim_context(
            {
                "date": "2026-08-30",
                "daily_cap_hours": 4,
                "active": [{"title": "Lab 1", "course": "DATA 144", "due": "Wed", "days_left": 2, "hours": 2}],
                "upcoming": [],
                "materials": [],
            }
        )
        self.assertEqual(len(trimmed["active_now"]), 1)
        self.assertEqual(trimmed["active_now"][0]["title"], "Lab 1")


if __name__ == "__main__":
    unittest.main()

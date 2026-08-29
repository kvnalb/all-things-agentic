import unittest
from datetime import UTC, date, datetime, timedelta

from pydantic import ValidationError

from studyagent.models import (
    AcademicEventCandidate,
    ConnectionState,
    ConnectorResult,
    EventKind,
    ProviderName,
)


class AcademicEventCandidateTest(unittest.TestCase):
    def candidate(self, **overrides: object) -> AcademicEventCandidate:
        values = {
            "id": "candidate-1",
            "course_id": "course-1",
            "source_id": "source-1",
            "kind": EventKind.ASSIGNMENT,
            "title": "Homework 1",
            "all_day_date": date(2026, 9, 3),
            "evidence": "Homework 1 is due September 3.",
            "confidence": 0.95,
        }
        values.update(overrides)
        return AcademicEventCandidate.model_validate(values)

    def test_high_confidence_candidate_is_auto_importable(self) -> None:
        self.assertTrue(self.candidate().eligible_for_auto_import)

    def test_submitted_or_conflicting_candidate_requires_no_auto_import(self) -> None:
        self.assertFalse(self.candidate(submitted=True).eligible_for_auto_import)
        self.assertFalse(self.candidate(has_conflict=True).eligible_for_auto_import)

    def test_candidate_requires_exactly_one_schedule_shape(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(all_day_date=None)
        with self.assertRaises(ValidationError):
            self.candidate(start_at=datetime.now(UTC))

    def test_timed_candidate_requires_increasing_end(self) -> None:
        start = datetime(2026, 9, 3, 18, tzinfo=UTC)
        candidate = self.candidate(
            all_day_date=None,
            start_at=start,
            end_at=start + timedelta(hours=1),
        )
        self.assertEqual(candidate.end_at, start + timedelta(hours=1))
        with self.assertRaises(ValidationError):
            self.candidate(all_day_date=None, start_at=start, end_at=start)


class ConnectorResultTest(unittest.TestCase):
    def test_defaults_to_no_discovered_courses(self) -> None:
        result = ConnectorResult(
            provider=ProviderName.CANVAS,
            state=ConnectionState.CONNECTED,
        )
        self.assertEqual(result.discovered_course_ids, [])


if __name__ == "__main__":
    unittest.main()

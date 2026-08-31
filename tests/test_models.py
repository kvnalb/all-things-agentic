import unittest
from datetime import UTC, date, datetime, timedelta

from pydantic import ValidationError

from studyagent.connectors.extractions import reconcile_candidates
from studyagent.extraction import EventExtractor, ExtractionBatch
from studyagent.models import (
    AcademicEventCandidate,
    CandidateStatus,
    ConnectionState,
    ConnectorResult,
    DatePrecision,
    EventKind,
    Evidence,
    ExtractionMethod,
    GradeComponent,
    ProviderName,
    Source,
    SourceKind,
    SourceRevision,
    weights_complete,
)


def sample_evidence(**overrides: object) -> Evidence:
    values = {
        "field": "all_day_date",
        "source_id": "source-1",
        "source_revision_id": "revision-1",
        "method": ExtractionMethod.PROSE,
        "confidence": 0.95,
        "excerpt": "Homework 1 is due September 3.",
    }
    values.update(overrides)
    return Evidence.model_validate(values)


class AcademicEventCandidateTest(unittest.TestCase):
    def candidate(self, **overrides: object) -> AcademicEventCandidate:
        values = {
            "id": "candidate-1",
            "course_id": "course-1",
            "source_id": "source-1",
            "source_revision_id": "revision-1",
            "kind": EventKind.ASSIGNMENT,
            "title": "Homework 1",
            "all_day_date": date(2026, 9, 3),
            "evidence": [sample_evidence()],
        }
        values.update(overrides)
        return AcademicEventCandidate.model_validate(values)

    def test_high_confidence_candidate_is_auto_importable(self) -> None:
        self.assertTrue(self.candidate().eligible_for_auto_import)

    def test_submitted_or_conflicting_candidate_requires_no_auto_import(self) -> None:
        self.assertFalse(self.candidate(submitted=True).eligible_for_auto_import)
        self.assertFalse(self.candidate(has_conflict=True).eligible_for_auto_import)
        self.assertFalse(self.candidate(review_required=True).eligible_for_auto_import)

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

    def test_confidence_is_weakest_evidence_field(self) -> None:
        candidate = self.candidate(
            evidence=[
                sample_evidence(confidence=1.0),
                sample_evidence(confidence=0.7),
            ]
        )
        self.assertEqual(candidate.confidence, 0.7)

    def test_empty_evidence_list_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(evidence=[])

    def test_unknown_precision_without_date_validates(self) -> None:
        candidate = self.candidate(
            all_day_date=None,
            date_precision=DatePrecision.UNKNOWN,
        )
        self.assertIsNone(candidate.start_at)
        self.assertIsNone(candidate.all_day_date)

    def test_unknown_precision_with_date_raises(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(date_precision=DatePrecision.UNKNOWN)

    def test_unknown_precision_is_never_auto_importable(self) -> None:
        candidate = self.candidate(
            all_day_date=None,
            date_precision=DatePrecision.UNKNOWN,
            evidence=[sample_evidence(confidence=1.0)],
            review_required=False,
        )
        self.assertFalse(candidate.eligible_for_auto_import)

    def test_projected_status_is_never_auto_importable(self) -> None:
        candidate = self.candidate(
            status=CandidateStatus.PROJECTED,
            review_required=False,
        )
        self.assertFalse(candidate.eligible_for_auto_import)

    def test_identity_key_is_stable_for_external_id(self) -> None:
        first = self.candidate(
            id="candidate-a",
            external_source="canvas",
            external_id="assignment-42",
        )
        second = self.candidate(
            id="candidate-b",
            external_source="canvas",
            external_id="assignment-42",
        )
        self.assertEqual(first.identity_key, second.identity_key)

    def test_identity_key_falls_back_to_content_key(self) -> None:
        candidate = self.candidate(title="Homework 1")
        self.assertEqual(
            candidate.identity_key,
            "course-1:assignment:homework 1",
        )


class GradeComponentTest(unittest.TestCase):
    def component(self, weight_pct: float) -> GradeComponent:
        return GradeComponent(
            id="component-1",
            course_id="course-1",
            name="Exams",
            weight_pct=weight_pct,
            evidence=[sample_evidence()],
        )

    def test_weights_complete_false_for_partial_breakdown(self) -> None:
        self.assertFalse(weights_complete([self.component(30), self.component(16)]))

    def test_weights_complete_true_at_one_hundred(self) -> None:
        self.assertTrue(weights_complete([self.component(60), self.component(40)]))


class CandidateReconcileTest(unittest.TestCase):
    def candidate(
        self,
        *,
        candidate_id: str,
        title: str,
        external_id: str | None = None,
        status: CandidateStatus = CandidateStatus.PUBLISHED,
    ) -> AcademicEventCandidate:
        return AcademicEventCandidate(
            id=candidate_id,
            course_id="course-1",
            source_id="source-1",
            source_revision_id="revision-1",
            kind=EventKind.ASSIGNMENT,
            title=title,
            all_day_date=date(2026, 9, 3),
            external_source="canvas" if external_id else None,
            external_id=external_id,
            status=status,
            evidence=[sample_evidence()],
        )

    def test_reconcile_preserves_id_for_matching_external_identity(self) -> None:
        existing = [
            self.candidate(
                candidate_id="stable-id",
                title="Homework 1",
                external_id="42",
            )
        ]
        incoming = [
            self.candidate(
                candidate_id="new-id",
                title="Homework 1 (renamed)",
                external_id="42",
            )
        ]
        reconciled, changes = reconcile_candidates(
            existing=existing,
            incoming=incoming,
            source_revision_id="revision-2",
            detected_at=datetime.now(UTC),
        )
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0].id, "stable-id")
        self.assertEqual(reconciled[0].title, "Homework 1 (renamed)")
        self.assertTrue(any(change.field == "title" for change in changes))

    def test_reconcile_marks_missing_candidates_withdrawn(self) -> None:
        existing = [
            self.candidate(candidate_id="gone", title="Dropped assignment"),
        ]
        reconciled, changes = reconcile_candidates(
            existing=existing,
            incoming=[],
            source_revision_id="revision-2",
            detected_at=datetime.now(UTC),
        )
        self.assertEqual(reconciled[0].status, CandidateStatus.WITHDRAWN)
        self.assertTrue(any(change.field == "status" for change in changes))


class EventExtractorCandidatesTest(unittest.TestCase):
    def source(self) -> Source:
        return Source(
            id="source-1",
            course_id="course-1",
            kind=SourceKind.URL,
            label="Syllabus",
            url="https://classes.example.edu/syllabus",
        )

    def revision(self) -> SourceRevision:
        return SourceRevision(
            id="revision-1",
            source_id="source-1",
            run_id="ingestion-run-1",
            content_hash="abc",
            media_type="text/plain",
            fetched_at=datetime.now(UTC),
            parser_version="source-parser-v1",
        )

    def test_candidates_round_trip_produces_prose_evidence(self) -> None:
        batch = ExtractionBatch.model_validate(
            {
                "events": [
                    {
                        "kind": "exam",
                        "title": "Midterm",
                        "all_day_date": "2026-09-24",
                        "evidence": "Midterm is September 24",
                        "confidence": 0.95,
                    }
                ]
            }
        )
        candidates = EventExtractor._candidates(
            source=self.source(),
            revision=self.revision(),
            normalized_text="Midterm is September 24",
            batch=batch,
        )
        self.assertEqual(len(candidates), 1)
        evidence = candidates[0].evidence[0]
        self.assertEqual(evidence.method, ExtractionMethod.PROSE)
        self.assertEqual(evidence.excerpt, "Midterm is September 24")
        self.assertEqual(candidates[0].date_precision, DatePrecision.DATE_ONLY)


class ConnectorResultTest(unittest.TestCase):
    def test_defaults_to_no_discovered_courses(self) -> None:
        result = ConnectorResult(
            provider=ProviderName.CANVAS,
            state=ConnectionState.CONNECTED,
        )
        self.assertEqual(result.discovered_course_ids, [])


if __name__ == "__main__":
    unittest.main()

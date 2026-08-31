import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from studyagent.taskmaster.models import AcademicClaim, ClaimProvenance, ClaimStatus, EventKind
from studyagent.taskmaster.registry import build_coverage, merge_claims, merge_group_key


class RegistryMergeTest(unittest.TestCase):
    def test_corroborated_canvas_and_syllabus_merge(self) -> None:
        due = datetime(2026, 9, 12, 23, 59, tzinfo=UTC)
        claims = [
            AcademicClaim(
                id="canvas:1",
                course_id="101",
                course_label="DATA 101",
                title="Homework 3",
                due_at=due,
                provenance=ClaimProvenance.CANVAS_ASSIGNMENT,
                source_ref="1",
            ),
            AcademicClaim(
                id="syllabus:101:hw3",
                course_id="101",
                course_label="DATA 101",
                title="Homework 3",
                due_at=due,
                provenance=ClaimProvenance.SYLLABUS_VERIFIED,
                source_ref="101:hw3",
                evidence="Homework 3 due September 12",
            ),
        ]
        canonical = merge_claims(claims)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0].status, ClaimStatus.READY)
        self.assertEqual(len(canonical[0].claim_ids), 2)
        self.assertEqual(canonical[0].merge_reason, "corroborated")

    def test_conflicting_dates_mark_conflict(self) -> None:
        claims = [
            AcademicClaim(
                id="canvas:1",
                course_id="101",
                course_label="DATA 101",
                title="Paper",
                due_at=datetime(2026, 9, 10, 23, 59, tzinfo=UTC),
                provenance=ClaimProvenance.CANVAS_ASSIGNMENT,
                source_ref="1",
            ),
            AcademicClaim(
                id="syllabus:101:paper",
                course_id="101",
                course_label="DATA 101",
                title="Paper",
                due_at=datetime(2026, 9, 15, 23, 59, tzinfo=UTC),
                provenance=ClaimProvenance.SYLLABUS_VERIFIED,
                source_ref="101:paper",
                evidence="Paper due September 15",
            ),
        ]
        canonical = merge_claims(claims)
        self.assertEqual(canonical[0].status, ClaimStatus.CONFLICTING)
        self.assertIsNone(canonical[0].chosen_claim_id)

    def test_skipped_claims_stay_in_coverage_but_not_canonical(self) -> None:
        claims = [
            AcademicClaim(
                id="canvas:9",
                course_id="101",
                course_label="DATA 101",
                title="Old quiz",
                due_at=datetime(2026, 1, 1, tzinfo=UTC),
                provenance=ClaimProvenance.CANVAS_ASSIGNMENT,
                source_ref="9",
                status=ClaimStatus.SKIPPED,
                skip_reason="past_due",
            )
        ]
        canonical = merge_claims(claims)
        self.assertEqual(canonical, [])
        coverage = build_coverage({"selected_course_ids": ["101"]}, claims, canonical, [])
        self.assertEqual(coverage["skipped_claims"], 1)

    def test_merge_group_key_normalizes_titles(self) -> None:
        self.assertEqual(
            merge_group_key("DATA 101", "HW-3!!!"),
            merge_group_key("DATA 101", "hw 3"),
        )


class RegistryApiTest(unittest.TestCase):
    def test_export_csv_header(self) -> None:
        from studyagent.taskmaster.store import export_schedule_csv

        with patch("studyagent.taskmaster.store.list_canonical", return_value=[]):
            self.assertTrue(export_schedule_csv().startswith("course,title,kind"))


if __name__ == "__main__":
    unittest.main()

"""Convert registry canonical items into schedulable donor tasks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from studyagent.taskmaster.donor.models import Task as DonorTask
from studyagent.taskmaster.models import (
    AcademicClaim,
    CanonicalScheduleItem,
    ClaimStatus,
    EventKind,
    TimedScheduleItem,
)


def _is_excluded(task: DonorTask, cfg: dict[str, Any]) -> bool:
    course = (task.course or "").lower()
    title = (task.title or "").lower()
    for excluded in cfg.get("excluded_courses", []):
        needle = excluded.lower().strip()
        if needle and (needle in course or needle in title):
            return True
    return False


def canonical_to_donor_tasks(
    canonical: list[CanonicalScheduleItem],
    claims: list[AcademicClaim],
    cfg: dict[str, Any],
) -> tuple[list[DonorTask], list[str]]:
    by_claim = {claim.id: claim for claim in claims}
    kept: list[DonorTask] = []
    skipped: list[str] = []
    for item in canonical:
        if item.status != ClaimStatus.READY or item.due_at is None:
            continue
        claim = by_claim.get(item.chosen_claim_id or "")
        task = DonorTask(
            source="canonical",
            source_ref=item.id,
            title=item.title,
            course=item.course_label,
            due_at=item.due_at,
            points_possible=claim.points_possible if claim else None,
            estimated_hours=2.0,
        )
        if _is_excluded(task, cfg):
            skipped.append(f"{item.title} ({item.course_label})")
        else:
            kept.append(task)
    return kept, skipped


def busy_intervals_from_timed_events(
    timed_events: list[TimedScheduleItem],
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for event in timed_events:
        if event.optional or not event.is_mine:
            continue
        end = event.end_at
        if end is None:
            hours = 2.0 if event.kind == EventKind.EXAM else 1.0
            end = event.start_at + timedelta(hours=hours)
        intervals.append((event.start_at, end))
    intervals.sort(key=lambda pair: pair[0])
    return intervals

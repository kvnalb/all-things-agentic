"""Multi-source academic claims registry with canonical merge (P1)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .donor.canvas_poller import (
    _get,
    _parse_due,
    course_role,
    fetch_active_courses,
    fetch_assignments,
    is_teaching_role,
)
from .donor.onboarding import load_config
from .donor.syllabus import _parse_due_hint
from .store import load_syllabus_cache
from .models import AcademicClaim, CanonicalScheduleItem, ClaimProvenance, ClaimStatus, EventKind


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def merge_group_key(course_label: str, title: str) -> str:
    return f"{(course_label or '')[:40].lower()}|{_normalize_title(title)}"


def _claim_id(provenance: ClaimProvenance, source_ref: str) -> str:
    return f"{provenance.value}:{source_ref}"


def _canonical_id(group_key: str) -> str:
    return hashlib.sha256(group_key.encode()).hexdigest()[:24]


def _kind_from_type(type_hint: str | None) -> EventKind:
    value = (type_hint or "").lower()
    if "exam" in value or "midterm" in value or "final" in value:
        return EventKind.EXAM
    if "project" in value:
        return EventKind.PROJECT
    if "quiz" in value:
        return EventKind.QUIZ
    return EventKind.ASSIGNMENT


def _provenance_rank(provenance: ClaimProvenance) -> int:
    order = {
        ClaimProvenance.CANVAS_ASSIGNMENT: 0,
        ClaimProvenance.SYLLABUS_VERIFIED: 1,
        ClaimProvenance.SYLLABUS_LLM: 2,
        ClaimProvenance.EXTRACTION: 3,
        ClaimProvenance.MANUAL: 4,
    }
    return order.get(provenance, 9)


def collect_canvas_claims(cfg: dict, *, now: datetime | None = None) -> tuple[list[AcademicClaim], list[dict]]:
    now = now or datetime.now(UTC)
    selected = {str(item) for item in cfg.get("selected_course_ids", []) if item}
    claims: list[AcademicClaim] = []
    coverage_notes: list[dict] = []

    for course in fetch_active_courses():
        course_id = str(course.get("id"))
        course_label = course.get("name") or course.get("course_code") or course_id
        if selected and course_id not in selected:
            continue
        if is_teaching_role(course):
            coverage_notes.append(
                {
                    "course_id": course_id,
                    "course_label": course_label,
                    "note": f"skipped_teaching_role:{course_role(course)}",
                }
            )
            continue

        assignment_count = 0
        for item in fetch_assignments(int(course_id)):
            assignment_count += 1
            due = _parse_due(item.get("due_at"))
            source_ref = str(item.get("id"))
            claim_id = _claim_id(ClaimProvenance.CANVAS_ASSIGNMENT, source_ref)
            if due is None:
                claims.append(
                    AcademicClaim(
                        id=claim_id,
                        course_id=course_id,
                        course_label=course_label,
                        title=item.get("name") or "Untitled assignment",
                        kind=EventKind.ASSIGNMENT,
                        due_at=None,
                        provenance=ClaimProvenance.CANVAS_ASSIGNMENT,
                        source_ref=source_ref,
                        source_url=item.get("html_url"),
                        status=ClaimStatus.SKIPPED,
                        skip_reason="no_due_date",
                    )
                )
                continue
            status = ClaimStatus.ACTIVE
            skip_reason = None
            if due < now:
                status = ClaimStatus.SKIPPED
                skip_reason = "past_due"
            claims.append(
                AcademicClaim(
                    id=claim_id,
                    course_id=course_id,
                    course_label=course_label,
                    title=item.get("name") or "Untitled assignment",
                    kind=EventKind.ASSIGNMENT,
                    due_at=due,
                    provenance=ClaimProvenance.CANVAS_ASSIGNMENT,
                    source_ref=source_ref,
                    source_url=item.get("html_url"),
                    points_possible=item.get("points_possible"),
                    status=status,
                    skip_reason=skip_reason,
                )
            )
        coverage_notes.append(
            {
                "course_id": course_id,
                "course_label": course_label,
                "canvas_assignments": assignment_count,
            }
        )
    return claims, coverage_notes


def collect_syllabus_claims(cfg: dict, *, syllabus_data: dict | None = None) -> list[AcademicClaim]:
    data = syllabus_data if syllabus_data is not None else load_syllabus_cache()
    selected = {str(item) for item in cfg.get("selected_course_ids", []) if item}
    claims: list[AcademicClaim] = []

    for course_label, analysis in (data or {}).items():
        course_id = str(analysis.get("course_id") or "")
        if selected and course_id and course_id not in selected:
            continue
        for item in analysis.get("assignments", []) or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            due_hint = item.get("due_hint", "")
            due = _parse_due_hint(due_hint)
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-") or "item"
            source_ref = f"{course_id or course_label}:{slug}"
            claim_id = _claim_id(ClaimProvenance.SYLLABUS_VERIFIED, source_ref)
            evidence = (item.get("evidence") or "").strip()
            if due is None:
                claims.append(
                    AcademicClaim(
                        id=claim_id,
                        course_id=course_id or None,
                        course_label=course_label,
                        title=title,
                        kind=_kind_from_type(item.get("type")),
                        due_at=None,
                        provenance=ClaimProvenance.SYLLABUS_VERIFIED,
                        source_ref=source_ref,
                        evidence=evidence or None,
                        status=ClaimStatus.SKIPPED,
                        skip_reason="unparseable_due_hint",
                        confidence="medium" if evidence else "low",
                    )
                )
                continue
            claims.append(
                AcademicClaim(
                    id=claim_id,
                    course_id=course_id or None,
                    course_label=course_label,
                    title=title,
                    kind=_kind_from_type(item.get("type")),
                    due_at=due,
                    provenance=ClaimProvenance.SYLLABUS_VERIFIED,
                    source_ref=source_ref,
                    evidence=evidence or None,
                    status=ClaimStatus.REVIEW_REQUIRED if not evidence else ClaimStatus.ACTIVE,
                    confidence="high" if evidence else "low",
                )
            )
    return claims


def merge_claims(claims: list[AcademicClaim]) -> list[CanonicalScheduleItem]:
    groups: dict[str, list[AcademicClaim]] = {}
    for claim in claims:
        if claim.status == ClaimStatus.SKIPPED:
            continue
        key = merge_group_key(claim.course_label, claim.title)
        groups.setdefault(key, []).append(claim)

    canonical: list[CanonicalScheduleItem] = []
    for group_key, members in groups.items():
        members = sorted(members, key=lambda item: (_provenance_rank(item.provenance), item.id))
        dated = [item for item in members if item.due_at is not None]
        claim_ids = [item.id for item in members]
        sources = sorted({item.provenance.value for item in members})

        if not dated:
            canonical.append(
                CanonicalScheduleItem(
                    id=_canonical_id(group_key),
                    group_key=group_key,
                    title=members[0].title,
                    course_id=members[0].course_id,
                    course_label=members[0].course_label,
                    kind=members[0].kind,
                    due_at=None,
                    claim_ids=claim_ids,
                    sources=sources,
                    status=ClaimStatus.REVIEW_REQUIRED,
                    merge_reason="no_parseable_due_date",
                )
            )
            continue

        due_times = {item.due_at for item in dated}
        conflict = len(due_times) > 1 and (
            max(due_times) - min(due_times) > timedelta(hours=24)
        )
        chosen = dated[0]
        if conflict:
            canonical.append(
                CanonicalScheduleItem(
                    id=_canonical_id(group_key),
                    group_key=group_key,
                    title=chosen.title,
                    course_id=chosen.course_id,
                    course_label=chosen.course_label,
                    kind=chosen.kind,
                    due_at=None,
                    claim_ids=claim_ids,
                    sources=sources,
                    status=ClaimStatus.CONFLICTING,
                    chosen_claim_id=None,
                    merge_reason="sources_disagree_on_due_date",
                    conflict_details=[
                        {
                            "claim_id": item.id,
                            "provenance": item.provenance.value,
                            "due_at": item.due_at.isoformat() if item.due_at else None,
                        }
                        for item in dated
                    ],
                )
            )
            continue

        review = any(item.status == ClaimStatus.REVIEW_REQUIRED for item in members)
        if len(members) == 1 and members[0].provenance == ClaimProvenance.SYLLABUS_VERIFIED:
            review = review or members[0].confidence in {"low", "medium"}
        status = ClaimStatus.REVIEW_REQUIRED if review else ClaimStatus.READY
        merge_reason = "corroborated" if len(members) > 1 else "single_source"
        canonical.append(
            CanonicalScheduleItem(
                id=_canonical_id(group_key),
                group_key=group_key,
                title=chosen.title,
                course_id=chosen.course_id,
                course_label=chosen.course_label,
                kind=chosen.kind,
                due_at=chosen.due_at,
                claim_ids=claim_ids,
                sources=sources,
                status=status,
                chosen_claim_id=chosen.id,
                merge_reason=merge_reason,
            )
        )
    canonical.sort(key=lambda item: (item.due_at or datetime.max.replace(tzinfo=UTC), item.title))
    return canonical


def build_coverage(
    cfg: dict,
    claims: list[AcademicClaim],
    canonical: list[CanonicalScheduleItem],
    canvas_notes: list[dict],
) -> dict[str, Any]:
    selected = [str(item) for item in cfg.get("selected_course_ids", []) if item]
    by_course: dict[str, dict[str, Any]] = {
        course_id: {
            "course_id": course_id,
            "course_label": course_id,
            "selected": True,
            "claims": 0,
            "canonical_ready": 0,
            "conflicts": 0,
            "review_required": 0,
            "skipped_claims": 0,
            "notes": [],
        }
        for course_id in selected
    }
    label_by_id = {note.get("course_id"): note.get("course_label") for note in canvas_notes if note.get("course_id")}
    for course_id, label in label_by_id.items():
        if course_id in by_course:
            by_course[course_id]["course_label"] = label

    for note in canvas_notes:
        course_id = note.get("course_id")
        if course_id and course_id in by_course and note.get("note"):
            by_course[course_id]["notes"].append(note["note"])
        if course_id and course_id in by_course and "canvas_assignments" in note:
            by_course[course_id]["canvas_assignments"] = note["canvas_assignments"]

    for claim in claims:
        course_id = claim.course_id or ""
        bucket = by_course.setdefault(
            course_id or claim.course_label,
            {
                "course_id": course_id or None,
                "course_label": claim.course_label,
                "selected": course_id in selected if course_id else False,
                "claims": 0,
                "canonical_ready": 0,
                "conflicts": 0,
                "review_required": 0,
                "skipped_claims": 0,
                "notes": [],
            },
        )
        bucket["claims"] += 1
        if claim.status == ClaimStatus.SKIPPED:
            bucket["skipped_claims"] += 1

    for item in canonical:
        course_id = item.course_id or item.course_label
        bucket = by_course.setdefault(
            course_id,
            {
                "course_id": item.course_id,
                "course_label": item.course_label,
                "selected": bool(item.course_id in selected),
                "claims": 0,
                "canonical_ready": 0,
                "conflicts": 0,
                "review_required": 0,
                "skipped_claims": 0,
                "notes": [],
            },
        )
        if item.status == ClaimStatus.READY:
            bucket["canonical_ready"] += 1
        elif item.status == ClaimStatus.CONFLICTING:
            bucket["conflicts"] += 1
        elif item.status == ClaimStatus.REVIEW_REQUIRED:
            bucket["review_required"] += 1

    courses = list(by_course.values())
    courses.sort(key=lambda row: str(row.get("course_label")))
    return {
        "selected_courses": len(selected),
        "total_claims": len(claims),
        "canonical_total": len(canonical),
        "canonical_ready": sum(1 for item in canonical if item.status == ClaimStatus.READY),
        "conflicts": sum(1 for item in canonical if item.status == ClaimStatus.CONFLICTING),
        "review_required": sum(1 for item in canonical if item.status == ClaimStatus.REVIEW_REQUIRED),
        "skipped_claims": sum(1 for claim in claims if claim.status == ClaimStatus.SKIPPED),
        "courses": courses,
    }


def build_registry(
    cfg: dict | None = None,
    *,
    run_id: str,
    syllabus_data: dict | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    canvas_claims, canvas_notes = collect_canvas_claims(cfg, now=now)
    syllabus_claims = collect_syllabus_claims(cfg, syllabus_data=syllabus_data)
    claims = canvas_claims + syllabus_claims
    canonical = merge_claims(claims)
    coverage = build_coverage(cfg, claims, canonical, canvas_notes)
    return {
        "run_id": run_id,
        "claims": claims,
        "canonical": canonical,
        "coverage": coverage,
        "summary": {
            "claims": len(claims),
            "canonical_total": len(canonical),
            "canonical_ready": coverage["canonical_ready"],
            "conflicts": coverage["conflicts"],
            "review_required": coverage["review_required"],
            "skipped_claims": coverage["skipped_claims"],
        },
    }

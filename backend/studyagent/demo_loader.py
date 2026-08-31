"""Load manually verified Fall 2026 demo data from demo/data/deadlines.db."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from studyagent.taskmaster.models import (
    AcademicClaim,
    CanonicalScheduleItem,
    ClaimProvenance,
    ClaimStatus,
    EventKind,
    TimedScheduleItem,
)

PT = ZoneInfo("America/Los_Angeles")
DEMO_SOURCE = "demo_registry_v1"

ASSIGNMENT_KINDS: dict[str, EventKind] = {
    "problem_set": EventKind.ASSIGNMENT,
    "lab": EventKind.ASSIGNMENT,
    "project": EventKind.PROJECT,
    "quiz": EventKind.QUIZ,
    "reading": EventKind.ASSIGNMENT,
    "presentation": EventKind.OTHER,
    "other": EventKind.OTHER,
}

EVENT_KINDS: dict[str, EventKind] = {
    "lecture": EventKind.LECTURE,
    "discussion": EventKind.LECTURE,
    "office_hours": EventKind.OFFICE_HOURS,
    "exam": EventKind.EXAM,
    "review": EventKind.OTHER,
    "quiz": EventKind.QUIZ,
    "holiday": EventKind.OTHER,
    "break": EventKind.OTHER,
    "term_marker": EventKind.OTHER,
}

METHOD_TO_PROVENANCE: dict[str, ClaimProvenance] = {
    "api_field": ClaimProvenance.CANVAS_ASSIGNMENT,
    "ics_field": ClaimProvenance.SYLLABUS_VERIFIED,
    "html_table": ClaimProvenance.SYLLABUS_VERIFIED,
    "pdf_prose": ClaimProvenance.SYLLABUS_VERIFIED,
    "pattern_inference": ClaimProvenance.MANUAL,
    "screenshot": ClaimProvenance.MANUAL,
}


def demo_mode_enabled() -> bool:
    return os.environ.get("STUDYAGENT_DATA_SOURCE", "").strip().lower() == "demo"


def resolve_demo_db_path() -> Path:
    explicit = os.environ.get("STUDYAGENT_DEMO_DB", "").strip()
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parents[2] / "demo" / "data" / "deadlines.db"


def _canonical_id(group_key: str) -> str:
    return hashlib.sha256(group_key.encode()).hexdigest()[:24]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=PT)
    return parsed


def _confidence_rank(value: str | None) -> int:
    order = {"exact": 0, "high": 1, "medium": 2, "low": 3}
    return order.get((value or "").strip().lower(), 9)


def _provenance_for_method(method: str | None) -> ClaimProvenance:
    return METHOD_TO_PROVENANCE.get((method or "").strip(), ClaimProvenance.MANUAL)


def _assignment_canonical_status(assignment: dict[str, Any]) -> ClaimStatus:
    if assignment.get("needs_review"):
        return ClaimStatus.REVIEW_REQUIRED
    if assignment.get("status") == "placeholder":
        return ClaimStatus.REVIEW_REQUIRED
    if assignment.get("due_precision") in {"unknown", "week_only"}:
        return ClaimStatus.REVIEW_REQUIRED
    if not assignment.get("due_at"):
        return ClaimStatus.REVIEW_REQUIRED
    if assignment.get("due_precision") == "date_only":
        return ClaimStatus.REVIEW_REQUIRED
    return ClaimStatus.READY


def _claim_status_for_assignment(assignment: dict[str, Any], *, field: str) -> ClaimStatus:
    if field != "due_at":
        return ClaimStatus.ACTIVE
    canonical = _assignment_canonical_status(assignment)
    if canonical is ClaimStatus.READY:
        return ClaimStatus.READY
    if assignment.get("due_precision") in {"unknown", "week_only"} and not assignment.get("due_at"):
        return ClaimStatus.SKIPPED
    return ClaimStatus.REVIEW_REQUIRED


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"demo database not found: {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _selected_course_ids(cfg: dict[str, Any]) -> set[str]:
    return {str(item) for item in cfg.get("selected_course_ids", []) if item}


def _course_selected(course: dict[str, Any], selected: set[str]) -> bool:
    if not selected:
        return True
    canvas_id = course.get("canvas_id")
    if canvas_id is not None and str(canvas_id) in selected:
        return True
    return str(course.get("slug")) in selected


def _load_courses(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM courses ORDER BY code").fetchall()
    return [dict(row) for row in rows]


def _load_provenance(connection: sqlite3.Connection) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    rows = connection.execute(
        "SELECT id, table_name, row_id, field, source_id, method, confidence, excerpt, note "
        "FROM provenance ORDER BY id"
    ).fetchall()
    for row in rows:
        item = dict(row)
        key = (str(item["table_name"]), int(item["row_id"]))
        grouped.setdefault(key, []).append(item)
    return grouped


def _build_assignment_claims(
    assignment: dict[str, Any],
    *,
    course: dict[str, Any],
    provenance_rows: list[dict[str, Any]],
) -> list[AcademicClaim]:
    claims: list[AcademicClaim] = []
    course_id = str(course["canvas_id"]) if course.get("canvas_id") is not None else course["slug"]
    course_label = course["code"]
    title = assignment["title"]
    due_at = _parse_iso(assignment.get("due_at"))
    kind = ASSIGNMENT_KINDS.get(assignment.get("kind") or "", EventKind.ASSIGNMENT)

    if provenance_rows:
        for row in provenance_rows:
            field = str(row["field"])
            claim_id = f"demo:provenance:{row['id']}"
            claims.append(
                AcademicClaim(
                    id=claim_id,
                    course_id=course_id,
                    course_label=course_label,
                    title=f"{title} · {field}",
                    kind=kind,
                    due_at=due_at if field == "due_at" else None,
                    provenance=_provenance_for_method(row.get("method")),
                    source_ref=f"demo-assignment:{assignment['id']}:{field}",
                    source_url=assignment.get("url"),
                    source_revision_id=DEMO_SOURCE,
                    evidence=row.get("excerpt"),
                    confidence=row.get("confidence"),
                    points_possible=assignment.get("points"),
                    status=_claim_status_for_assignment(assignment, field=field),
                    skip_reason=None
                    if _claim_status_for_assignment(assignment, field=field) is not ClaimStatus.SKIPPED
                    else "undated_or_unknown_precision",
                )
            )
        return claims

    claim_id = f"demo:assignment:{assignment['id']}"
    claims.append(
        AcademicClaim(
            id=claim_id,
            course_id=course_id,
            course_label=course_label,
            title=title,
            kind=kind,
            due_at=due_at,
            provenance=ClaimProvenance.MANUAL,
            source_ref=str(assignment["id"]),
            source_url=assignment.get("url"),
            source_revision_id=DEMO_SOURCE,
            evidence=f"Loaded from demo fixture assignment {assignment['id']}",
            confidence="medium",
            points_possible=assignment.get("points"),
            status=_claim_status_for_assignment(assignment, field="due_at"),
        )
    )
    return claims


def _build_assignment_canonical(
    assignment: dict[str, Any],
    *,
    course: dict[str, Any],
    claim_ids: list[str],
    provenance_rows: list[dict[str, Any]],
) -> CanonicalScheduleItem:
    course_id = str(course["canvas_id"]) if course.get("canvas_id") is not None else course["slug"]
    course_label = course["code"]
    title = assignment["title"]
    group_key = f"demo|{course['slug']}|assignment|{assignment['id']}"
    sources = sorted(
        {
            _provenance_for_method(row.get("method")).value
            for row in provenance_rows
        }
        or {ClaimProvenance.MANUAL.value}
    )
    due_confidences = [
        row.get("confidence")
        for row in provenance_rows
        if row.get("field") == "due_at" and row.get("confidence")
    ]
    merge_reason = "demo_fixture"
    if len(provenance_rows) > 1:
        merge_reason = "multi_source_provenance"
    if len({row.get("confidence") for row in provenance_rows if row.get("field") == "due_at"}) > 1:
        merge_reason = "mixed_confidence"
    return CanonicalScheduleItem(
        id=_canonical_id(group_key),
        group_key=group_key,
        title=title,
        course_id=course_id,
        course_label=course_label,
        kind=ASSIGNMENT_KINDS.get(assignment.get("kind") or "", EventKind.ASSIGNMENT),
        due_at=_parse_iso(assignment.get("due_at")),
        claim_ids=claim_ids,
        sources=sources,
        status=_assignment_canonical_status(assignment),
        chosen_claim_id=claim_ids[0] if claim_ids else None,
        merge_reason=merge_reason,
        conflict_details=[
            {
                "field": row.get("field"),
                "confidence": row.get("confidence"),
                "method": row.get("method"),
            }
            for row in sorted(
                provenance_rows,
                key=lambda item: _confidence_rank(str(item.get("confidence"))),
            )
        ],
    )


def _build_timed_events(
    connection: sqlite3.Connection,
    *,
    courses_by_slug: dict[str, dict[str, Any]],
    selected: set[str],
) -> list[TimedScheduleItem]:
    rows = connection.execute(
        """
        SELECT
            e.id AS event_id,
            e.start_at,
            e.end_at,
            e.course_slug,
            e.title,
            e.kind,
            e.location,
            e.optional,
            e.is_mine,
            e.status,
            e.needs_review
        FROM events e
        WHERE e.kind IN ('exam', 'quiz')
        ORDER BY e.start_at
        """
    ).fetchall()
    timed: list[TimedScheduleItem] = []
    for row in rows:
        item = dict(row)
        course = courses_by_slug.get(item.get("course_slug") or "")
        if course and not _course_selected(course, selected):
            continue
        course_label = course["code"] if course else "Campus"
        course_id = (
            str(course["canvas_id"])
            if course and course.get("canvas_id") is not None
            else (course["slug"] if course else None)
        )
        start_at = _parse_iso(item.get("start_at"))
        if start_at is None:
            continue
        end_at = _parse_iso(item.get("end_at"))
        event_id = str(item["event_id"])
        kind = EVENT_KINDS.get(item.get("kind") or "", EventKind.OTHER)
        timed.append(
            TimedScheduleItem(
                id=f"demo:event:{event_id}",
                event_id=event_id,
                occurrence_id=event_id,
                course_id=course_id,
                course_label=course_label,
                title=item["title"],
                kind=kind,
                start_at=start_at,
                end_at=end_at,
                location=item.get("location"),
                optional=bool(item.get("optional")),
                is_mine=bool(item.get("is_mine")),
                status=str(item.get("status") or "confirmed"),
                review_required=bool(item.get("needs_review")),
            )
        )
    return timed


def _build_coverage(
    *,
    cfg: dict[str, Any],
    courses: list[dict[str, Any]],
    claims: list[AcademicClaim],
    canonical: list[CanonicalScheduleItem],
    timed_events: list[TimedScheduleItem],
    grade_components_by_slug: dict[str, list[dict[str, Any]]],
    assignments_by_course: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    selected = _selected_course_ids(cfg)
    course_rows: list[dict[str, Any]] = []

    for course in courses:
        if not _course_selected(course, selected):
            continue
        slug = course["slug"]
        course_id = str(course["canvas_id"]) if course.get("canvas_id") is not None else slug
        components = grade_components_by_slug.get(slug, [])
        weights = [float(item["weight_pct"]) for item in components if item.get("weight_pct") is not None]
        assignments = assignments_by_course.get(slug, [])
        needs_review_count = sum(1 for row in assignments if row.get("needs_review"))
        immovable_events = sum(
            1 for event in timed_events if event.course_id == course_id and not event.optional
        )
        optional_events = sum(
            1 for event in timed_events if event.course_id == course_id and event.optional
        )
        grade_weights_complete = bool(weights) and abs(sum(weights) - 100.0) <= 0.01
        course_rows.append(
            {
                "course_id": course_id,
                "course_slug": slug,
                "course_label": course["code"],
                "selected": True,
                "claims": 0,
                "canonical_ready": 0,
                "conflicts": 0,
                "review_required": 0,
                "skipped_claims": 0,
                "needs_review_assignments": needs_review_count,
                "grade_weights_complete": grade_weights_complete,
                "grade_component_count": len(components),
                "timed_events": immovable_events + optional_events,
                "timed_events_optional": optional_events,
                "platform_note": course.get("platform_note"),
                "notes": [course["platform_note"]] if course.get("platform_note") else [],
            }
        )

    label_by_id = {row["course_id"]: row["course_label"] for row in course_rows}
    buckets = {row["course_id"]: row for row in course_rows}

    for claim in claims:
        course_id = claim.course_id or claim.course_label
        bucket = buckets.setdefault(
            course_id,
            {
                "course_id": claim.course_id,
                "course_label": claim.course_label,
                "selected": bool(claim.course_id in selected if claim.course_id else False),
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
        bucket = buckets.setdefault(
            course_id,
            {
                "course_id": item.course_id,
                "course_label": item.course_label,
                "selected": bool(item.course_id in selected if item.course_id else False),
                "claims": 0,
                "canonical_ready": 0,
                "conflicts": 0,
                "review_required": 0,
                "skipped_claims": 0,
                "notes": [],
            },
        )
        if item.course_label:
            label_by_id[course_id] = item.course_label
        if item.status == ClaimStatus.READY:
            bucket["canonical_ready"] += 1
        elif item.status == ClaimStatus.CONFLICTING:
            bucket["conflicts"] += 1
        elif item.status == ClaimStatus.REVIEW_REQUIRED:
            bucket["review_required"] += 1

    courses_out = list(buckets.values())
    courses_out.sort(key=lambda row: str(row.get("course_label")))
    return {
        "data_source": "demo",
        "selected_courses": len([row for row in courses_out if row.get("selected")]),
        "total_claims": len(claims),
        "canonical_total": len(canonical),
        "canonical_ready": sum(1 for item in canonical if item.status == ClaimStatus.READY),
        "conflicts": sum(1 for item in canonical if item.status == ClaimStatus.CONFLICTING),
        "review_required": sum(1 for item in canonical if item.status == ClaimStatus.REVIEW_REQUIRED),
        "skipped_claims": sum(1 for claim in claims if claim.status == ClaimStatus.SKIPPED),
        "timed_events_total": len(timed_events),
        "timed_events_immovable": sum(1 for event in timed_events if not event.optional),
        "courses": courses_out,
    }


def build_demo_registry(
    cfg: dict[str, Any] | None = None,
    *,
    run_id: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    from .taskmaster.donor.onboarding import load_config

    cfg = cfg or load_config()
    path = db_path or resolve_demo_db_path()
    selected = _selected_course_ids(cfg)

    with _connect(path) as connection:
        courses = _load_courses(connection)
        courses_by_slug = {course["slug"]: course for course in courses}
        provenance = _load_provenance(connection)

        assignment_rows = connection.execute(
            "SELECT * FROM assignments ORDER BY due_at, title"
        ).fetchall()
        assignments = [dict(row) for row in assignment_rows]

        grade_rows = connection.execute(
            "SELECT course_slug, weight_pct FROM grade_components"
        ).fetchall()
        grade_components_by_slug: dict[str, list[dict[str, Any]]] = {}
        for row in grade_rows:
            item = dict(row)
            grade_components_by_slug.setdefault(item["course_slug"], []).append(item)

        claims: list[AcademicClaim] = []
        canonical: list[CanonicalScheduleItem] = []
        assignments_by_course: dict[str, list[dict[str, Any]]] = {}

        for assignment in assignments:
            course = courses_by_slug.get(assignment["course_slug"])
            if course is None or not _course_selected(course, selected):
                continue
            assignments_by_course.setdefault(course["slug"], []).append(assignment)
            prov_rows = provenance.get(("assignments", int(assignment["id"])), [])
            assignment_claims = _build_assignment_claims(
                assignment,
                course=course,
                provenance_rows=prov_rows,
            )
            claims.extend(assignment_claims)
            canonical.append(
                _build_assignment_canonical(
                    assignment,
                    course=course,
                    claim_ids=[claim.id for claim in assignment_claims],
                    provenance_rows=prov_rows,
                )
            )

        timed_events = _build_timed_events(
            connection,
            courses_by_slug=courses_by_slug,
            selected=selected,
        )

    coverage = _build_coverage(
        cfg=cfg,
        courses=courses,
        claims=claims,
        canonical=canonical,
        timed_events=timed_events,
        grade_components_by_slug=grade_components_by_slug,
        assignments_by_course=assignments_by_course,
    )
    return {
        "run_id": run_id,
        "claims": claims,
        "canonical": canonical,
        "timed_events": timed_events,
        "coverage": coverage,
        "summary": {
            "claims": len(claims),
            "canonical_total": len(canonical),
            "canonical_ready": coverage["canonical_ready"],
            "conflicts": coverage["conflicts"],
            "review_required": coverage["review_required"],
            "skipped_claims": coverage["skipped_claims"],
            "timed_events": len(timed_events),
            "data_source": "demo",
        },
    }

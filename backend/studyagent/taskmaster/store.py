"""Firestore-backed persistence replacing donor local JSON files."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .cloud import State
from .models import AcademicClaim, CanonicalScheduleItem, RegistrySummary, TimedScheduleItem, UserConfig


def load_config_dict() -> dict[str, Any]:
    config = State().config()
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
        "calendar_writes_enabled": config.calendar_writes_enabled,
        "onboarding_complete": config.onboarding_complete,
    }


def save_config_dict(value: dict[str, Any]) -> None:
    current = State().config()
    State().save_config(
        UserConfig(
            selected_course_ids=[str(item) for item in value.get("selected_course_ids", current.selected_course_ids)],
            priority_mode=str(value.get("priority_mode", current.priority_mode)),
            lead_time_days=int(value.get("lead_time_days", current.lead_time_days)),
            reminder_style=str(value.get("reminder_style", current.reminder_style)),
            work_day_start=int(value.get("work_day_start", current.work_day_start)),
            work_day_end=int(value.get("work_day_end", current.work_day_end)),
            off_days=[str(item) for item in value.get("off_days", current.off_days)],
            priority_courses=[str(item) for item in value.get("priority_courses", current.priority_courses)],
            excluded_courses=[str(item) for item in value.get("excluded_courses", current.excluded_courses)],
            daily_cap_hours=float(value.get("daily_cap_hours", current.daily_cap_hours)),
            effort_padding=float(value.get("effort_padding", current.effort_padding)),
            calendar_writes_enabled=bool(value.get("calendar_writes_enabled", current.calendar_writes_enabled)),
            onboarding_complete=bool(value.get("onboarding_complete", current.onboarding_complete)),
        )
    )


def load_syllabus_cache() -> dict[str, Any]:
    value = State().db.collection("artifacts").document("syllabus_analysis").get().to_dict() or {}
    return value.get("data", {})


def save_syllabus_cache(data: dict[str, Any]) -> None:
    State().db.collection("artifacts").document("syllabus_analysis").set(
        {"data": data, "updated_at": datetime.now(UTC)}
    )


def save_task_list(payload: dict[str, Any]) -> None:
    State().db.collection("artifacts").document("task_list").set(
        {**payload, "updated_at": datetime.now(UTC)}
    )


def load_task_list() -> dict[str, Any]:
    return State().db.collection("artifacts").document("task_list").get().to_dict() or {"tasks": []}


def save_daily_view(view: dict[str, Any]) -> None:
    State().db.collection("artifacts").document("daily_view").set(
        {**view, "updated_at": datetime.now(UTC)}
    )


def load_daily_view() -> dict[str, Any]:
    return State().db.collection("artifacts").document("daily_view").get().to_dict() or {
        "active": [],
        "upcoming": [],
    }


def save_registry(
    *,
    run_id: str,
    claims: list[AcademicClaim],
    canonical: list[CanonicalScheduleItem],
    coverage: dict[str, Any],
    timed_events: list[TimedScheduleItem] | None = None,
) -> None:
    db = State().db
    batch = db.batch()
    for claim in claims:
        ref = db.collection("claims").document(claim.id)
        batch.set(ref, {**claim.model_dump(mode="json"), "run_id": run_id, "updated_at": datetime.now(UTC)})
    for item in canonical:
        ref = db.collection("canonical").document(item.id)
        batch.set(ref, {**item.model_dump(mode="json"), "run_id": run_id, "updated_at": datetime.now(UTC)})
    for event in timed_events or []:
        ref = db.collection("timed_events").document(event.id)
        batch.set(ref, {**event.model_dump(mode="json"), "run_id": run_id, "updated_at": datetime.now(UTC)})
    batch.commit()
    summary = RegistrySummary(
        run_id=run_id,
        claims=len(claims),
        canonical_total=len(canonical),
        canonical_ready=coverage.get("canonical_ready", 0),
        conflicts=coverage.get("conflicts", 0),
        review_required=coverage.get("review_required", 0),
        skipped_claims=coverage.get("skipped_claims", 0),
        updated_at=datetime.now(UTC),
    )
    db.collection("artifacts").document("registry").set(
        {
            **summary.model_dump(mode="json"),
            "coverage": coverage,
            "updated_at": datetime.now(UTC),
        }
    )


def load_registry_summary() -> dict[str, Any]:
    return State().db.collection("artifacts").document("registry").get().to_dict() or {}


def list_claims(*, course: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    snaps = State().db.collection("claims").limit(limit).stream()
    rows = [snap.to_dict() for snap in snaps]
    if course:
        needle = course.casefold()
        rows = [row for row in rows if needle in str(row.get("course_label", "")).casefold()]
    rows.sort(key=lambda row: (str(row.get("course_label", "")), str(row.get("title", ""))))
    return rows


def list_canonical(*, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    snaps = State().db.collection("canonical").limit(limit).stream()
    rows = [snap.to_dict() for snap in snaps]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    rows.sort(key=lambda row: (row.get("due_at") or "", str(row.get("title", ""))))
    return rows


def list_timed_events(*, course: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    snaps = State().db.collection("timed_events").limit(limit).stream()
    rows = [snap.to_dict() for snap in snaps if snap.to_dict()]
    if course:
        needle = course.casefold()
        rows = [
            row
            for row in rows
            if needle in str(row.get("course_label", "")).casefold()
            or needle in str(row.get("course_id", "")).casefold()
        ]
    rows.sort(key=lambda row: str(row.get("start_at") or ""))
    return rows


def load_coverage() -> dict[str, Any]:
    payload = load_registry_summary()
    return payload.get("coverage") or {"courses": [], "selected_courses": 0}


def list_calendar_audit(*, limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for snap in State().db.collection("calendar_bindings").limit(limit).stream():
        row = snap.to_dict() or {}
        row["binding_id"] = snap.id
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("synced_at") or row.get("attempted_at") or ""), reverse=True)
    return rows


def export_schedule_csv() -> str:
    lines = ["course,title,kind,due_at,status,sources,merge_reason,chosen_claim_id"]
    for row in list_canonical(limit=2000):
        due = row.get("due_at") or ""
        sources = "|".join(row.get("sources") or [])
        lines.append(
            ",".join(
                [
                    _csv_cell(row.get("course_label")),
                    _csv_cell(row.get("title")),
                    _csv_cell(row.get("kind")),
                    _csv_cell(due),
                    _csv_cell(row.get("status")),
                    _csv_cell(sources),
                    _csv_cell(row.get("merge_reason")),
                    _csv_cell(row.get("chosen_claim_id")),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _csv_cell(value: object) -> str:
    text = str(value or "")
    if any(char in text for char in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text

"""Firestore-backed persistence replacing donor local JSON files."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .cloud import State
from .models import UserConfig


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

"""Enrich the persisted daily view for the Taskmaster Today board."""

from __future__ import annotations

import datetime as dt
from typing import Any

from studyagent.taskmaster.cloud import Settings, State
from studyagent.taskmaster.course_colors import course_color_id
from studyagent.taskmaster.google import Google
from studyagent.taskmaster.store import (
    list_canonical,
    list_timed_events,
    load_config_dict,
    load_coverage,
    load_daily_view,
)

from googleapiclient.discovery import build


def _course_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for course in coverage.get("courses") or []:
        label = str(course.get("course_label") or course.get("course_slug") or "")
        if not label:
            continue
        ready = int(course.get("canonical_ready") or 0)
        review = int(course.get("review_required") or 0)
        rows.append(
            {
                "course": label,
                "work_type": "coursework",
                "total_assignments": ready + review,
                "upcoming": ready,
                "has_work": ready > 0,
            }
        )
    rows.sort(key=lambda row: row["course"])
    return rows


def _deadlines_from_canonical() -> list[dict[str, str]]:
    deadlines: list[dict[str, str]] = []
    for row in list_canonical(limit=500):
        if row.get("status") != "ready" or not row.get("due_at"):
            continue
        due_raw = str(row["due_at"])
        try:
            due_dt = dt.datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
            due_label = due_dt.astimezone().strftime("%a %b %d %I:%M %p")
        except ValueError:
            due_label = due_raw
        deadlines.append(
            {
                "title": str(row.get("title") or ""),
                "course": str(row.get("course_label") or ""),
                "due_label": due_label,
            }
        )
    return deadlines


def _fetch_calendar_events() -> dict[str, Any]:
    connection = State().connection()
    calendar_id = connection.get("calendar_id")
    if not calendar_id:
        return {"events": [], "deadlines": _deadlines_from_canonical(), "has_calendar_access": False}

    try:
        service = build("calendar", "v3", credentials=Google().credentials(), cache_discovery=False)
    except Exception:
        return {"events": [], "deadlines": _deadlines_from_canonical(), "has_calendar_access": False}

    now = dt.datetime.now(dt.timezone.utc)
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=(now - dt.timedelta(days=7)).isoformat(),
        timeMax=(now + dt.timedelta(days=90)).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=250,
    ).execute()

    events: list[dict[str, Any]] = []
    deadlines: list[dict[str, str]] = []
    for item in result.get("items", []):
        summary = str(item.get("summary") or "")
        start = (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date")
        end = (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date")
        if not start:
            continue
        private = ((item.get("extendedProperties") or {}).get("private") or {})
        if summary.startswith("[DUE]"):
            course = ""
            for line in str(item.get("description") or "").splitlines():
                if line.lower().startswith("course:"):
                    course = line.split(":", 1)[1].strip()
                    break
            due_label = start
            if "T" in start:
                try:
                    due_label = dt.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone().strftime(
                        "%a %b %d %I:%M %p"
                    )
                except ValueError:
                    pass
            deadlines.append({"title": summary[5:].strip(), "course": course, "due_label": due_label})
            continue
        events.append(
            {
                "title": summary,
                "start": start,
                "end": end or start,
                "description": str(item.get("description") or ""),
                "color_id": str(item.get("colorId") or private.get("color_id") or ""),
                "key": private.get("studyagent_key", ""),
            }
        )

    if not deadlines:
        deadlines = _deadlines_from_canonical()

    return {
        "generated_at": now.isoformat(),
        "calendar_name": Settings.calendar_name,
        "events": events,
        "deadlines": deadlines,
        "has_calendar_access": True,
    }


def _exam_events_for_calendar() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list_timed_events(limit=100):
        start = item.get("start_at")
        if not start:
            continue
        end = item.get("end_at") or start
        kind = str(item.get("kind") or "exam")
        label = "Exam" if kind == "exam" else "Quiz"
        rows.append(
            {
                "title": f"{label}: {item.get('title')} ({item.get('course_label')})",
                "start": start,
                "end": end,
                "description": "Academic event from registry",
                "color_id": course_color_id(str(item.get("course_label") or "")),
            }
        )
    return rows


def enrich_daily_view(view: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(view or load_daily_view())
    if not base.get("date"):
        today = dt.date.today().isoformat()
        base.setdefault("date", today)
        base.setdefault("generated_at", dt.datetime.now().astimezone().isoformat())
        base.setdefault("daily_cap_hours", load_config_dict().get("daily_cap_hours", 4))
        base.setdefault("active", [])
        base.setdefault("upcoming", [])

    calendar = _fetch_calendar_events()
    if not calendar.get("events"):
        calendar["events"] = _exam_events_for_calendar()
    else:
        existing = {(event["title"], event["start"]) for event in calendar["events"]}
        for event in _exam_events_for_calendar():
            key = (event["title"], event["start"])
            if key not in existing:
                calendar["events"].append(event)

    coverage = load_coverage()
    base["calendar"] = calendar
    base["courses"] = _course_rows(coverage)
    base.setdefault("materials", [])
    base.setdefault(
        "study_plan",
        {
            "cap_hours": base.get("daily_cap_hours", 4),
            "deadline_minutes": 0,
            "planned_minutes": 0,
            "free_minutes": int(float(base.get("daily_cap_hours", 4)) * 60),
            "picks": [],
            "not_today": [],
        },
    )
    base["manual"] = {"files": [], "course_urls": {}}
    return base

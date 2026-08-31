from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import StudyBlock, Task, TaskBriefing, UserConfig


LA = ZoneInfo("America/Los_Angeles")
MAX_BLOCK_HOURS = 3.0
COLORS = {"critical": "11", "soon": "6", "upcoming": "5", "later": "10", "priority": "3"}


def is_priority_course(task: Task, config: UserConfig) -> bool:
    course = task.course.casefold()
    return any(value.strip().casefold() in course for value in config.priority_courses if value.strip())


def is_excluded(task: Task, config: UserConfig) -> bool:
    text = f"{task.course} {task.title}".casefold()
    return any(value.strip().casefold() in text for value in config.excluded_courses if value.strip())


def score_task(task: Task, config: UserConfig, *, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    hours_left = max((task.due_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds() / 3600, 1)
    urgency = 24 / hours_left
    grade = task.points_possible / task.course_total_points if task.points_possible and task.course_total_points else 0.15
    effort = task.estimated_hours or 2
    if config.priority_mode == "grade": value = urgency * (1 + 3 * grade)
    elif config.priority_mode == "urgency": value = urgency * 2
    elif config.priority_mode == "effort": value = urgency * (1 + effort / 4)
    else: value = urgency * (1 + effort / 3) * (1 + grade)
    if is_priority_course(task, config): value *= 1.5
    return round(value, 4)


def budget_hours(task: Task, config: UserConfig) -> float:
    base = task.estimated_hours or 2
    weight = task.points_possible / task.course_total_points if task.points_possible and task.course_total_points else 0.1
    total = base * (1 + min(weight, 0.5)) * config.effort_padding
    if is_priority_course(task, config): total *= 1.1
    return round(total, 1)


def recommended_start(due: datetime, hours: float, config: UserConfig) -> datetime:
    return due - timedelta(days=max(config.lead_time_days, math.ceil(hours / config.daily_cap_hours)))


def _workable(cursor: datetime, config: UserConfig) -> datetime:
    off = {day[:3].title() for day in config.off_days}
    for _ in range(370):
        if cursor.strftime("%a") in off:
            cursor = (cursor + timedelta(days=1)).replace(hour=config.work_day_start, minute=0)
        elif cursor.hour < config.work_day_start:
            cursor = cursor.replace(hour=config.work_day_start, minute=0)
        elif cursor.hour >= config.work_day_end:
            cursor = (cursor + timedelta(days=1)).replace(hour=config.work_day_start, minute=0)
        else:
            return cursor
    return cursor


def plan_tasks(tasks: list[Task], config: UserConfig, *, now: datetime | None = None) -> tuple[list[TaskBriefing], list[StudyBlock]]:
    now = (now or datetime.now(LA)).astimezone(LA).replace(minute=0, second=0, microsecond=0)
    kept = [task for task in tasks if not task.submitted and not is_excluded(task, config)]
    for task in kept: task.priority_score = score_task(task, config, now=now)
    kept.sort(key=lambda task: (-(task.priority_score or 0), task.due_at, task.key))
    per_day: dict = defaultdict(float); briefings: list[TaskBriefing] = []; blocks: list[StudyBlock] = []
    for task in kept:
        due = task.due_at.astimezone(LA); total = budget_hours(task, config); remaining = total
        start_hint = recommended_start(due, total, config)
        cursor = _workable(max(now + timedelta(hours=1), start_hint), config); index = 0
        while remaining > 0 and cursor < due and index < 100:
            room = config.daily_cap_hours - per_day[cursor.date()]
            if room <= 0:
                cursor = _workable((cursor + timedelta(days=1)).replace(hour=config.work_day_start), config); continue
            chunk = min(remaining, MAX_BLOCK_HOURS, room, config.work_day_end - cursor.hour)
            if chunk <= 0: break
            end = cursor + timedelta(hours=chunk); days = (due - cursor).total_seconds() / 86400
            color = COLORS["priority"] if is_priority_course(task, config) else COLORS["critical" if days <= 2 else "soon" if days <= 5 else "upcoming" if days <= 14 else "later"]
            blocks.append(StudyBlock(key=f"{task.key}:block:{index}", task_key=task.key, title=f"Work: {task.title}", course=task.course, start_at=cursor, end_at=end, color_id=color, priority_score=task.priority_score or 0, source_url=task.source_url))
            per_day[cursor.date()] += chunk; remaining -= chunk; index += 1
            cursor = _workable(end, config)
        briefings.append(TaskBriefing(task_key=task.key, title=task.title, course=task.course, due_at=due, rank=task.priority_score or 0, budgeted_hours=total, blocks=index, fully_scheduled=remaining <= 0, priority_course=is_priority_course(task, config), from_syllabus=task.source == "syllabus", recommended_start=start_hint))
    return briefings, blocks


def build_daily_view(briefings: list[TaskBriefing], *, today=None) -> dict:
    today = today or datetime.now(LA).date(); active = []; upcoming = []
    scores = [item.rank for item in briefings if item.recommended_start.date() <= today]
    hi, lo = (max(scores), min(scores)) if scores else (0, 0)
    for item in briefings:
        value = {**item.model_dump(mode="json"), "days_left": (item.due_at.date() - today).days}
        if item.recommended_start.date() <= today:
            pct = 1 if hi == lo else (item.rank - lo) / (hi - lo)
            value["tier"] = "HIGH" if pct >= .66 else "MEDIUM" if pct >= .33 else "LOW"; active.append(value)
        else:
            value["opens_in_days"] = (item.recommended_start.date() - today).days; upcoming.append(value)
    active.sort(key=lambda item: item["rank"], reverse=True); upcoming.sort(key=lambda item: item["recommended_start"])
    return {"date": today.isoformat(), "active": active, "upcoming": upcoming}

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from studyagent.demo_loader import build_demo_registry, demo_mode_enabled

from .calibration import apply_calibration, load_profile, prompt_context
from .canonical_tasks import canonical_to_donor_tasks
from .cloud import State
from .donor.daily_view import build_daily_view
from .donor.models import Task as DonorTask
from .donor.onboarding import load_config
from .donor.syllabus import analyze_all_courses
from .donor.task_list import write_task_list
from .donor.taskmaster_calendar import rebuild_calendar_and_brief
from .google import CalendarWriter
from .models import ClaimStatus, Task
from .registry import build_registry
from .runner import TaskmasterRunner
from .store import save_daily_view, save_registry


ESTIMATE_CONCURRENCY = 6
ESTIMATE_TIMEOUT_SECONDS = 25


def _to_cloud_task(task: DonorTask, *, raw_estimated_hours: float | None = None) -> Task:
    return Task(
        source=task.source,
        source_ref=task.source_ref,
        title=task.title,
        course=task.course or "",
        description=task.description or "",
        due_at=task.due_at,
        points_possible=task.points_possible,
        course_total_points=task.course_total_points,
        estimated_hours=task.estimated_hours,
        raw_estimated_hours=raw_estimated_hours,
        estimate_confidence=task.estimate_confidence,
        priority_score=task.priority_score,
    )


def _apply_estimate(task: DonorTask, result: dict) -> DonorTask:
    task.estimated_hours = result.get("estimated_hours", task.estimated_hours or 2.0)
    task.estimate_confidence = result.get("estimate_confidence", task.estimate_confidence)
    task.priority_score = result.get("priority_score", task.priority_score)
    return task


def _briefing_from_canonical(registry: dict) -> list[dict]:
    briefing = []
    for item in registry["canonical"]:
        if item.status != ClaimStatus.READY or item.due_at is None:
            continue
        due_local = item.due_at.astimezone()
        briefing.append(
            {
                "task_key": item.chosen_claim_id or item.id,
                "title": item.title,
                "course": item.course_label,
                "due": f"{due_local:%a %b %d %I:%M %p}",
                "_due_dt": due_local,
                "rank": 0,
                "estimated_hours": None,
                "budgeted_hours": 2.0,
                "blocks": 0,
                "fully_scheduled": False,
                "priority_course": False,
                "from_syllabus": "syllabus" in "".join(item.sources),
            }
        )
    return briefing


class TaskmasterService:
    def __init__(self) -> None:
        self.state = State()
        self.runner = TaskmasterRunner()

    async def sync_semester(self, trigger: str = "manual") -> dict:
        run_id, run_ref = self.state.start_run(trigger)
        summary = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "deleted": 0,
            "tasks": 0,
            "estimate_failures": 0,
            "syllabus_courses": 0,
            "claims": 0,
            "canonical_ready": 0,
            "conflicts": 0,
            "review_required": 0,
            "calendar_writes": False,
            "timed_events": 0,
            "data_source": "demo" if demo_mode_enabled() else "live",
        }
        try:
            cfg = load_config()
            user_config = self.state.config()
            calendar_writes = user_config.calendar_writes_enabled
            summary["calendar_writes"] = calendar_writes

            if demo_mode_enabled():
                run_ref.set({"stage": "demo_registry_loading", "summary": summary}, merge=True)
                registry = await asyncio.to_thread(build_demo_registry, cfg, run_id=run_id)
            else:
                syllabus = await asyncio.to_thread(analyze_all_courses)
                summary["syllabus_courses"] = len(syllabus)
                run_ref.set({"stage": "syllabus_analyzed", "summary": summary}, merge=True)
                registry = await asyncio.to_thread(build_registry, cfg, run_id=run_id, syllabus_data=syllabus)

            await asyncio.to_thread(
                save_registry,
                run_id=run_id,
                claims=registry["claims"],
                canonical=registry["canonical"],
                coverage=registry["coverage"],
                timed_events=registry.get("timed_events"),
            )
            summary.update(registry["summary"])
            run_ref.set({"stage": "registry_built", "summary": summary}, merge=True)

            if not calendar_writes:
                briefing = _briefing_from_canonical(registry)
                skipped = [f"{row.title} ({row.course_label})" for row in registry["canonical"] if row.status != ClaimStatus.READY]
                await asyncio.to_thread(write_task_list, briefing, skipped, cfg)
                daily = await asyncio.to_thread(build_daily_view, briefing, cfg)
                await asyncio.to_thread(save_daily_view, daily)
                run_ref.set(
                    {
                        "state": "completed",
                        "stage": "completed",
                        "completed_at": datetime.now(UTC),
                        "summary": summary,
                        "daily": daily,
                    },
                    merge=True,
                )
                return {"run_id": run_id, **summary, "daily": daily, "registry_mode": True}

            profile = await asyncio.to_thread(load_profile)
            kept, skipped = await asyncio.to_thread(
                canonical_to_donor_tasks,
                registry["canonical"],
                registry["claims"],
                cfg,
            )
            semaphore = asyncio.Semaphore(ESTIMATE_CONCURRENCY)
            estimated = await asyncio.gather(*(self._estimate(task, cfg, profile, semaphore) for task in kept))
            summary["estimate_failures"] = sum(item[1] for item in estimated)
            tasks = [item[0] for item in estimated]
            raw_hours = {f"{item[0].source}:{item[0].source_ref}": item[2] for item in estimated}
            run_ref.set({"stage": "tasks_estimated", "summary": {**summary, "tasks": len(tasks)}}, merge=True)

            writer = CalendarWriter()
            briefing, skipped, cfg, counts = await asyncio.to_thread(
                rebuild_calendar_and_brief,
                tasks=tasks,
                calendar_writer=writer,
                run_id=run_id,
                skip_consent=True,
                canonical=registry["canonical"],
                timed_events=registry.get("timed_events") or [],
            )
            summary.update(counts)
            run_ref.set({"stage": "calendar_synced", "summary": {**summary, **counts}}, merge=True)

            await asyncio.to_thread(write_task_list, briefing, skipped, cfg)
            daily = await asyncio.to_thread(build_daily_view, briefing, cfg)
            await asyncio.to_thread(save_daily_view, daily)
            await asyncio.to_thread(
                self.state.save_tasks,
                [_to_cloud_task(task, raw_estimated_hours=raw_hours.get(f"{task.source}:{task.source_ref}")) for task in tasks],
            )

            state = "partial_success" if summary["estimate_failures"] else "completed"
            run_ref.set(
                {
                    "state": state,
                    "stage": "completed",
                    "completed_at": datetime.now(UTC),
                    "summary": {**summary, "tasks": len(tasks)},
                    "daily": daily,
                },
                merge=True,
            )
            return {"run_id": run_id, **summary, "daily": daily, "registry_mode": False}
        except Exception as exc:
            run_ref.set(
                {"state": "failed", "completed_at": datetime.now(UTC), "error_code": type(exc).__name__},
                merge=True,
            )
            raise

    async def _estimate(
        self,
        task: DonorTask,
        config: dict,
        profile,
        semaphore: asyncio.Semaphore,
    ) -> tuple[DonorTask, int, float | None]:
        failed = 0
        raw_hours: float | None = None
        async with semaphore:
            try:
                context = prompt_context(task.course or "", profile)
                async with asyncio.timeout(ESTIMATE_TIMEOUT_SECONDS):
                    result = await self.runner.process(task, config, calibration_context=context)
                task = _apply_estimate(task, result)
                raw_hours = float(task.estimated_hours or 2.0)
                task.estimated_hours = apply_calibration(raw_hours, task.course or "", profile)
            except Exception:
                raw_hours = task.estimated_hours or 2.0
                task.estimated_hours = apply_calibration(raw_hours, task.course or "", profile)
                task.estimate_confidence = task.estimate_confidence or "low"
                failed = 1
        return task, failed, raw_hours

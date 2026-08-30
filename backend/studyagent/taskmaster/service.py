from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .calibration import apply_calibration, load_profile, prompt_context
from .cloud import State
from .donor.daily_view import build_daily_view
from .donor.models import Task as DonorTask
from .donor.onboarding import load_config
from .donor.syllabus import analyze_all_courses
from .donor.task_list import write_task_list
from .donor.taskmaster_calendar import _prepare_tasks, rebuild_calendar_and_brief
from .google import CalendarWriter
from .models import Task
from .runner import TaskmasterRunner
from .store import save_daily_view


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
        }
        try:
            cfg = load_config()
            profile = await asyncio.to_thread(load_profile)
            syllabus = await asyncio.to_thread(analyze_all_courses)
            summary["syllabus_courses"] = len(syllabus)
            run_ref.set({"stage": "syllabus_analyzed", "summary": summary}, merge=True)

            kept, skipped = await asyncio.to_thread(_prepare_tasks, cfg)
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
            return {"run_id": run_id, **summary, "daily": daily}
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

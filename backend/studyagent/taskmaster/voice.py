"""Voice Q&A grounded in the student's daily board data."""

from __future__ import annotations

import json
import os
import re

from studyagent.taskmaster.cloud import Settings
from studyagent.taskmaster.store import load_config_dict, load_daily_view

SYSTEM_PROMPT = """\
You are the student's taskmaster assistant, answering out loud. You will be
given their real coursework data as JSON, then a spoken question.

RULES — these matter more than being helpful:
- Answer ONLY from the data provided. Never invent an assignment, deadline,
  reading, or course that isn't in the data.
- If the answer isn't in the data, say so plainly: "That's not in what I can
  see" — then say what you DO know that's closest.
- Never guess at grades, times you don't have, or what a professor wants.

STYLE — this is being spoken aloud, not read:
- Two or three sentences. Never lists, never markdown, never bullet points.
- Say dates like a person: "next Thursday", "the 24th", not "2026-09-24".
- Say durations naturally: "about half an hour", not "~25m est".
- Be direct and warm. No preamble like "Based on your data".
"""


def _trim_context(view: dict) -> dict:
    def slim_task(task: dict) -> dict:
        return {
            "title": task.get("title"),
            "course": (task.get("course") or "")[:40],
            "due": task.get("due"),
            "days_left": task.get("days_left"),
            "hours": task.get("hours"),
            "starts_in_days": task.get("opens_in_days"),
            "tier": task.get("tier"),
        }

    plan = view.get("study_plan") or {}
    return {
        "date": view.get("date"),
        "daily_cap_hours": view.get("daily_cap_hours"),
        "active_now": [slim_task(task) for task in view.get("active", [])],
        "not_started_yet": [slim_task(task) for task in view.get("upcoming", [])[:6]],
        "open_materials": [
            {
                "title": item.get("title"),
                "type": item.get("label"),
                "course": (item.get("course") or "")[:40],
            }
            for item in view.get("materials", [])
        ],
        "study_plan_today": {
            "free_minutes": plan.get("free_minutes"),
            "picks": [
                {
                    "title": pick.get("title"),
                    "type": pick.get("label"),
                    "est_minutes": pick.get("est_minutes"),
                }
                for pick in plan.get("picks", [])
            ],
        }
        if plan
        else None,
        "preferences": view.get("preferences"),
    }


def ask(question: str) -> dict:
    view = load_daily_view()
    cfg = load_config_dict()
    view["preferences"] = {
        "prioritizes_by": cfg.get("priority_mode"),
        "starts_days_before_deadline": cfg.get("lead_time_days"),
        "max_hours_per_day": cfg.get("daily_cap_hours"),
        "work_hours": f"{cfg.get('work_day_start')}:00-{cfg.get('work_day_end')}:00",
        "days_off": cfg.get("off_days", []),
        "priority_courses": cfg.get("priority_courses", []),
        "ignored_courses": cfg.get("excluded_courses", []),
    }
    ctx = _trim_context(view)
    has_data = bool(ctx.get("date"))

    prompt = (
        SYSTEM_PROMPT
        + "\n\nSTUDENT'S DATA:\n"
        + json.dumps(ctx, indent=2, default=str)
        + "\n\nSPOKEN QUESTION: "
        + question
        + "\n\nAnswer out loud in two or three sentences:"
    )

    model = os.environ.get("STUDYAGENT_GEMINI_MODEL", "gemini-2.5-flash")
    try:
        from google import genai

        client = genai.Client(
            vertexai=True,
            project=Settings.project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"temperature": 0.3, "max_output_tokens": 400},
        )
        text = (response.text or "").strip()
    except Exception as exc:
        return {
            "answer": f"I couldn't work that out just now. {str(exc)[:60]}",
            "used_context": has_data,
        }

    text = re.sub(r"[*#`]", "", text)
    return {"answer": text, "used_context": has_data}

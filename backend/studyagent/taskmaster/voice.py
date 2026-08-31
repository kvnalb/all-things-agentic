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
- A few short sentences. Never lists, never markdown, never bullet points.
- If several items matter, name the top ones in one flowing sentence instead of
  trailing off.
- Always finish your last sentence; never stop mid-thought.
- Say dates like a person: "next Thursday", "the 24th", not "2026-09-24".
- Say durations naturally: "about half an hour", not "~25m est".
- Be direct and warm. No preamble like "Based on your data".
"""

VOICE_MAX_OUTPUT_TOKENS = 1024
DEFAULT_VOICE_MODEL = "gemini-3.7-flash"
OMNI_VOICE_MODEL = "gemini-omni-1.1-flash-preview"


def _voice_model() -> str:
    return os.environ.get("STUDYAGENT_VOICE_MODEL", DEFAULT_VOICE_MODEL)


def _voice_fallback_model() -> str:
    return os.environ.get("STUDYAGENT_GEMINI_MODEL", DEFAULT_VOICE_MODEL)


def _is_omni_model(model: str) -> bool:
    return "omni" in model.lower()


def _is_retriable_voice_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "429" in message or "quota" in message or "resource exhausted" in message


def _response_text(response) -> str:
    text = (getattr(response, "text", None) or "").strip()
    if text:
        return text
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(part_text)
    return "".join(chunks).strip()


def _interaction_text(interaction) -> str:
    output_text = getattr(interaction, "output_text", None)
    if output_text:
        return str(output_text).strip()
    outputs = getattr(interaction, "outputs", None) or []
    for output in reversed(outputs):
        text = getattr(output, "text", None)
        if text:
            return str(text).strip()
    for step in reversed(getattr(interaction, "steps", None) or []):
        if getattr(step, "type", None) != "model_output":
            continue
        for content in getattr(step, "content", None) or []:
            text = getattr(content, "text", None)
            if text:
                return str(text).strip()
    return ""


def _generate_voice_answer(client, model: str, prompt: str) -> str:
    if _is_omni_model(model):
        interaction = client.interactions.create(
            model=model,
            input=prompt,
            response_modalities=["text"],
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": VOICE_MAX_OUTPUT_TOKENS,
                "thinking_level": "low",
            },
        )
        return _interaction_text(interaction)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "max_output_tokens": VOICE_MAX_OUTPUT_TOKENS,
            "thinking_config": {"thinking_level": "LOW"},
        },
    )
    return _response_text(response)


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
        + "\n\nAnswer out loud in a few complete sentences:"
    )

    model = _voice_model()
    try:
        from google import genai

        client = genai.Client(
            vertexai=True,
            project=Settings.project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
        try:
            text = _generate_voice_answer(client, model, prompt)
        except Exception as exc:
            fallback = _voice_fallback_model()
            if model != fallback and _is_retriable_voice_error(exc):
                text = _generate_voice_answer(client, fallback, prompt)
            else:
                raise
    except Exception as exc:
        return {
            "answer": f"I couldn't work that out just now. {str(exc)[:60]}",
            "used_context": has_data,
        }

    text = re.sub(r"[*#`]", "", text)
    return {"answer": text, "used_context": has_data}

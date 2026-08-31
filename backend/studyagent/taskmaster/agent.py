# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0.
"""ADK 2 graph ported from the co-submitter's Taskmaster agent."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime

from google.adk import Agent, Context, Event, Workflow

from .models import Task, UserConfig
from .planning import score_task
from .prompts import EFFORT_ESTIMATOR_INSTRUCTION


def parse_task_event(node_input: str, ctx: Context) -> Event:
    try:
        envelope = json.loads(node_input)
        data = envelope.get("data", envelope)
        if isinstance(data, str):
            try: data = json.loads(base64.b64decode(data))
            except Exception: data = json.loads(data)
        task = Task.model_validate(data).model_dump(mode="json")
    except Exception:
        return Event(output={"error": "invalid task payload"})
    ctx.state["parsed_task"] = task
    return Event(output=task)


effort_agent = Agent(name="effort_agent", model=os.environ.get("STUDYAGENT_GEMINI_MODEL", "gemini-3.5-flash"), mode="single_turn", instruction=EFFORT_ESTIMATOR_INSTRUCTION)


def apply_effort_estimate(node_input: object, ctx: Context) -> Event:
    hours, confidence = 2.0, "low"
    try:
        raw = node_input if isinstance(node_input, str) else json.dumps(node_input)
        value = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        candidate = float(value.get("estimated_hours", 2))
        hours = candidate if .25 <= candidate <= 20 else max(.25, min(20, candidate))
        confidence = value.get("confidence") if value.get("confidence") in {"low", "medium", "high"} else "low"
    except Exception:
        pass
    task = {**ctx.state.get("parsed_task", {}), "estimated_hours": hours, "estimate_confidence": confidence}
    ctx.state["parsed_task"] = task
    return Event(output=task)


def estimate_and_score(node_input: dict, ctx: Context) -> Event:
    if node_input.get("error"): return Event(output=node_input)
    task = Task.model_validate(node_input)
    task.priority_score = score_task(task, UserConfig.model_validate(ctx.state.get("config", {})))
    result = task.model_dump(mode="json"); ctx.state["task"] = result
    return Event(route="HIGH_PRIORITY" if task.priority_score >= .6 else "QUIET", output=result)


def schedule_quietly(node_input: dict) -> Event:
    return Event(output={"decision": "scheduled", **node_input})


def flag_high_priority(node_input: dict) -> Event:
    return Event(output={"decision": "scheduled_and_reminded", **node_input})


root_agent = Workflow(name="taskmaster", edges=[("START", parse_task_event, effort_agent, apply_effort_estimate, estimate_and_score), (estimate_and_score, {"QUIET": schedule_quietly, "HIGH_PRIORITY": flag_high_priority})])

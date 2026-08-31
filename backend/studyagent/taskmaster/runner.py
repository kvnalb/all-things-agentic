from __future__ import annotations

import json
from uuid import uuid4

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .donor.agent import root_agent
from .donor.models import Task


class TaskmasterRunner:
    def __init__(self) -> None:
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="studyagent", agent=root_agent, session_service=self.sessions)

    async def process(self, task: Task, config: dict, *, calibration_context: str = "") -> dict:
        session_id = uuid4().hex
        await self.sessions.create_session(
            app_name="studyagent",
            user_id="owner",
            session_id=session_id,
            state={"config": config},
        )
        result = None
        try:
            payload = json.loads(task.model_dump_json())
            if calibration_context:
                description = (payload.get("description") or "").strip()
                payload["description"] = f"{description}\n\n{calibration_context}".strip()
            message = types.Content(
                role="user",
                parts=[types.Part.from_text(text=json.dumps({"data": payload}))],
            )
            async for event in self.runner.run_async(user_id="owner", session_id=session_id, new_message=message):
                output = getattr(event, "output", None)
                if isinstance(output, dict) and output.get("priority_score") is not None:
                    result = output
            if result is None:
                raise RuntimeError("Taskmaster graph returned no scored task")
            return result
        finally:
            await self.sessions.delete_session(app_name="studyagent", user_id="owner", session_id=session_id)

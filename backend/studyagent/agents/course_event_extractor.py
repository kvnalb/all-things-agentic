from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from studyagent.prompts import course_event_instruction


MODEL_TIMEOUT_SECONDS = 30


class ModelRunError(RuntimeError):
    pass


class AdkGeminiModel:
    def __init__(self, *, output_schema: type, model: str | None = None) -> None:
        self.model_name = model or os.environ.get(
            "STUDYAGENT_GEMINI_MODEL", "gemini-3.7-flash"
        )
        self.agent = LlmAgent(
            name="course_event_extractor",
            description="Extract explicit scheduled academic activity from one source.",
            model=self.model_name,
            instruction=course_event_instruction(),
            tools=[],
            output_schema=output_schema,
            include_contents="none",
            generate_content_config=types.GenerateContentConfig(
                # Gemini 3+ calibrates its reasoning layers around default sampling
                # values, so bound cost with thinking_level instead of temperature.
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                ),
                max_output_tokens=8192,
            ),
        )
        self._sessions = InMemorySessionService()
        self._runner = Runner(
            app_name="studyagent",
            agent=self.agent,
            session_service=self._sessions,
        )

    async def generate(self, prompt: str) -> str:
        session_id = uuid4().hex
        user_id = "single-user"
        await self._sessions.create_session(
            app_name="studyagent",
            user_id=user_id,
            session_id=session_id,
        )
        message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        final_text: str | None = None
        try:
            try:
                async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
                    async for event in self._runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=message,
                        run_config=RunConfig(max_llm_calls=1),
                    ):
                        if event.content:
                            text_parts = [
                                part.text for part in event.content.parts if part.text
                            ]
                            if text_parts:
                                final_text = "".join(text_parts)
            except TimeoutError as exc:
                raise ModelRunError("event extraction timed out") from exc
            if final_text is None:
                raise ModelRunError(
                    "event extraction returned no structured output"
                )
            return final_text
        finally:
            await self._sessions.delete_session(
                app_name="studyagent",
                user_id=user_id,
                session_id=session_id,
            )

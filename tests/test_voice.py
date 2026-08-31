import unittest
from unittest.mock import MagicMock, patch

from studyagent.taskmaster.voice import (
    DEFAULT_VOICE_MODEL,
    _interaction_text,
    _response_text,
    ask,
)


class VoiceAskTest(unittest.TestCase):
    def test_response_text_joins_all_parts(self) -> None:
        part_a = MagicMock(text="First part. ")
        part_b = MagicMock(text="Second part.")
        content = MagicMock(parts=[part_a, part_b])
        candidate = MagicMock(content=content)
        response = MagicMock(text="", candidates=[candidate])
        self.assertEqual(_response_text(response), "First part. Second part.")

    def test_interaction_text_reads_output_text(self) -> None:
        interaction = MagicMock(output_text="Hello from Omni.", outputs=[], steps=[])
        self.assertEqual(_interaction_text(interaction), "Hello from Omni.")

    def test_ask_uses_omni_interactions_api(self) -> None:
        long_answer = "You have Lab 1 due Wednesday. " + "Keep chipping away on readings. " * 20
        interaction = MagicMock(output_text=long_answer, outputs=[], steps=[])
        view = {
            "date": "2026-08-30",
            "daily_cap_hours": 4,
            "active": [],
            "upcoming": [],
            "materials": [],
            "study_plan": None,
        }
        with patch("studyagent.taskmaster.voice.load_daily_view", return_value=view):
            with patch("studyagent.taskmaster.voice.load_config_dict", return_value={}):
                with patch("google.genai.Client") as client_cls:
                    client_cls.return_value.interactions.create.return_value = interaction
                    result = ask("What should I work on?")
        self.assertEqual(result["answer"], long_answer.strip())
        create = client_cls.return_value.interactions.create
        create.assert_called_once()
        call_kwargs = create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], DEFAULT_VOICE_MODEL)
        self.assertEqual(call_kwargs["response_modalities"], ["text"])
        self.assertEqual(call_kwargs["generation_config"]["max_output_tokens"], 1024)
        self.assertEqual(call_kwargs["generation_config"]["thinking_level"], "low")


if __name__ == "__main__":
    unittest.main()

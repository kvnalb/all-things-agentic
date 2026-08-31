import unittest
from unittest.mock import MagicMock, patch

from studyagent.taskmaster.voice import (
    DEFAULT_VOICE_MODEL,
    _interaction_text,
    _is_retriable_voice_error,
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

    def test_is_retriable_voice_error(self) -> None:
        self.assertTrue(_is_retriable_voice_error(RuntimeError("Error code: 429 - quota exceeded")))
        self.assertFalse(_is_retriable_voice_error(RuntimeError("invalid argument")))

    def test_ask_uses_generate_content_by_default(self) -> None:
        long_answer = "You have Lab 1 due Wednesday. " + "Keep chipping away on readings. " * 20
        response = MagicMock(text=long_answer)
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
                    client_cls.return_value.models.generate_content.return_value = response
                    result = ask("What should I work on?")
        self.assertEqual(result["answer"], long_answer.strip())
        generate = client_cls.return_value.models.generate_content
        generate.assert_called_once()
        self.assertEqual(generate.call_args.kwargs["model"], DEFAULT_VOICE_MODEL)

    def test_ask_falls_back_when_omni_quota_exceeded(self) -> None:
        fallback_answer = "Start with Lab 1 — it is due soon."
        response = MagicMock(text=fallback_answer)
        view = {
            "date": "2026-08-30",
            "daily_cap_hours": 4,
            "active": [],
            "upcoming": [],
            "materials": [],
            "study_plan": None,
        }
        with patch("studyagent.taskmaster.voice._voice_model", return_value="gemini-omni-1.1-flash-preview"):
            with patch("studyagent.taskmaster.voice.load_daily_view", return_value=view):
                with patch("studyagent.taskmaster.voice.load_config_dict", return_value={}):
                    with patch("google.genai.Client") as client_cls:
                        client_cls.return_value.interactions.create.side_effect = RuntimeError(
                            "Error code: 429 - quota exceeded"
                        )
                        client_cls.return_value.models.generate_content.return_value = response
                        result = ask("What should I work on?")
        self.assertEqual(result["answer"], fallback_answer)
        client_cls.return_value.interactions.create.assert_called_once()
        client_cls.return_value.models.generate_content.assert_called_once()


if __name__ == "__main__":
    unittest.main()

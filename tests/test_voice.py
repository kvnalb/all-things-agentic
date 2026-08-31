import unittest
from unittest.mock import MagicMock, patch

from studyagent.taskmaster.voice import DEFAULT_VOICE_MODEL, _response_text, ask


class VoiceAskTest(unittest.TestCase):
    def test_response_text_joins_all_parts(self) -> None:
        part_a = MagicMock(text="First part. ")
        part_b = MagicMock(text="Second part.")
        content = MagicMock(parts=[part_a, part_b])
        candidate = MagicMock(content=content)
        response = MagicMock(text="", candidates=[candidate])
        self.assertEqual(_response_text(response), "First part. Second part.")

    def test_ask_uses_gemini_37_flash(self) -> None:
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


if __name__ == "__main__":
    unittest.main()

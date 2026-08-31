import unittest
from unittest.mock import MagicMock, patch

from studyagent.taskmaster.tts import DEFAULT_CHIRP3_VOICE, chirp3_voice_name, synthesize_reply_audio


class TtsTest(unittest.TestCase):
    def test_chirp3_voice_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(chirp3_voice_name(), DEFAULT_CHIRP3_VOICE)

    def test_synthesize_reply_audio_returns_base64_mp3(self) -> None:
        audio_bytes = b"fake-mp3-bytes"
        response = MagicMock(audio_content=audio_bytes)
        with patch("studyagent.taskmaster.tts.texttospeech.TextToSpeechClient") as client_cls:
            client_cls.return_value.synthesize_speech.return_value = response
            encoded = synthesize_reply_audio("Start with Lab 1 today.")
        self.assertEqual(encoded, "ZmFrZS1tcDMtYnl0ZXM=")
        call_kwargs = client_cls.return_value.synthesize_speech.call_args.kwargs
        self.assertEqual(call_kwargs["voice"].name, DEFAULT_CHIRP3_VOICE)
        self.assertEqual(call_kwargs["voice"].language_code, "en-US")


if __name__ == "__main__":
    unittest.main()

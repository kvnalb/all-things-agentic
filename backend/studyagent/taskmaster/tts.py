"""Cloud Text-to-Speech for spoken assistant replies."""

from __future__ import annotations

import base64
import os

from google.cloud import texttospeech

DEFAULT_CHIRP3_VOICE = "en-US-Chirp3-HD-Aoede"
MAX_TTS_CHARS = 5000


def chirp3_voice_name() -> str:
    return os.environ.get("STUDYAGENT_TTS_VOICE", DEFAULT_CHIRP3_VOICE)


def synthesize_reply_audio(text: str) -> str:
    """Return base64-encoded MP3 audio for the given reply text."""
    cleaned = text.strip()[:MAX_TTS_CHARS]
    if not cleaned:
        return ""

    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=cleaned),
        voice=texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=chirp3_voice_name(),
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
        ),
    )
    if not response.audio_content:
        return ""
    return base64.b64encode(response.audio_content).decode("ascii")

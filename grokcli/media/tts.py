"""Text-to-speech via ``POST /v1/tts`` (and voice listing via ``GET /v1/tts/voices``).

Body shape verified live against api.x.ai: ``{model, text, voice, response_format}``
(the field is ``text``, not OpenAI's ``input``). The response is raw audio bytes,
or ``{audio: <base64>}`` if the server answers with JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Mapping, Optional

from .. import output
from ..client import GrokClient
from ..config import Settings
from ..errors import APIError, UsageError
from . import files


def synthesize(
    client: GrokClient,
    *,
    text: str,
    model: str,
    voice: Optional[str],
    fmt: str,
    output_dir: Path,
    language: str = "en",
) -> Path:
    """Synthesize speech for ``text`` and save it as an audio file."""
    payload: dict = {"model": model, "text": text, "response_format": fmt, "language": language}
    if voice:
        payload["voice"] = voice
    body = json.dumps(payload).encode("utf-8")
    response = client.request(
        "POST", "/tts", body=body, headers={"Content-Type": "application/json", "Accept": "audio/*"}
    )
    audio = _audio_bytes(response)
    path = files.output_path(output_dir, label=text, ext=fmt)
    return files.save_bytes(path, audio)


def _audio_bytes(response: Any) -> bytes:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        data = response.json()
        encoded = data.get("audio") or data.get("data") if isinstance(data, dict) else None
        if isinstance(encoded, str):
            return files.decode_b64(encoded)
        raise APIError("TTS JSON response did not contain audio data.")
    if not response.body:
        raise APIError("TTS returned an empty audio body.")
    return response.body


def list_voices(client: GrokClient) -> List[str]:
    """Return available voice identifiers from ``GET /v1/tts/voices``."""
    data = client.request_json("GET", "/tts/voices")
    if isinstance(data, dict):
        voices = data.get("voices") or data.get("data") or []
    elif isinstance(data, list):
        voices = data
    else:
        voices = []
    names: List[str] = []
    for voice in voices:
        if isinstance(voice, str):
            names.append(voice)
        elif isinstance(voice, dict):
            name = voice.get("id") or voice.get("name") or voice.get("voice_id")
            if name:
                names.append(str(name))
    return names


def run_tts(
    settings: Settings,
    *,
    text: str,
    voice: Optional[str] = None,
    model: Optional[str] = None,
    fmt: str = "mp3",
    language: str = "en",
    env: Optional[Mapping[str, str]] = None,
) -> int:
    if not text.strip():
        raise UsageError("Empty text.", hint='Provide text: grokcli tts "hello world"')
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Synthesizing speech...", enabled=settings.color)
    spinner.start()
    try:
        path = synthesize(
            client,
            text=text,
            model=model or settings.tts_model,
            voice=voice or settings.tts_voice,
            fmt=fmt,
            language=language,
            output_dir=settings.output_dir,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0


def run_voices(settings: Settings, *, env: Optional[Mapping[str, str]] = None) -> int:
    client = GrokClient(settings, env=env)
    voices = list_voices(client)
    output.emit_result(settings.output_format, {"voices": voices}, "\n".join(voices) or "(no voices listed)")
    return 0

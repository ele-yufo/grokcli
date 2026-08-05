"""Text-to-speech via ``POST /v1/tts`` (and voice listing via ``GET /v1/tts/voices``).

Request shape (2026-08): ``{text, voice_id, language}`` plus optional
``output_format {codec, sample_rate, bit_rate}``, ``speed`` (0.7-1.5),
``optimize_streaming_latency`` (0/1/2) and ``text_normalization``. ``voice_id``
takes built-in voices (see ``grokcli voices``) or a cloned custom-voice id. The
TTS API has no ``model`` parameter — ``-m/--model`` is accepted for
compatibility only and is not sent. Text is capped at 15,000 characters.
The response is raw audio bytes, or ``{audio: <base64>}`` if the server answers
with JSON.
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

TTS_MAX_TEXT_CHARS = 15_000
# Codecs accepted by the TTS output_format object (default: mp3).
TTS_CODECS = frozenset({"mp3", "wav", "pcm", "mulaw", "alaw"})
TTS_LATENCY_LEVELS = frozenset({0, 1, 2})


def synthesize(
    client: GrokClient,
    *,
    text: str,
    model: Optional[str] = None,  # accepted for compatibility; the TTS API has no model parameter
    voice: Optional[str],
    fmt: str,
    output_dir: Path,
    language: str = "en",
    speed: Optional[float] = None,
    optimize_streaming_latency: Optional[int] = None,
    text_normalization: bool = False,
) -> Path:
    """Synthesize speech for ``text`` and save it as an audio file."""
    if len(text) > TTS_MAX_TEXT_CHARS:
        raise UsageError(
            f"Text is {len(text)} characters; TTS accepts at most {TTS_MAX_TEXT_CHARS}.",
            hint="Split the text into shorter chunks.",
        )
    payload: dict = {"text": text, "language": language}
    if voice:
        payload["voice_id"] = voice
    if fmt != "mp3":
        if fmt not in TTS_CODECS:
            raise UsageError(f"Invalid audio format {fmt!r}.", hint=f"Choose from: {', '.join(sorted(TTS_CODECS))}")
        payload["output_format"] = {"codec": fmt}
    if speed is not None:
        if not 0.7 <= float(speed) <= 1.5:
            raise UsageError(f"Speed {speed} is out of range (0.7-1.5).", hint="Choose a multiplier within 0.7-1.5.")
        payload["speed"] = speed
    if optimize_streaming_latency is not None:
        if optimize_streaming_latency not in TTS_LATENCY_LEVELS:
            raise UsageError(
                f"Invalid latency level {optimize_streaming_latency}.",
                hint="Choose 0 (best quality), 1, or 2 (lowest latency).",
            )
        payload["optimize_streaming_latency"] = optimize_streaming_latency
    if text_normalization:
        payload["text_normalization"] = True
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
    speed: Optional[float] = None,
    latency: Optional[int] = None,
    normalize: bool = False,
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
            model=model,  # explicit -m only; the TTS API has no model parameter
            voice=voice or settings.tts_voice,
            fmt=fmt,
            language=language,
            speed=speed,
            optimize_streaming_latency=latency,
            text_normalization=normalize,
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

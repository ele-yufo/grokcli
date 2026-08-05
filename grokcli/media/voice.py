"""Custom voices (voice cloning) via the ``/v1/custom-voices`` API.

Clone a voice from a reference clip (max 120s, WAV recommended), then use the
returned ``voice_id`` anywhere a built-in voice works — ``grokcli tts --voice``
included. Note: cloning is currently US-only and gated to Enterprise plans; a
403 from the API means your tier cannot create voices (listing may still work).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .. import output
from ..client import GrokClient
from ..config import Settings
from ..errors import APIError, UsageError
from . import files

MAX_CLIP_SECONDS = 120
CUSTOM_VOICES_PATH = "/custom-voices"


def clone_voice(
    client: GrokClient,
    *,
    audio_path: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    gender: Optional[str] = None,
    accent: Optional[str] = None,
    age: Optional[str] = None,
    language: Optional[str] = None,
    tone: Optional[str] = None,
) -> Dict[str, Any]:
    """Clone a voice from a reference clip; return the voice object (has ``voice_id``)."""
    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise UsageError(f"Audio file not found: {audio_path}", hint="Pass a path to a reference clip (max 120s).")
    # Duration can't be parsed with the stdlib, so gate by size: ~120s of
    # 16-bit mono 24kHz WAV is ~6 MB — a bigger file is over the API limit.
    if path.stat().st_size > 6 * 1024 * 1024:
        raise UsageError(
            "Reference clip exceeds the ~120s limit.",
            hint="Trim the clip to under 120 seconds (or re-encode to a lower bitrate).",
        )
    if gender not in (None, "male", "female", "neutral"):
        raise UsageError(f"Invalid gender {gender!r}.", hint="Choose male, female, or neutral.")
    fields: Dict[str, Any] = {}
    for key, value in (("name", name), ("description", description), ("gender", gender),
                       ("accent", accent), ("age", age), ("language", language), ("tone", tone)):
        if value is not None:
            fields[key] = value
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body, content_type = files.encode_multipart(
        fields=fields,
        file_field="file",
        filename=path.name,
        file_bytes=path.read_bytes(),
        file_mime=mime,
    )
    response = client.request("POST", CUSTOM_VOICES_PATH, body=body, headers={"Content-Type": content_type})
    data = response.json()
    if not isinstance(data, dict) or not (data.get("voice_id") or data.get("id")):
        raise APIError("The custom-voices response did not contain a voice_id.")
    return data


def list_custom_voices(client: GrokClient) -> List[Dict[str, Any]]:
    """Return cloned voices from ``GET /v1/custom-voices``."""
    data = client.request_json("GET", CUSTOM_VOICES_PATH)
    if isinstance(data, dict):
        items = data.get("voices") or data.get("data") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [v for v in items if isinstance(v, dict)]


def delete_custom_voice(client: GrokClient, voice_id: str) -> bool:
    """Delete a cloned voice via ``DELETE /v1/custom-voices/{id}``."""
    result = client.request_json("DELETE", f"{CUSTOM_VOICES_PATH}/{voice_id}")
    return bool(result.get("deleted")) if isinstance(result, dict) else bool(result)


def run_voice_clone(
    settings: Settings,
    *,
    audio_path: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    gender: Optional[str] = None,
    accent: Optional[str] = None,
    age: Optional[str] = None,
    language: Optional[str] = None,
    tone: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Cloning voice...", enabled=settings.color)
    spinner.start()
    try:
        voice = clone_voice(
            client, audio_path=audio_path, name=name, description=description, gender=gender,
            accent=accent, age=age, language=language, tone=tone,
        )
    finally:
        spinner.stop()
    voice_id = str(voice.get("voice_id") or voice.get("id") or "")
    text = f"Cloned voice {voice_id}."
    if voice.get("name"):
        text = f"Cloned voice {voice_id} ({voice['name']})."
    output.emit_result(settings.output_format, voice, text)
    return 0


def run_voice_list(settings: Settings, *, env: Optional[Mapping[str, str]] = None) -> int:
    client = GrokClient(settings, env=env)
    voices = list_custom_voices(client)
    if settings.output_format == "json":
        output.print_json({"voices": voices})
        return 0
    if not voices:
        output.stdout("(no custom voices)")
        return 0
    style = output.Style(settings.color)
    for voice in voices:
        voice_id = str(voice.get("voice_id") or voice.get("id") or "?")
        name = voice.get("name") or ""
        line = style.cyan(voice_id) + (f"  {name}" if name else "")
        output.stdout(line)
    return 0


def run_voice_delete(settings: Settings, *, voice_id: str, env: Optional[Mapping[str, str]] = None) -> int:
    client = GrokClient(settings, env=env)
    removed = delete_custom_voice(client, voice_id)
    text = f"Deleted custom voice {voice_id}." if removed else f"Failed to delete custom voice {voice_id}."
    output.emit_result(settings.output_format, {"voice_id": voice_id, "deleted": removed}, text)
    return 0

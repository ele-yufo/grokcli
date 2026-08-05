"""Speech-to-text via ``POST /v1/stt`` (multipart upload).

Body (2026-08): a multipart/form-data form whose option fields (``vad_threshold``,
``language``, ``diarize``, ``keyterm``, ...) MUST precede the ``file`` part —
the API documents that fields sent after ``file`` may be ignored on streamable
uploads. The STT API exposes no model parameter (the old ``grok-transcribe`` id
now returns 404); a ``model`` field is only sent when one is explicitly given.
The response is JSON with ``text`` plus ``language``/``duration``/``words``/
``channels``. The multipart body is built with the standard library only (see
``files.encode_multipart``).
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


def transcribe(
    client: GrokClient,
    *,
    audio_path: str,
    model: Optional[str] = None,
    vad_threshold: Optional[float] = None,
    language: Optional[str] = None,
    diarize: bool = False,
    keyterms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file; return ``{"text": ..., "raw": ...}``."""
    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise UsageError(f"Audio file not found: {audio_path}", hint="Pass a path to an existing audio file.")
    if vad_threshold is not None and not 0.0 <= float(vad_threshold) <= 1.0:
        raise UsageError(
            f"Invalid vad_threshold {vad_threshold!r}.",
            hint="vad_threshold is a speech-probability gate in 0.0-1.0 (0 disables it).",
        )
    fields: Dict[str, Any] = {}
    if model:  # only sent when explicitly requested; the API has no model parameter
        fields["model"] = model
    if vad_threshold is not None:
        fields["vad_threshold"] = str(vad_threshold)
    if language:
        fields["language"] = language
    if diarize:
        fields["diarize"] = "true"
    if keyterms:
        fields["keyterm"] = list(keyterms)  # repeatable field; emitted as multiple parts
    audio_bytes = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body, content_type = files.encode_multipart(
        fields=fields,
        file_field="file",
        filename=path.name,
        file_bytes=audio_bytes,
        file_mime=mime,
    )
    response = client.request("POST", "/stt", body=body, headers={"Content-Type": content_type})
    data = response.json()
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise APIError("The transcription response did not contain text.")
    return {"text": text, "raw": data}


def run_transcribe(
    settings: Settings,
    *,
    audio_path: str,
    model: Optional[str] = None,
    vad_threshold: Optional[float] = None,
    language: Optional[str] = None,
    diarize: bool = False,
    keyterms: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Transcribing audio...", enabled=settings.color)
    spinner.start()
    try:
        result = transcribe(
            client,
            audio_path=audio_path,
            model=model,  # explicit -m only; the API has no model parameter
            vad_threshold=vad_threshold,
            language=language,
            diarize=diarize,
            keyterms=keyterms,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"text": result["text"]}, result["text"])
    return 0

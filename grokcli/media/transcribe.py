"""Speech-to-text via ``POST /v1/stt`` (multipart upload).

NOTE: like TTS, the exact REST STT contract is not published in the SDK. This
sends a standard ``multipart/form-data`` body with ``model`` and a ``file``
part — the conventional OpenAI-compatible transcription shape — and reads
``{text: ...}`` from the JSON response. Adjust the field names here if the live
API differs. The multipart body is built with the standard library only.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .. import output
from ..client import GrokClient
from ..config import Settings
from ..errors import APIError, UsageError


def transcribe(client: GrokClient, *, audio_path: str, model: str) -> Dict[str, Any]:
    """Transcribe an audio file; return ``{"text": ..., "raw": ...}``."""
    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise UsageError(f"Audio file not found: {audio_path}", hint="Pass a path to an existing audio file.")
    audio_bytes = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body, content_type = _encode_multipart(
        fields={"model": model},
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


def _encode_multipart(
    *,
    fields: Mapping[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    file_mime: str,
) -> Tuple[bytes, str]:
    """Build a multipart/form-data body and its Content-Type header (stdlib only)."""
    boundary = f"----grokcli{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {file_mime}".encode())
    parts.append(b"")
    body = crlf.join(parts) + crlf + file_bytes + crlf + f"--{boundary}--".encode() + crlf
    return body, f"multipart/form-data; boundary={boundary}"


def run_transcribe(
    settings: Settings,
    *,
    audio_path: str,
    model: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Transcribing audio...", enabled=settings.color)
    spinner.start()
    try:
        result = transcribe(client, audio_path=audio_path, model=model or settings.stt_model)
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"text": result["text"]}, result["text"])
    return 0

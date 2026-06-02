"""Filesystem helpers for media outputs: safe names, timestamped paths, saving.

Generated media files are not secrets, so they use normal permissions (unlike
the credential store). Writes still go through a temp file + rename for atomicity.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Optional


def safe_filename(text: str, *, max_len: int = 40) -> str:
    """Turn arbitrary prompt text into a filesystem-safe slug."""
    kept = "".join(c if (c.isalnum() or c in " -_") else "" for c in text[:max_len])
    slug = "_".join(kept.split())
    return slug or "output"


def output_path(output_dir: Path, *, label: str, ext: str, index: Optional[int] = None) -> Path:
    """Build ``<output_dir>/<timestamp>_<label>[_<index>].<ext>``."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{index}" if index is not None else ""
    name = f"{timestamp}_{safe_filename(label)}{suffix}.{ext.lstrip('.')}"
    return output_dir / name


def save_bytes(path: Path, data: bytes) -> Path:
    """Atomically write ``data`` to ``path`` (creating parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.part.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def decode_b64(value: str) -> bytes:
    """Decode a base64 (optionally data-URI) image/audio payload to bytes."""
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def image_to_data_uri(image_path: str) -> str:
    """Encode a local image as a ``data:`` URI for image-to-video input.

    Returns the input unchanged if it is already a URL or not a readable image.
    """
    path = Path(image_path).expanduser()
    if not path.is_file():
        return image_path
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        return image_path
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"

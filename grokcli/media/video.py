"""Video generation via ``POST /v1/videos/generations`` + polling.

Submit returns a ``request_id``; poll ``GET /v1/videos/{request_id}`` every few
seconds until the status is terminal, then download the result. Supports
text-to-video and image-to-video (a local image becomes a ``data:`` URI).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .. import models, output
from ..client import GrokClient
from ..config import Settings
from ..errors import APIError, ContentFilterError, RequestTimeoutError, UsageError
from . import files

POLL_INTERVAL_SECONDS = 5.0
POLL_TIMEOUT_SECONDS = 600.0
# Image-to-video requires the dedicated preview model; text-to-video uses the base.
IMAGE_TO_VIDEO_MODEL = "grok-imagine-video-1.5-preview"
_DONE = {"done", "succeeded", "success", "completed"}
_FAILED = {"failed", "error", "expired", "cancelled", "canceled"}

StatusCallback = Callable[[str, int], None]


def generate_video(
    client: GrokClient,
    *,
    prompt: str,
    model: str,
    aspect_ratio: str,
    resolution: str,
    duration: int,
    output_dir: Path,
    image: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
    poll_timeout: float = POLL_TIMEOUT_SECONDS,
) -> Path:
    """Submit a video job, poll to completion, download, and return the path."""
    if aspect_ratio not in models.ASPECT_RATIOS:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.")
    if resolution not in models.VIDEO_RESOLUTIONS:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {', '.join(sorted(models.VIDEO_RESOLUTIONS))}")
    duration = max(models.VIDEO_DURATION_MIN, min(models.VIDEO_DURATION_MAX, duration))
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    if image:
        payload["image"] = {"url": files.image_to_data_uri(image)}
    headers = {"x-idempotency-key": uuid.uuid4().hex}
    submit = client.request_json("POST", "/videos/generations", json_body=payload, headers=headers)
    request_id = _request_id(submit)
    result = _poll(client, request_id, on_status=on_status, poll_timeout=poll_timeout)
    url = _video_url(result)
    path = files.output_path(output_dir, label=prompt, ext="mp4")
    return client.download(url, path)


def _request_id(submit: Any) -> str:
    if isinstance(submit, dict):
        rid = submit.get("request_id") or submit.get("id")
        if isinstance(rid, str) and rid:
            return rid
    raise APIError("The video API did not return a request_id.")


def _poll(
    client: GrokClient,
    request_id: str,
    *,
    on_status: Optional[StatusCallback],
    poll_timeout: float,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline:
        result = client.request_json("GET", f"/videos/{request_id}")
        status = str(result.get("status") or "").lower() if isinstance(result, dict) else ""
        if status in _DONE or (isinstance(result, dict) and result.get("video")):
            return result
        if status in _FAILED:
            raise _failure_error(result, status)
        if on_status:
            on_status(status or "pending", int(poll_timeout - (deadline - time.monotonic())))
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RequestTimeoutError(f"Video generation timed out after {int(poll_timeout)}s.", code="video_timeout")


def _failure_error(result: Mapping[str, Any], status: str):
    error = result.get("error") if isinstance(result, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    detail = message or f"status: {status}"
    if "policy" in detail.lower() or "moderation" in detail.lower():
        return ContentFilterError(f"Video generation blocked: {detail}", code="content_filter")
    return APIError(f"Video generation failed: {detail}")


def _video_url(result: Mapping[str, Any]) -> str:
    video = result.get("video") if isinstance(result, dict) else None
    if isinstance(video, dict) and isinstance(video.get("url"), str):
        return video["url"]
    if isinstance(result, dict) and isinstance(result.get("url"), str):
        return result["url"]
    raise APIError("The completed video response had no downloadable URL.")


def run_video(
    settings: Settings,
    *,
    prompt: str,
    model: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 8,
    image: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: generate a video (with progress) and report the saved path."""
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint='Provide a description: grokcli video "a wave crashing"')
    resolved_model = model or (IMAGE_TO_VIDEO_MODEL if image else settings.video_model)
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Submitting video job...", enabled=settings.color)
    spinner.start()

    def _status(status: str, elapsed: int) -> None:
        spinner.update(f"Rendering video... [{status}] {elapsed}s")

    try:
        path = generate_video(
            client,
            prompt=prompt,
            model=resolved_model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            image=image,
            output_dir=settings.output_dir,
            on_status=_status,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0

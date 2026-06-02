"""Video generation via ``POST /v1/videos/generations`` + polling.

Submit returns a ``request_id``; poll ``GET /v1/videos/{request_id}`` every few
seconds until the status is terminal, then download the result. Supports
text-to-video and image-to-video (a local image becomes a ``data:`` URI).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

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
    reference_images: Optional[List[str]] = None,
    on_status: Optional[StatusCallback] = None,
    poll_timeout: float = POLL_TIMEOUT_SECONDS,
) -> Path:
    """Submit a video job, poll to completion, download, and return the path.

    ``image`` = first frame (image-to-video). ``reference_images`` = style/subject
    references (reference-to-video, R2V); up to 7. Both encode local files as data URIs.
    """
    if aspect_ratio not in models.ASPECT_RATIOS:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.")
    if resolution not in models.VIDEO_RESOLUTIONS:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {', '.join(sorted(models.VIDEO_RESOLUTIONS))}")
    if reference_images and len(reference_images) > 7:
        raise UsageError("At most 7 reference images are allowed for reference-to-video.")
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
    if reference_images:
        payload["reference_images"] = [{"image_url": files.image_to_data_uri(p)} for p in reference_images]
    headers = {"x-idempotency-key": uuid.uuid4().hex}
    submit = client.request_json("POST", "/videos/generations", json_body=payload, headers=headers)
    request_id = _request_id(submit)
    result = _poll(client, request_id, on_status=on_status, poll_timeout=poll_timeout)
    url = _video_url(result)
    path = files.output_path(output_dir, label=prompt, ext="mp4")
    return client.download(url, path)


def extend_video(
    client: GrokClient,
    *,
    video: str,
    model: str,
    duration: int,
    output_dir: Path,
    prompt: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
    poll_timeout: float = POLL_TIMEOUT_SECONDS,
) -> Path:
    """Extend an existing video via ``POST /videos/extensions`` (submit + poll + download).

    ``video`` may be an http(s) URL or a local file (encoded as a data URI).
    """
    duration = max(models.VIDEO_DURATION_MIN, min(models.VIDEO_DURATION_MAX, duration))
    payload: dict = {"model": model, "video": {"url": _video_to_url(video)}, "duration": duration}
    if prompt:
        payload["prompt"] = prompt
    headers = {"x-idempotency-key": uuid.uuid4().hex}
    submit = client.request_json("POST", "/videos/extensions", json_body=payload, headers=headers)
    request_id = _request_id(submit)
    result = _poll(client, request_id, on_status=on_status, poll_timeout=poll_timeout)
    url = _video_url(result)
    path = files.output_path(output_dir, label="extended", ext="mp4")
    return client.download(url, path)


def _video_to_url(video: str) -> str:
    """Return an http(s) URL unchanged; encode a local video file as a data URI."""
    import base64
    import mimetypes

    if video.startswith(("http://", "https://", "data:")):
        return video
    path = Path(video).expanduser()
    if not path.is_file():
        raise UsageError(f"Video not found: {video}", hint="Pass a local video file or an http(s) URL.")
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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
    reference_images: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: generate a video (with progress) and report the saved path.

    With ``image`` (image-to-video) or ``reference_images`` (reference-to-video),
    the 1.5-preview model is selected automatically unless ``model`` overrides it.
    """
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint='Provide a description: grokcli video "a wave crashing"')
    # Image-to-video uses the 1.5-preview model; text-to-video and reference-to-video
    # (reference_images) both use the base model (the preview model rejects reference_images).
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
            reference_images=reference_images,
            output_dir=settings.output_dir,
            on_status=_status,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0


def run_video_extend(
    settings: Settings,
    *,
    video: str,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    duration: int = 6,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: extend an existing video and report the saved path."""
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Submitting video extension...", enabled=settings.color)
    spinner.start()

    def _status(status: str, elapsed: int) -> None:
        spinner.update(f"Extending video... [{status}] {elapsed}s")

    try:
        path = extend_video(
            client,
            video=video,
            prompt=prompt,
            model=model or settings.video_model,
            duration=duration,
            output_dir=settings.output_dir,
            on_status=_status,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0

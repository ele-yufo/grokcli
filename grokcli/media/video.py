"""Video generation via ``POST /v1/videos/generations`` + polling.

Submit returns a ``request_id``; poll ``GET /v1/videos/{request_id}`` every few
seconds until the status is terminal, then download the result. Supports
text-to-video, image-to-video (a local image becomes a ``data:`` URI),
reference-to-video (style/subject references, optionally with preset-voice
narration), video extension, and video editing.
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
# /videos/edits and /videos/extensions are served by the base model: live check
# 2026-08 — grok-imagine-video-1.5 returns HTTP 400 "Video editing is not
# supported for this model", while grok-imagine-video accepts both.
EDIT_VIDEO_MODEL = "grok-imagine-video"
# grok-imagine-video-1.5 is the unified model: T2V + I2V + R2V (see models.py).
# Max reference images is undocumented but enforced live by the API (HTTP 400
# "Too many reference images: 8. Maximum allowed is 7.", verified 2026-08).
MAX_REFERENCE_IMAGES = 7
_DONE = {"done", "succeeded", "success", "completed"}
_FAILED = {"failed", "error", "expired", "cancelled", "canceled"}

StatusCallback = Callable[[str, int, Optional[int]], None]


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
    reference_audios: Optional[List[str]] = None,
    on_status: Optional[StatusCallback] = None,
    poll_timeout: float = POLL_TIMEOUT_SECONDS,
) -> Path:
    """Submit a video job, poll to completion, download, and return the path.

    ``image`` = first frame (image-to-video). ``reference_images`` = style/subject
    references (reference-to-video, R2V). ``reference_audios`` = preset-voice ids
    for R2V narration (max 3), tagged in the prompt as ``<AUDIO_0>`` etc. Local
    image files are encoded as data URIs. Image-to-video and reference-to-video
    are mutually exclusive modes (the API rejects both together).
    """
    spec = models.video_spec(model)
    if aspect_ratio not in spec.aspect_ratios:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.", hint=f"Choose from: {', '.join(sorted(spec.aspect_ratios))}")
    if resolution not in spec.resolutions:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {', '.join(sorted(spec.resolutions))}")
    # Validate explicitly rather than silently clamping — never mutate the user's intent.
    if not (spec.min_duration <= duration <= spec.max_duration):
        raise UsageError(
            f"Duration {duration}s is out of range for {model} ({spec.min_duration}-{spec.max_duration}s).",
            hint="Choose a duration within the model's supported range.",
        )
    if image and not spec.supports_image:
        raise UsageError(
            f"{model} does not support image-to-video.",
            hint="Use grok-imagine-video-1.5 for -i (or omit -i for text-to-video).",
        )
    if (reference_images or reference_audios) and not spec.supports_reference:
        raise UsageError(
            f"{model} does not support reference-to-video (R2V).",
            hint="Use grok-imagine-video or grok-imagine-video-1.5 for --ref / --ref-audio.",
        )
    if image and (reference_images or reference_audios):
        raise UsageError(
            "Image-to-video (-i) and reference-to-video (--ref / --ref-audio) are mutually exclusive.",
            hint="Pick one mode: -i IMAGE, or --ref IMG (with optional --ref-audio VOICE).",
        )
    if reference_images and len(reference_images) > MAX_REFERENCE_IMAGES:
        raise UsageError(
            f"At most {MAX_REFERENCE_IMAGES} reference images are allowed for reference-to-video.",
            hint=f"Pick the strongest {MAX_REFERENCE_IMAGES} references or split into multiple videos.",
        )
    if reference_audios:
        if spec.max_reference_audios <= 0:
            raise UsageError(
                f"{model} does not support preset-voice narration (reference_audios).",
                hint="Use grok-imagine-video-1.5 for --ref-audio.",
            )
        if len(reference_audios) > spec.max_reference_audios:
            raise UsageError(
                f"At most {spec.max_reference_audios} preset voices are allowed for reference-to-video narration.",
                hint=f"Tag each voice in the prompt as <AUDIO_0>..<AUDIO_{spec.max_reference_audios - 1}>.",
            )
    if reference_images and spec.r2v_max_resolution and models.resolution_rank(resolution) > models.resolution_rank(spec.r2v_max_resolution):
        raise UsageError(
            f"Reference-to-video is capped at {spec.r2v_max_resolution} on {model} (got {resolution}).",
            hint=f"Choose {spec.r2v_max_resolution} or lower for --ref (T2V/I2V support 1080p).",
        )
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
        payload["reference_images"] = [{"url": files.image_to_data_uri(p)} for p in reference_images]
    if reference_audios:
        payload["reference_audios"] = [{"voice_id": v} for v in reference_audios]
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
    Extension segments are 2-10s (the API range for this endpoint).
    """
    spec = models.video_spec(model)
    if not (spec.min_extend_duration <= duration <= spec.max_extend_duration):
        raise UsageError(
            f"Extension duration {duration}s is out of range for {model} ({spec.min_extend_duration}-{spec.max_extend_duration}s).",
            hint="Choose an extension duration within the API's supported range.",
        )
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


def edit_video(
    client: GrokClient,
    *,
    video: str,
    model: str,
    prompt: str,
    output_dir: Path,
    on_status: Optional[StatusCallback] = None,
    poll_timeout: float = POLL_TIMEOUT_SECONDS,
) -> Path:
    """Edit an existing video via ``POST /videos/edits`` (submit + poll + download).

    The output keeps the input's length (no duration/aspect_ratio parameters on
    this endpoint) and is capped at 720p.
    """
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint="Describe the edit, e.g. grokcli video-edit clip.mp4 \"add a neon glow\"")
    payload: dict = {"model": model, "prompt": prompt, "video": {"url": _video_to_url(video)}}
    headers = {"x-idempotency-key": uuid.uuid4().hex}
    submit = client.request_json("POST", "/videos/edits", json_body=payload, headers=headers)
    request_id = _request_id(submit)
    result = _poll(client, request_id, on_status=on_status, poll_timeout=poll_timeout)
    url = _video_url(result)
    path = files.output_path(output_dir, label="edited", ext="mp4")
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
            progress = result.get("progress") if isinstance(result, dict) else None
            if isinstance(progress, int) and not isinstance(progress, bool):
                on_status(f"{status or 'pending'} {progress}%", int(poll_timeout - (deadline - time.monotonic())), progress)
            else:
                on_status(status or "pending", int(poll_timeout - (deadline - time.monotonic())), None)
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
    if isinstance(video, dict):
        # respect_moderation=false means the output was withheld: url is empty.
        if video.get("respect_moderation") is False:
            raise ContentFilterError(
                "The video was withheld by moderation (respect_moderation=false).", code="content_filter"
            )
        if isinstance(video.get("url"), str):
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
    reference_audios: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: generate a video (with progress) and report the saved path.

    The default model (grok-imagine-video-1.5) handles all three modes;
    ``model`` overrides it and per-model capabilities are validated.
    """
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint='Provide a description: grokcli video "a wave crashing"')
    resolved_model = model or settings.video_model
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Submitting video job...", enabled=settings.color)
    spinner.start()

    def _status(status: str, elapsed: int, progress: Optional[int]) -> None:
        detail = f" {progress}%" if progress is not None else ""
        spinner.update(f"Rendering video... [{status}]{detail} {elapsed}s")

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
            reference_audios=reference_audios,
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

    def _status(status: str, elapsed: int, progress: Optional[int]) -> None:
        detail = f" {progress}%" if progress is not None else ""
        spinner.update(f"Extending video... [{status}]{detail} {elapsed}s")

    try:
        path = extend_video(
            client,
            video=video,
            prompt=prompt,
            model=model or EDIT_VIDEO_MODEL,
            duration=duration,
            output_dir=settings.output_dir,
            on_status=_status,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0


def run_video_edit(
    settings: Settings,
    *,
    video: str,
    prompt: str,
    model: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: edit an existing video and report the saved path."""
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Submitting video edit...", enabled=settings.color)
    spinner.start()

    def _status(status: str, elapsed: int, progress: Optional[int]) -> None:
        detail = f" {progress}%" if progress is not None else ""
        spinner.update(f"Editing video... [{status}]{detail} {elapsed}s")

    try:
        path = edit_video(
            client,
            video=video,
            prompt=prompt,
            model=model or EDIT_VIDEO_MODEL,
            output_dir=settings.output_dir,
            on_status=_status,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"path": str(path)}, str(path))
    return 0

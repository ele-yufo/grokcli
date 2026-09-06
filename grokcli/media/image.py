"""Image generation via ``POST /v1/images/generations`` and edits via
``POST /v1/images/edits``.

Request: ``{model, prompt, n, aspect_ratio, resolution, quality?,
response_format?}``.
The response carries ``data[]`` items with either ``b64_json``/``base64`` or a
(short-lived) ``url``; both are handled and saved locally. The saved extension
follows the item's ``mime_type`` (Imagine Image 2.0 returns JPEG, older tiers
PNG).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Mapping, Optional

from .. import models, output
from ..client import GrokClient
from ..config import Settings
from ..errors import APIError, UsageError
from . import files


def generate_images(
    client: GrokClient,
    *,
    prompt: str,
    model: str,
    aspect_ratio: str,
    resolution: str,
    n: int,
    output_dir: Path,
    quality: Optional[str] = None,
    response_format: Optional[str] = None,
) -> List[Path]:
    """Generate ``n`` images and save them; return the saved paths."""
    if aspect_ratio not in models.IMAGE_ASPECT_RATIOS:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.", hint=f"Choose from: {_sorted(models.IMAGE_ASPECT_RATIOS)}")
    if resolution not in models.IMAGE_RESOLUTIONS:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {_sorted(models.IMAGE_RESOLUTIONS)}")
    _check_count(n)
    payload = {"model": model, "prompt": prompt, "n": max(1, n), "aspect_ratio": aspect_ratio, "resolution": resolution}
    if quality:
        _check_quality(quality)
        payload["quality"] = quality
    if response_format:
        _check_response_format(response_format)
        payload["response_format"] = response_format
    data = client.request_json("POST", "/images/generations", json_body=payload)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise APIError("The image API returned no image data.")
    multiple = len(items) > 1
    paths: List[Path] = []
    for index, item in enumerate(items):
        path = files.output_path(output_dir, label=prompt, ext=_ext_for(item), index=index if multiple else None)
        paths.append(_save_item(client, item, path))
    return paths


def edit_image(
    client: GrokClient,
    *,
    prompt: str,
    sources: List[str],
    model: str,
    aspect_ratio: Optional[str],
    resolution: Optional[str],
    n: int,
    output_dir: Path,
    quality: Optional[str] = None,
    response_format: Optional[str] = None,
) -> List[Path]:
    """Edit up to 5 reference images guided by ``prompt`` via ``POST /images/edits``.

    Local source paths are encoded as data URIs; http(s) URLs pass through.
    aspect_ratio/resolution are optional — omitted, the result follows the input.
    Refer to sources in the prompt as ``<IMAGE_0>``, ``<IMAGE_1>``, ... for
    multi-reference edits.
    """
    if not sources:
        raise UsageError("image-edit needs at least one source image.", hint="Pass one with -i: grokcli image-edit \"...\" -i photo.png")
    limit = models.image_edit_max_sources(model)
    if len(sources) > limit:
        raise UsageError(f"image-edit accepts at most {limit} source images.")
    if aspect_ratio and aspect_ratio not in models.IMAGE_ASPECT_RATIOS:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.", hint=f"Choose from: {_sorted(models.IMAGE_ASPECT_RATIOS)}")
    if resolution and resolution not in models.IMAGE_RESOLUTIONS:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {_sorted(models.IMAGE_RESOLUTIONS)}")
    _check_count(n)
    # Canonical input field is ``url`` (docs 2026-08; ``image_url`` is kept as
    # an accepted alias server-side).
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "images": [{"url": files.image_to_data_uri(s)} for s in sources],
        "n": max(1, n),
    }
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if resolution:
        payload["resolution"] = resolution
    if quality:
        _check_quality(quality)
        payload["quality"] = quality
    if response_format:
        _check_response_format(response_format)
        payload["response_format"] = response_format
    data = client.request_json("POST", "/images/edits", json_body=payload)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise APIError("The image-edit API returned no image data.")
    multiple = len(items) > 1
    paths: List[Path] = []
    for index, item in enumerate(items):
        path = files.output_path(output_dir, label=f"edit {prompt}", ext=_ext_for(item), index=index if multiple else None)
        paths.append(_save_item(client, item, path))
    return paths


def _save_item(client: GrokClient, item: Mapping, path: Path) -> Path:
    b64 = item.get("b64_json") or item.get("b64") or item.get("base64")
    url = item.get("url")
    if isinstance(b64, str) and b64:
        return files.save_bytes(path, files.decode_b64(b64))
    if isinstance(url, str) and url:
        return client.download(url, path)
    raise APIError("Image item had neither base64 data nor a URL.")


# Imagine Image 2.0 returns JPEG by default (with ``mime_type`` saying so);
# older tiers return PNG. Trust the field, fall back to .png.
_ITEM_EXTS = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}


def _ext_for(item: Mapping) -> str:
    mime = item.get("mime_type")
    return _ITEM_EXTS.get(mime, "png") if isinstance(mime, str) else "png"


def _sorted(values) -> str:
    return ", ".join(sorted(values))


def _check_count(n: int) -> None:
    if n > models.IMAGE_COUNT_MAX:
        raise UsageError(f"The image API accepts at most {models.IMAGE_COUNT_MAX} images per request.", hint=f"You asked for {n}.")


def _check_quality(quality: str) -> None:
    if quality not in models.IMAGE_QUALITIES:
        raise UsageError(f"Invalid quality {quality!r}.", hint=f"Choose from: {_sorted(models.IMAGE_QUALITIES)}")


def _check_response_format(response_format: str) -> None:
    if response_format not in models.RESPONSE_FORMATS:
        raise UsageError(f"Invalid response format {response_format!r}.", hint=f"Choose from: {_sorted(models.RESPONSE_FORMATS)}")


def run_image(
    settings: Settings,
    *,
    prompt: str,
    model: Optional[str] = None,
    aspect_ratio: str = "1:1",
    resolution: str = "2k",
    n: int = 1,
    quality: Optional[str] = None,
    response_format: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: generate image(s), report saved paths."""
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint='Provide a description: grokcli image "a red fox"')
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Generating image...", enabled=settings.color)
    spinner.start()
    try:
        paths = generate_images(
            client,
            prompt=prompt,
            model=model or settings.image_model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            n=n,
            output_dir=settings.output_dir,
            quality=quality,
            response_format=response_format,
        )
    finally:
        spinner.stop()
    output.emit_result(
        settings.output_format,
        {"paths": [str(p) for p in paths]},
        "\n".join(str(p) for p in paths),
    )
    return 0


# Imagine Image 2.0 by default for edits (same as generation): the docs
# recommend it and it is cheaper than the old quality tier. Fall back with
# -m grok-imagine-image-quality or -m grok-imagine-image.
DEFAULT_EDIT_MODEL = "grok-imagine-image-2.0"


def run_image_edit(
    settings: Settings,
    *,
    prompt: str,
    sources: List[str],
    model: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    n: int = 1,
    quality: Optional[str] = None,
    response_format: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """CLI entry: edit reference image(s) with a prompt; report saved paths."""
    if not prompt.strip():
        raise UsageError("Empty prompt.", hint='Describe the edit: grokcli image-edit "make it night" -i photo.png')
    client = GrokClient(settings, env=env)
    spinner = output.Spinner("Editing image...", enabled=settings.color)
    spinner.start()
    try:
        paths = edit_image(
            client,
            prompt=prompt,
            sources=sources,
            model=model or DEFAULT_EDIT_MODEL,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            n=n,
            output_dir=settings.output_dir,
            quality=quality,
            response_format=response_format,
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"paths": [str(p) for p in paths]}, "\n".join(str(p) for p in paths))
    return 0

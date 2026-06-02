"""Image generation via ``POST /v1/images/generations``.

Request: ``{model, prompt, n, aspect_ratio, resolution}``. The response carries
``data[]`` items with either ``b64_json``/``base64`` or a (short-lived) ``url``;
both are handled and saved locally.
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
) -> List[Path]:
    """Generate ``n`` images and save them; return the saved paths."""
    if aspect_ratio not in models.ASPECT_RATIOS:
        raise UsageError(f"Invalid aspect ratio {aspect_ratio!r}.", hint=f"Choose from: {_sorted(models.ASPECT_RATIOS)}")
    if resolution not in models.IMAGE_RESOLUTIONS:
        raise UsageError(f"Invalid resolution {resolution!r}.", hint=f"Choose from: {_sorted(models.IMAGE_RESOLUTIONS)}")
    payload = {"model": model, "prompt": prompt, "n": max(1, n), "aspect_ratio": aspect_ratio, "resolution": resolution}
    data = client.request_json("POST", "/images/generations", json_body=payload)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise APIError("The image API returned no image data.")
    multiple = len(items) > 1
    paths: List[Path] = []
    for index, item in enumerate(items):
        path = files.output_path(output_dir, label=prompt, ext="png", index=index if multiple else None)
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
) -> List[Path]:
    """Edit 1-3 reference images guided by ``prompt`` via ``POST /images/edits``.

    Local source paths are encoded as data URIs; http(s) URLs pass through.
    aspect_ratio/resolution are optional — omitted, the result follows the input.
    """
    if not sources:
        raise UsageError("image-edit needs at least one source image.", hint="Pass one with -i: grokcli image-edit \"...\" -i photo.png")
    if len(sources) > 3:
        raise UsageError("image-edit accepts at most 3 source images.")
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "images": [{"image_url": files.image_to_data_uri(s)} for s in sources],
        "n": max(1, n),
    }
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if resolution:
        payload["resolution"] = resolution
    data = client.request_json("POST", "/images/edits", json_body=payload)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise APIError("The image-edit API returned no image data.")
    multiple = len(items) > 1
    paths: List[Path] = []
    for index, item in enumerate(items):
        path = files.output_path(output_dir, label=f"edit {prompt}", ext="png", index=index if multiple else None)
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


def _sorted(values) -> str:
    return ", ".join(sorted(values))


def run_image(
    settings: Settings,
    *,
    prompt: str,
    model: Optional[str] = None,
    aspect_ratio: str = "1:1",
    resolution: str = "2k",
    n: int = 1,
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
        )
    finally:
        spinner.stop()
    output.emit_result(
        settings.output_format,
        {"paths": [str(p) for p in paths]},
        "\n".join(str(p) for p in paths),
    )
    return 0


DEFAULT_EDIT_MODEL = "grok-imagine-image"


def run_image_edit(
    settings: Settings,
    *,
    prompt: str,
    sources: List[str],
    model: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    n: int = 1,
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
        )
    finally:
        spinner.stop()
    output.emit_result(settings.output_format, {"paths": [str(p) for p in paths]}, "\n".join(str(p) for p in paths))
    return 0

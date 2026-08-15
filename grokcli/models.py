"""Known xAI model names and capability hints.

These are convenience defaults and validation hints only — the authoritative
list comes from ``GET /v1/models`` (see ``grokcli models``). New models work
without a code change; this catalog just powers tab-completion-style help and
sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

# Chat / reasoning models (Responses API). Verified against GET /v1/models
# (2026-08): ``grok-4.5`` is the flagship SOTA (500k context, reasoning effort
# none/low/medium/high); ``grok-4`` also resolves as an unlisted alias. The
# grok-4.2 beta family (grok-4.20-*) was dropped from this catalog as stale.
CHAT_MODELS: FrozenSet[str] = frozenset(
    {
        "grok-4.5",
        "grok-4.3",
        "grok-build-0.1",
        "grok-4",
    }
)

# Configurable reasoning effort for chat models (Responses API
# ``reasoning: {effort}``). ``none`` disables reasoning entirely.
REASONING_EFFORTS: FrozenSet[str] = frozenset({"none", "low", "medium", "high"})

IMAGE_MODELS: Dict[str, str] = {
    # Imagine Image 2.0 (2026-08-07) — live in the API since 2026-08; the
    # docs recommend it and it undercuts the old quality tier ($0.04 vs
    # $0.05/image). Strong instruction-following and typography.
    "grok-imagine-image-2.0": "Imagine Image 2.0 — recommended; sharp text, strong prompt adherence",
    "grok-imagine-image-quality": "Higher fidelity (~10-20s)",
    "grok-imagine-image": "Fast image generation (~5-10s)",
}

# Per-model source-image caps for POST /images/edits. The API guide documents
# "up to 3 source images in a single request" for every current model,
# including 2.0 (its consumer-app "5 inputs" multi-reference editing is not
# exposed via the API). Unknown models stay permissive via the default.
IMAGE_EDIT_MAX_SOURCES: Dict[str, int] = {}
MAX_EDIT_SOURCES = 3


def image_edit_max_sources(model: str) -> int:
    """Max source images ``/images/edits`` accepts for ``model``."""
    return IMAGE_EDIT_MAX_SOURCES.get(model, MAX_EDIT_SOURCES)

VIDEO_MODELS: Dict[str, str] = {
    "grok-imagine-video-1.5": "Text-, image-, and reference-to-video; native 1080p (R2V capped at 720p)",
    "grok-imagine-video": "Text-to-video and reference-to-video (R2V)",
}

# Media parameter value sets (validated client-side before hitting the API).
ASPECT_RATIOS: FrozenSet[str] = frozenset(
    {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
)

# Image generation accepts a wider set (docs 2026-08), including phone-full-
# screen ratios and "auto" (model picks). Video keeps the classic 7 above.
IMAGE_ASPECT_RATIOS: FrozenSet[str] = ASPECT_RATIOS | frozenset(
    {"9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "auto"}
)
IMAGE_RESOLUTIONS: FrozenSet[str] = frozenset({"1k", "2k"})
# Docs guide: "up to 10 images per request" (generation and edits).
IMAGE_COUNT_MAX = 10
# response_format picks the delivery shape: a short-lived URL (default) or
# inline base64 (one round-trip, no follow-up download).
RESPONSE_FORMATS: FrozenSet[str] = frozenset({"url", "b64_json"})
VIDEO_RESOLUTIONS: FrozenSet[str] = frozenset({"480p", "720p", "1080p"})

VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15
# Video *extension* segments are capped differently than generation (2-10s).
VIDEO_EXTEND_DURATION_MIN = 2
VIDEO_EXTEND_DURATION_MAX = 10
# Preset-voice narration for reference-to-video (``reference_audios``).
MAX_REFERENCE_AUDIOS = 3

# Resolution ordering, used to compare e.g. "R2V capped at 720p".
_RESOLUTION_RANK = {"480p": 0, "720p": 1, "1080p": 2}


@dataclass(frozen=True)
class VideoModelSpec:
    """Per-model video capabilities and limits.

    Values verified against the xAI docs (2026-08): generation is 1-15s,
    extension segments 2-10s; the 1.5 model is the unified T2V/I2V/R2V model
    with native 1080p for T2V/I2V (R2V capped at 720p) and preset-voice
    narration; the base model is T2V/R2V only. The API remains the final
    authority — this table catches obvious mistakes early and routes capability
    errors with guidance, but never blocks a value the API would accept.
    """

    min_duration: int = VIDEO_DURATION_MIN
    max_duration: int = VIDEO_DURATION_MAX
    min_extend_duration: int = VIDEO_EXTEND_DURATION_MIN
    max_extend_duration: int = VIDEO_EXTEND_DURATION_MAX
    resolutions: FrozenSet[str] = VIDEO_RESOLUTIONS
    aspect_ratios: FrozenSet[str] = ASPECT_RATIOS
    supports_image: bool = True       # image-to-video (first frame)
    supports_reference: bool = True   # reference-to-video (R2V)
    r2v_max_resolution: Optional[str] = None  # R2V resolution cap, e.g. "720p"
    max_reference_audios: int = MAX_REFERENCE_AUDIOS  # 0 = preset voices unsupported


VIDEO_MODEL_SPECS: Dict[str, "VideoModelSpec"] = {
    # 1.5 (current flagship): all three modes + preset-voice R2V narration;
    # native 1080p for T2V/I2V, R2V capped at 720p.
    "grok-imagine-video-1.5": VideoModelSpec(r2v_max_resolution="720p"),
    # Base model: text-to-video + reference-to-video; rejects a first-frame
    # image and preset-voice narration.
    "grok-imagine-video": VideoModelSpec(
        supports_image=False, max_reference_audios=0
    ),
}
# Unknown/future models: permissive — let the API be the authority.
DEFAULT_VIDEO_SPEC = VideoModelSpec()


def video_spec(model: str) -> "VideoModelSpec":
    """Return the capability spec for ``model`` (permissive default if unknown)."""
    return VIDEO_MODEL_SPECS.get(model, DEFAULT_VIDEO_SPEC)


def resolution_rank(resolution: str) -> int:
    """Order resolutions for capability caps; unknown values rank highest."""
    return _RESOLUTION_RANK.get(resolution, 10)

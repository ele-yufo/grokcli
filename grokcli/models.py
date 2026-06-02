"""Known xAI model names and capability hints.

These are convenience defaults and validation hints only — the authoritative
list comes from ``GET /v1/models`` (see ``grokcli models``). New models work
without a code change; this catalog just powers tab-completion-style help and
sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet

# Chat / reasoning models (Responses API). Verified against GET /v1/models
# (2026-06); ``grok-4`` also resolves as an unlisted alias.
CHAT_MODELS: FrozenSet[str] = frozenset(
    {
        "grok-4.3",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
        "grok-4.20-multi-agent-0309",
        "grok-build-0.1",
        "grok-4",
    }
)

IMAGE_MODELS: Dict[str, str] = {
    "grok-imagine-image": "Fast image generation (~5-10s)",
    "grok-imagine-image-quality": "Higher fidelity (~10-20s)",
}

VIDEO_MODELS: Dict[str, str] = {
    "grok-imagine-video": "Text-to-video and reference-to-video (R2V)",
    "grok-imagine-video-1.5-preview": "Image-to-video (latest)",
}

# Media parameter value sets (validated client-side before hitting the API).
ASPECT_RATIOS: FrozenSet[str] = frozenset(
    {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
)
IMAGE_RESOLUTIONS: FrozenSet[str] = frozenset({"1k", "2k"})
# 1080p exists but is subscription-tier-gated — allow it client-side and let the
# API reject it ("not available for your team") rather than over-restrict here.
VIDEO_RESOLUTIONS: FrozenSet[str] = frozenset({"480p", "720p", "1080p"})

VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15


@dataclass(frozen=True)
class VideoModelSpec:
    """Per-model video capabilities and limits.

    Values verified live against the API (2026-06): both shipping models validate
    duration 1-15s at submit; the base model supports reference-to-video while the
    1.5-preview supports image-to-video. The API remains the final authority — this
    table catches obvious mistakes early and routes capability errors with guidance,
    but never blocks a value the API would actually accept.
    """

    min_duration: int = VIDEO_DURATION_MIN
    max_duration: int = VIDEO_DURATION_MAX
    resolutions: FrozenSet[str] = VIDEO_RESOLUTIONS
    aspect_ratios: FrozenSet[str] = ASPECT_RATIOS
    supports_image: bool = True       # image-to-video (first-frame)
    supports_reference: bool = True   # reference-to-video (R2V)


VIDEO_MODEL_SPECS: Dict[str, "VideoModelSpec"] = {
    # Base model: text-to-video + reference-to-video; rejects a first-frame image.
    "grok-imagine-video": VideoModelSpec(supports_image=False, supports_reference=True),
    # Preview model: image-to-video; rejects reference_images (HTTP 400, verified live).
    "grok-imagine-video-1.5-preview": VideoModelSpec(supports_image=True, supports_reference=False),
}
# Unknown/future models: permissive — let the API be the authority.
DEFAULT_VIDEO_SPEC = VideoModelSpec(supports_image=True, supports_reference=True)


def video_spec(model: str) -> "VideoModelSpec":
    """Return the capability spec for ``model`` (permissive default if unknown)."""
    return VIDEO_MODEL_SPECS.get(model, DEFAULT_VIDEO_SPEC)

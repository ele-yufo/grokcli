"""Known xAI model names and capability hints.

These are convenience defaults and validation hints only — the authoritative
list comes from ``GET /v1/models`` (see ``grokcli models``). New models work
without a code change; this catalog just powers tab-completion-style help and
sensible defaults.
"""

from __future__ import annotations

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
    "grok-imagine-video": "Text-to-video",
    "grok-imagine-video-1.5-preview": "Image-to-video (latest)",
}

# Media parameter value sets (validated client-side before hitting the API).
ASPECT_RATIOS: FrozenSet[str] = frozenset(
    {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
)
IMAGE_RESOLUTIONS: FrozenSet[str] = frozenset({"1k", "2k"})
VIDEO_RESOLUTIONS: FrozenSet[str] = frozenset({"480p", "720p"})

VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15

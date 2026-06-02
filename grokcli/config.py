"""Configuration: paths, persisted settings, and runtime resolution.

Resolution precedence for every setting is: CLI flag > environment variable >
config file (``~/.config/grokcli/config.json``) > built-in default.

The config home is independent of the official Grok CLI's ``~/.grok`` directory
to avoid clobbering its credentials; override with ``GROKCLI_HOME``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from . import fsutil

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_CHAT_MODEL = "grok-4.3"
DEFAULT_IMAGE_MODEL = "grok-imagine-image-quality"
DEFAULT_VIDEO_MODEL = "grok-imagine-video"
DEFAULT_TTS_MODEL = "grok-tts"
DEFAULT_STT_MODEL = "grok-transcribe"
DEFAULT_TIMEOUT_SECONDS = 300.0

# Persisted config keys (the subset of Settings that it makes sense to save).
_PERSISTED_KEYS = (
    "base_url",
    "chat_model",
    "image_model",
    "video_model",
    "tts_model",
    "stt_model",
    "tts_voice",
    "output_dir",
    "timeout",
    "proxy",
)


def home_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return the grokcli config/credential home directory.

    ``GROKCLI_HOME`` overrides the default ``~/.config/grokcli``.
    """
    env = os.environ if env is None else env
    override = (env.get("GROKCLI_HOME") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "grokcli"


def config_path(env: Optional[Mapping[str, str]] = None) -> Path:
    return home_dir(env) / "config.json"


def auth_path(env: Optional[Mapping[str, str]] = None) -> Path:
    return home_dir(env) / "auth.json"


def auth_lock_path(env: Optional[Mapping[str, str]] = None) -> Path:
    return home_dir(env) / "auth.json.lock"


def sessions_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return home_dir(env) / "sessions"


def default_output_dir() -> Path:
    return Path.home() / "grokcli-output"


def load_config_file(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Read the JSON config file, returning ``{}`` if missing or unparseable."""
    path = config_path(env)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config_file(data: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> Path:
    """Persist ``data`` (only known keys) to the config file atomically."""
    clean = {k: data[k] for k in _PERSISTED_KEYS if k in data and data[k] is not None}
    text = json.dumps(clean, indent=2, ensure_ascii=False) + "\n"
    return fsutil.atomic_write_text(config_path(env), text)


def set_config_value(key: str, value: Any, env: Optional[Mapping[str, str]] = None) -> Path:
    """Update a single persisted config ``key`` and rewrite the file."""
    if key not in _PERSISTED_KEYS:
        from .errors import UsageError

        raise UsageError(
            f"Unknown config key: {key!r}.",
            hint=f"Valid keys: {', '.join(_PERSISTED_KEYS)}",
        )
    if key == "base_url":
        # Reject up front rather than silently neutralizing it at resolve time.
        pinned = validate_base_url(str(value))
        if pinned != str(value).strip().rstrip("/"):
            from .errors import UsageError

            raise UsageError(
                f"Refusing to set base_url to {value!r}.",
                hint="base_url must be HTTPS on x.ai or a *.x.ai subdomain.",
            )
        value = pinned
    data = load_config_file(env)
    data[key] = value
    return save_config_file(data, env)


def validate_base_url(candidate: str, *, fallback: str = DEFAULT_BASE_URL) -> str:
    """Pin the inference base URL to HTTPS on the xAI origin.

    The OAuth bearer is a high-value credential tied to the user's subscription;
    sending it to an arbitrary host would leak it. A bad override falls back to
    the default rather than raising, so a stray env var cannot deadlock the CLI.
    """
    value = (candidate or "").strip().rstrip("/")
    if not value:
        return fallback
    try:
        parsed = urlparse(value)
    except ValueError:
        return fallback
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return fallback
    if host != "x.ai" and not host.endswith(".x.ai"):
        return fallback
    return value


def detect_output_format(stream: Any = None) -> str:
    """Default to machine-readable JSON when output is piped, text on a TTY."""
    stream = sys.stdout if stream is None else stream
    try:
        return "text" if stream.isatty() else "json"
    except (AttributeError, ValueError):
        return "json"


def detect_color(env: Optional[Mapping[str, str]] = None, stream: Any = None) -> bool:
    """Enable ANSI color only on a TTY and when ``NO_COLOR`` is unset."""
    env = os.environ if env is None else env
    if env.get("NO_COLOR") or env.get("GROKCLI_NO_COLOR"):
        return False
    stream = sys.stderr if stream is None else stream
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


@dataclass
class Settings:
    """Fully resolved runtime configuration for one CLI invocation."""

    base_url: str = DEFAULT_BASE_URL
    chat_model: str = DEFAULT_CHAT_MODEL
    image_model: str = DEFAULT_IMAGE_MODEL
    video_model: str = DEFAULT_VIDEO_MODEL
    tts_model: str = DEFAULT_TTS_MODEL
    stt_model: str = DEFAULT_STT_MODEL
    tts_voice: Optional[str] = None
    output_dir: Path = field(default_factory=default_output_dir)
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    proxy: Optional[str] = None
    output_format: str = "text"
    color: bool = True
    verbose: bool = False
    home: Path = field(default_factory=home_dir)


def _first(*values: Any) -> Optional[Any]:
    """Return the first value that is neither None nor an empty string."""
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _truthy(value: Any) -> bool:
    """Interpret an env-style flag: unset/0/false/no/off are False."""
    return str(value or "").strip().lower() not in ("", "0", "false", "no", "off")


def resolve_settings(
    overrides: Optional[Mapping[str, Any]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    file_cfg: Optional[Mapping[str, Any]] = None,
) -> Settings:
    """Merge CLI ``overrides`` > ``env`` > ``file_cfg`` > defaults into Settings.

    ``overrides`` carries only flags the user actually passed (None otherwise).
    """
    overrides = overrides or {}
    env = os.environ if env is None else env
    file_cfg = load_config_file(env) if file_cfg is None else file_cfg

    base_url = validate_base_url(
        str(
            _first(
                overrides.get("base_url"),
                env.get("GROKCLI_BASE_URL"),
                env.get("XAI_BASE_URL"),
                file_cfg.get("base_url"),
                DEFAULT_BASE_URL,
            )
        )
    )

    timeout_raw = _first(
        overrides.get("timeout"),
        env.get("GROKCLI_TIMEOUT"),
        file_cfg.get("timeout"),
        DEFAULT_TIMEOUT_SECONDS,
    )
    try:
        timeout = max(1.0, float(timeout_raw)) if timeout_raw is not None else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS

    output_dir_raw = _first(
        overrides.get("output_dir"),
        env.get("GROKCLI_OUTPUT_DIR"),
        file_cfg.get("output_dir"),
    )
    output_dir = Path(str(output_dir_raw)).expanduser() if output_dir_raw else default_output_dir()

    output_format = str(
        _first(overrides.get("output_format"), env.get("GROKCLI_OUTPUT")) or detect_output_format()
    ).lower()
    if output_format not in ("text", "json"):
        output_format = "text"

    no_color_flag = overrides.get("no_color")
    color = (not no_color_flag) and detect_color(env)

    proxy = _first(
        overrides.get("proxy"),
        env.get("HTTPS_PROXY"),
        env.get("https_proxy"),
        env.get("ALL_PROXY"),
        file_cfg.get("proxy"),
    )

    return Settings(
        base_url=base_url,
        chat_model=str(_first(overrides.get("chat_model"), env.get("GROKCLI_CHAT_MODEL"), file_cfg.get("chat_model"), DEFAULT_CHAT_MODEL)),
        image_model=str(_first(overrides.get("image_model"), file_cfg.get("image_model"), DEFAULT_IMAGE_MODEL)),
        video_model=str(_first(overrides.get("video_model"), file_cfg.get("video_model"), DEFAULT_VIDEO_MODEL)),
        tts_model=str(_first(overrides.get("tts_model"), file_cfg.get("tts_model"), DEFAULT_TTS_MODEL)),
        stt_model=str(_first(overrides.get("stt_model"), file_cfg.get("stt_model"), DEFAULT_STT_MODEL)),
        tts_voice=_first(overrides.get("tts_voice"), file_cfg.get("tts_voice")),
        output_dir=output_dir,
        timeout=timeout,
        proxy=str(proxy) if proxy else None,
        output_format=output_format,
        color=bool(color),
        verbose=bool(overrides.get("verbose")) or _truthy(env.get("GROKCLI_VERBOSE")),
        home=home_dir(env),
    )

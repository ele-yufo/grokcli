"""Persistence for xAI OAuth credentials at ``~/.config/grokcli/auth.json``.

The store is a single JSON object (owner-only, 0600) written atomically under a
cross-process advisory lock. It is deliberately independent of the official Grok
CLI's ``~/.grok/auth.json`` so the two never clobber each other.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from .. import config, fsutil

STORE_VERSION = 1
PROVIDER = "xai-oauth"


def now_iso() -> str:
    """UTC timestamp in RFC 3339 form (``...Z``)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_unlocked(env: Optional[Mapping[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Read+parse the auth state WITHOUT taking the lock (caller must hold it).

    Returns ``None`` if the file is absent, unparseable, or has no tokens block.
    """
    path = config.auth_path(env)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tokens"), dict):
        return None
    return data


def write_unlocked(state: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> None:
    """Write the auth state WITHOUT taking the lock (caller must hold it)."""
    payload = dict(state)
    payload.setdefault("version", STORE_VERSION)
    payload.setdefault("provider", PROVIDER)
    payload.setdefault("auth_mode", "oauth_pkce")
    payload["updated_at"] = now_iso()
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fsutil.atomic_write_text(config.auth_path(env), text)


def lock(env: Optional[Mapping[str, str]] = None):
    """Return the cross-process advisory lock context manager for the store."""
    return fsutil.file_lock(config.auth_lock_path(env))


def load(env: Optional[Mapping[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Return the stored auth state, or ``None`` if absent/unparseable."""
    with lock(env):
        return read_unlocked(env)


def save(state: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> None:
    """Persist ``state`` atomically with owner-only permissions."""
    with lock(env):
        write_unlocked(state, env)


def clear(env: Optional[Mapping[str, str]] = None) -> bool:
    """Delete the auth file (logout). Returns True if a file was removed."""
    path = config.auth_path(env)
    with lock(env):
        if path.exists():
            path.unlink()
            return True
    return False


def new_state(
    *,
    tokens: Dict[str, Any],
    discovery: Mapping[str, str],
    redirect_uri: str,
    base_url: str,
    account: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble a fresh auth-state object from a completed login."""
    return {
        "version": STORE_VERSION,
        "provider": PROVIDER,
        "auth_mode": "oauth_pkce",
        "base_url": base_url,
        "tokens": dict(tokens),
        "discovery": dict(discovery),
        "redirect_uri": redirect_uri,
        "last_refresh": now_iso(),
        "last_auth_error": None,
        "account": dict(account) if account else {},
    }


def record_error(state: Optional[Mapping[str, Any]], error: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> None:
    """Persist a ``last_auth_error`` so ``status``/``doctor`` can surface it.

    Re-reads the on-disk state under the lock (ignoring the possibly-stale
    ``state`` arg) so a concurrent successful refresh is never overwritten.
    """
    del state  # advisory only; the on-disk state is authoritative
    with lock(env):
        current = read_unlocked(env)
        if not current or not current.get("tokens"):
            return
        current["last_auth_error"] = {**dict(error), "at": now_iso()}
        write_unlocked(current, env)

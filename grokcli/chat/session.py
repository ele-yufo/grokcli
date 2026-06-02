"""Bounded local persistence for resumable chat conversations.

Each conversation is one small JSON file at ``~/.config/grokcli/sessions/<id>.json``
holding ``{version, id, created, updated, model, system, messages}``. Persistence
is purely event-driven (write-on-turn, atomic) — there is no polling or daemon.

Growth is bounded two ways so the store can never grow without limit:
  * per-session: only the most recent ``max_messages`` messages are kept (oldest
    user/assistant pairs are trimmed), which also caps the per-request payload;
  * across sessions: an LRU cap on the number of session files — creating a new
    session prunes the oldest beyond ``max_sessions`` (by mtime).

Tune via ``GROKCLI_MAX_SESSION_MESSAGES`` / ``GROKCLI_MAX_SESSIONS``.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .. import config, fsutil

SESSION_VERSION = 1
DEFAULT_MAX_MESSAGES = 100  # ~50 user/assistant exchanges
DEFAULT_MAX_SESSIONS = 50
_ID_RE = re.compile(r"[^a-zA-Z0-9._-]")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _max_messages(env: Optional[Mapping[str, str]]) -> int:
    return _int_env(env, "GROKCLI_MAX_SESSION_MESSAGES", DEFAULT_MAX_MESSAGES)


def _max_sessions(env: Optional[Mapping[str, str]]) -> int:
    return _int_env(env, "GROKCLI_MAX_SESSIONS", DEFAULT_MAX_SESSIONS)


def _int_env(env: Optional[Mapping[str, str]], key: str, default: int) -> int:
    import os

    raw = (os.environ if env is None else env).get(key)
    try:
        return max(1, int(raw)) if raw else default
    except (TypeError, ValueError):
        return default


def new_id() -> str:
    """A sortable, unique session id: ``<UTC timestamp>_<6 hex>``."""
    return f"{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{secrets.token_hex(3)}"


def sanitize_id(name: str) -> str:
    """Make a user-supplied session name safe to use as a filename."""
    cleaned = _ID_RE.sub("-", name.strip())[:64].strip("-.")
    return cleaned or new_id()


def session_path(session_id: str, env: Optional[Mapping[str, str]] = None) -> Path:
    return config.sessions_dir(env) / f"{session_id}.json"


@dataclass
class Session:
    id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    model: Optional[str] = None
    system: Optional[str] = None
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": SESSION_VERSION,
            "id": self.id,
            "created": self.created,
            "updated": self.updated,
            "model": self.model,
            "system": self.system,
            "messages": self.messages,
        }


def new_session(*, model: Optional[str] = None, system: Optional[str] = None, session_id: Optional[str] = None) -> Session:
    return Session(id=session_id or new_id(), model=model, system=system)


def load(session_id: str, env: Optional[Mapping[str, str]] = None) -> Optional[Session]:
    path = session_path(session_id, env)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    return Session(
        id=str(data.get("id") or session_id),
        messages=[m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else [],
        model=data.get("model"),
        system=data.get("system"),
        created=str(data.get("created") or _now()),
        updated=str(data.get("updated") or _now()),
    )


def latest(env: Optional[Mapping[str, str]] = None) -> Optional[Session]:
    """Return the most-recently-updated session, or None if there are none."""
    files = _session_files(env)
    if not files:
        return None
    return load(files[0].stem, env)


def resolve(
    *,
    continue_latest: bool = False,
    name: Optional[str] = None,
    force_new: bool = False,
    model: Optional[str] = None,
    system: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Session:
    """Pick the session to use: ``--new`` > ``--session NAME`` > ``-c`` > fresh."""
    if not force_new and name:
        sid = sanitize_id(name)
        existing = load(sid, env)
        return existing or new_session(model=model, system=system, session_id=sid)
    if not force_new and continue_latest:
        existing = latest(env)
        if existing is not None:
            return existing
    return new_session(model=model, system=system)


def save(session: Session, env: Optional[Mapping[str, str]] = None) -> Path:
    """Trim to the per-session cap, write atomically, and LRU-prune the store."""
    cap = _max_messages(env)
    if len(session.messages) > cap:
        trimmed = session.messages[-cap:]
        # Don't leave a dangling leading assistant turn after trimming a pair.
        if trimmed and trimmed[0].get("role") == "assistant":
            trimmed = trimmed[1:]
        session.messages = trimmed
    session.updated = _now()
    path = session_path(session.id, env)
    is_new = not path.exists()
    fsutil.secure_dir(config.sessions_dir(env))
    fsutil.atomic_write_text(path, json.dumps(session.to_dict(), indent=2, ensure_ascii=False) + "\n", mode=0o600)
    if is_new:
        _prune_lru(env)
    return path


def _prune_lru(env: Optional[Mapping[str, str]] = None) -> int:
    """Delete oldest session files beyond the count cap. Returns how many removed."""
    files = _session_files(env)
    cap = _max_sessions(env)
    removed = 0
    for stale in files[cap:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _session_files(env: Optional[Mapping[str, str]] = None) -> List[Path]:
    """Session files, newest first by mtime."""
    directory = config.sessions_dir(env)
    if not directory.exists():
        return []
    files = [p for p in directory.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def list_sessions(env: Optional[Mapping[str, str]] = None) -> List[Dict[str, Any]]:
    """Return metadata for each stored session, newest first."""
    out: List[Dict[str, Any]] = []
    for path in _session_files(env):
        session = load(path.stem, env)
        if session is None:
            continue
        first_user = next((m["content"] for m in session.messages if m.get("role") == "user"), "")
        out.append(
            {
                "id": session.id,
                "updated": session.updated,
                "turns": sum(1 for m in session.messages if m.get("role") == "user"),
                "model": session.model,
                "preview": first_user[:60],
            }
        )
    return out


def clear(session_id: Optional[str] = None, *, all_sessions: bool = False, env: Optional[Mapping[str, str]] = None) -> int:
    """Delete one session (by id) or all. Returns the number removed."""
    if all_sessions:
        removed = 0
        for path in _session_files(env):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed
    if session_id:
        path = session_path(sanitize_id(session_id), env)
        if path.exists():
            path.unlink()
            return 1
    return 0

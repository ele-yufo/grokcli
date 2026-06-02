"""Token lifecycle: JWT expiry, proactive refresh, runtime resolution, import.

The access token is a JWT, so expiry is read from its ``exp`` claim. When that
is unavailable we fall back to ``last_refresh + expires_in``. A token within
:data:`grokcli.auth.oauth.ACCESS_TOKEN_REFRESH_SKEW_SECONDS` of expiry is
refreshed proactively before a request goes out.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from ..errors import AuthError
from ..transport import HttpClient
from . import oauth, store


def decode_jwt_claims(token: str) -> Dict[str, Any]:
    """Decode (without verifying) a JWT's payload claims; ``{}`` on failure."""
    if not isinstance(token, str) or token.count(".") < 2:
        return {}
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def access_token_expiry(token: str) -> Optional[float]:
    """Return the JWT ``exp`` (epoch seconds), or ``None`` if not a dated JWT."""
    exp = decode_jwt_claims(token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def _parse_iso(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def is_expiring(state: Mapping[str, Any], skew_seconds: int = oauth.ACCESS_TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    """True if the stored access token is missing, expired, or expiring soon.

    Returns False when expiry is genuinely unknown — a reactive 401 refresh will
    cover that case rather than refreshing on every call.
    """
    tokens = state.get("tokens") or {}
    access = str(tokens.get("access_token") or "").strip()
    if not access:
        return True
    deadline = time.time() + max(0, int(skew_seconds))
    exp = access_token_expiry(access)
    if exp is not None:
        return exp <= deadline
    last_refresh = _parse_iso(state.get("last_refresh"))
    expires_in = tokens.get("expires_in")
    if last_refresh is not None and isinstance(expires_in, (int, float)):
        return (last_refresh + float(expires_in)) <= deadline
    return False


def _refresh_client(settings: Any = None) -> HttpClient:
    proxy = getattr(settings, "proxy", None)
    verbose = bool(getattr(settings, "verbose", False))
    return HttpClient(timeout=20.0, proxy=proxy, max_retries=1, verbose=verbose)


def ensure_fresh(
    state: Dict[str, Any],
    *,
    client: Optional[HttpClient] = None,
    env: Optional[Mapping[str, str]] = None,
    force: bool = False,
    settings: Any = None,
) -> Tuple[Dict[str, Any], bool]:
    """Refresh the access token if it is expiring (or ``force``). Persist and return.

    The whole read-recheck-refresh-write cycle runs under the store's advisory
    lock, so concurrent processes serialize: the second one re-reads the freshly
    refreshed token and skips its own (now-redundant, would-fail) refresh. Returns
    ``(state, refreshed)``; on a terminal failure records the error and re-raises.
    """
    if not force and not is_expiring(state):
        return state, False
    client = client or _refresh_client(settings)
    with store.lock(env):
        current = store.read_unlocked(env) or dict(state)
        # Another process may have refreshed while we waited for the lock.
        if not force and not is_expiring(current):
            return current, False
        discovery = dict(current.get("discovery") or {})
        token_endpoint = str(discovery.get("token_endpoint") or "").strip()
        if not token_endpoint:
            discovery = oauth.discover(client)
            token_endpoint = discovery["token_endpoint"]
        refresh_token = str((current.get("tokens") or {}).get("refresh_token") or "").strip()
        try:
            payload = oauth.refresh(client, token_endpoint=token_endpoint, refresh_token=refresh_token)
        except AuthError as exc:
            current["last_auth_error"] = {
                "code": exc.code or "xai_refresh_failed",
                "message": exc.message,
                "relogin_required": exc.relogin_required,
                "entitlement_denied": exc.entitlement_denied,
                "at": store.now_iso(),
            }
            store.write_unlocked(current, env)
            raise
        current["tokens"] = oauth.normalize_tokens(payload, previous=current.get("tokens"))
        current["discovery"] = discovery
        current["last_refresh"] = store.now_iso()
        current["last_auth_error"] = None
        store.write_unlocked(current, env)
        return current, True


def resolve_runtime_credentials(
    *,
    env: Optional[Mapping[str, str]] = None,
    force_refresh: bool = False,
    settings: Any = None,
) -> Dict[str, Any]:
    """Load credentials, refresh if needed, and return the usable bearer.

    Raises :class:`AuthError` (relogin required) when not logged in.
    """
    state = store.load(env)
    if state is None:
        raise AuthError(
            "Not logged in. Run `grokcli login` to authenticate with your "
            "SuperGrok / X Premium+ subscription.",
            code="not_logged_in",
            relogin_required=True,
        )
    state, _ = ensure_fresh(state, env=env, force=force_refresh, settings=settings)
    tokens = state.get("tokens") or {}
    return {
        "access_token": str(tokens.get("access_token") or "").strip(),
        "token_type": str(tokens.get("token_type") or "Bearer").strip() or "Bearer",
        "base_url": str(state.get("base_url") or "").strip(),
        "account": dict(state.get("account") or {}),
    }


def import_from_official_grok(
    env: Optional[Mapping[str, str]] = None,
    *,
    official_path: Optional[Path] = None,
) -> bool:
    """Import an existing login from the official Grok CLI's ``~/.grok/auth.json``.

    One-time bootstrap. Returns True if credentials were imported. Note: the two
    CLIs then share a refresh token; the first to refresh may rotate it.
    """
    official = official_path or (Path.home() / ".grok" / "auth.json")
    if not official.exists():
        return False
    try:
        data = json.loads(official.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    entry = _find_official_entry(data)
    if not entry:
        return False
    access = str(entry.get("key") or "").strip()
    refresh_token = str(entry.get("refresh_token") or "").strip()
    if not access or not refresh_token:
        return False
    tokens = {
        "access_token": access,
        "refresh_token": refresh_token,
        "id_token": "",
        "token_type": "Bearer",
        "expires_in": None,
    }
    account = {
        "email": entry.get("email", ""),
        "user_id": entry.get("user_id", ""),
    }
    from ..config import DEFAULT_BASE_URL

    state = store.new_state(
        tokens=tokens,
        discovery={
            "authorization_endpoint": oauth.DEFAULT_AUTHORIZATION_ENDPOINT,
            "token_endpoint": oauth.DEFAULT_TOKEN_ENDPOINT,
        },
        redirect_uri=f"http://{oauth.REDIRECT_HOST}:{oauth.REDIRECT_PORT}{oauth.REDIRECT_PATH}",
        base_url=DEFAULT_BASE_URL,
        account=account,
    )
    store.save(state, env)
    return True


def _find_official_entry(data: Any) -> Optional[Dict[str, Any]]:
    """Locate the xAI OAuth identity in the official CLI's keyed auth store."""
    if not isinstance(data, dict):
        return None
    preferred_key = f"{oauth.ISSUER}::{oauth.CLIENT_ID}"
    entry = data.get(preferred_key)
    if isinstance(entry, dict):
        return entry
    for value in data.values():
        if isinstance(value, dict) and str(value.get("oidc_issuer") or "") == oauth.ISSUER:
            return value
    return None

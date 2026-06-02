"""The xAI Grok OAuth 2.0 (PKCE) protocol: constants, discovery, code exchange, refresh.

Constants and quirks are verified against the official Grok CLI, Hermes Agent, and
the independent Rust ``Moore-developers/grok-cli`` — see the project notes:

* ``plan=generic`` on the authorize request is mandatory; without it accounts.x.ai
  rejects loopback OAuth from non-allowlisted clients.
* The token exchange must **echo** ``code_challenge`` + ``code_challenge_method``
  alongside ``code_verifier`` — xAI re-validates the challenge at the token step.
* A ``403`` from the token/refresh endpoint is a subscription tier/entitlement
  denial, not a stale token (re-login will not fix it). HttpClient maps that to
  :class:`grokcli.errors.TierDeniedError` already.

This module is transport-only over :class:`grokcli.transport.HttpClient`; token
storage and the loopback browser dance live in sibling modules.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

from ..errors import APIError, AuthError, GrokError
from ..transport import HttpClient

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DEFAULT_AUTHORIZATION_ENDPOINT = f"{ISSUER}/oauth2/authorize"
DEFAULT_TOKEN_ENDPOINT = f"{ISSUER}/oauth2/token"
SCOPE = "openid profile email offline_access grok-cli:access api:access"

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 56121
REDIRECT_PATH = "/callback"

# Authorize-request attribution. ``plan`` is mandatory; ``referrer`` is best-effort.
AUTHORIZE_PLAN = "generic"
AUTHORIZE_REFERRER = "grokcli"

# Refresh the access token this many seconds before its stated expiry.
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 300

_FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
}


def generate_code_verifier() -> str:
    """Return a high-entropy PKCE ``code_verifier`` (RFC 7636, 43–128 chars)."""
    verifier = secrets.token_urlsafe(64)
    return verifier[:128]


def code_challenge(code_verifier: str) -> str:
    """Return the S256 ``code_challenge`` for ``code_verifier`` (base64url, no pad)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def random_state() -> str:
    return secrets.token_hex(16)


def validate_endpoint(url: str, *, field: str) -> str:
    """Reject any OIDC endpoint that is not HTTPS on the xAI origin.

    The discovery document is cached and its ``token_endpoint`` later receives
    the refresh token on every refresh; a MITM that substituted a hostile
    endpoint once would harvest the refresh token forever. Pin to ``x.ai`` /
    ``*.x.ai`` over HTTPS.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or (host != "x.ai" and not host.endswith(".x.ai")):
        raise AuthError(
            f"xAI OIDC {field} is not on the xAI origin: {url!r}.",
            code="xai_discovery_invalid",
        )
    return url


def discover(client: HttpClient, *, timeout: float = 20.0) -> Dict[str, str]:
    """Fetch the OIDC discovery document, falling back to hardcoded endpoints.

    Endpoints from a successful discovery are validated to be HTTPS on x.ai.
    """
    try:
        payload = client.request_json("GET", DISCOVERY_URL, timeout=timeout)
    except GrokError:
        payload = None
    if isinstance(payload, dict):
        authorize = str(payload.get("authorization_endpoint") or "").strip()
        token = str(payload.get("token_endpoint") or "").strip()
        if authorize and token:
            return {
                "authorization_endpoint": validate_endpoint(authorize, field="authorization_endpoint"),
                "token_endpoint": validate_endpoint(token, field="token_endpoint"),
            }
    return {
        "authorization_endpoint": DEFAULT_AUTHORIZATION_ENDPOINT,
        "token_endpoint": DEFAULT_TOKEN_ENDPOINT,
    }


def build_authorize_url(
    *,
    authorization_endpoint: str,
    redirect_uri: str,
    challenge: str,
    state: str,
    nonce: str,
) -> str:
    """Construct the browser authorization URL (PKCE S256 + plan/referrer)."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "plan": AUTHORIZE_PLAN,
        "referrer": AUTHORIZE_REFERRER,
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


def exchange_code(
    client: HttpClient,
    *,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    challenge: str,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Exchange an authorization ``code`` for tokens.

    Echoes ``code_challenge``/``code_challenge_method`` (the xAI quirk).
    """
    if not code_verifier:
        raise AuthError("PKCE code_verifier is empty (internal error).", code="xai_pkce_missing")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    payload = _post_token_form(client, token_endpoint, form, timeout=timeout, action="token exchange")
    _require_tokens(payload, require_refresh=True, action="token exchange")
    return payload


def refresh(
    client: HttpClient,
    *,
    token_endpoint: str,
    refresh_token: str,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Exchange a ``refresh_token`` for a new access token."""
    if not refresh_token:
        raise AuthError(
            "Stored credentials have no refresh_token; run `grokcli login`.",
            code="xai_refresh_missing",
            relogin_required=True,
        )
    form = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }
    payload = _post_token_form(client, token_endpoint, form, timeout=timeout, action="token refresh")
    _require_tokens(payload, require_refresh=False, action="token refresh")
    # Per the xAI contract, a refresh response may omit refresh_token; the caller
    # keeps the previous one in that case.
    return payload


def _post_token_form(
    client: HttpClient,
    token_endpoint: str,
    form: Dict[str, str],
    *,
    timeout: float,
    action: str,
) -> Dict[str, Any]:
    body = urlencode(form).encode("utf-8")
    try:
        response = client.request(
            "POST", token_endpoint, headers=_FORM_HEADERS, body=body, timeout=timeout
        )
    except AuthError as exc:  # 401 from the token endpoint => grant is dead
        raise AuthError(
            f"xAI {action} failed (HTTP 401): {exc.message}",
            code="xai_grant_invalid",
            relogin_required=True,
        ) from exc
    except APIError as exc:  # 400 invalid_grant / invalid_request
        relogin = exc.status_code in (400, 422) or "invalid_grant" in (exc.message or "").lower()
        raise AuthError(
            f"xAI {action} failed: {exc.message}",
            code="xai_grant_invalid",
            status_code=exc.status_code,
            relogin_required=relogin,
        ) from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise AuthError(f"xAI {action} returned a non-object response.", code="xai_token_invalid")
    return payload


def _require_tokens(payload: Dict[str, Any], *, require_refresh: bool, action: str) -> None:
    if not str(payload.get("access_token") or "").strip():
        raise AuthError(f"xAI {action} did not return an access_token.", code="xai_token_invalid")
    if require_refresh and not str(payload.get("refresh_token") or "").strip():
        raise AuthError(f"xAI {action} did not return a refresh_token.", code="xai_token_invalid")


def normalize_tokens(payload: Dict[str, Any], *, previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the stored ``tokens`` block from a token-endpoint response.

    Preserves the previous ``refresh_token`` when the response omits one.
    """
    previous = previous or {}
    refresh_token = str(payload.get("refresh_token") or "").strip() or str(
        previous.get("refresh_token") or ""
    ).strip()
    return {
        "access_token": str(payload.get("access_token") or "").strip(),
        "refresh_token": refresh_token,
        "id_token": str(payload.get("id_token") or "").strip() or previous.get("id_token", ""),
        "token_type": str(payload.get("token_type") or "Bearer").strip() or "Bearer",
        "expires_in": payload.get("expires_in", previous.get("expires_in")),
    }

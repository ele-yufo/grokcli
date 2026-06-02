"""Orchestration for ``grokcli login`` / ``logout`` / ``status``.

These functions drive the interactive OAuth dance (progress to stderr, prompts
on stdin) and return structured result dicts; the CLI layer renders them as text
or JSON. Token mechanics live in :mod:`grokcli.auth.oauth`/``tokens``/``store``.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, Mapping, Optional

from ..config import Settings
from ..errors import AuthError
from ..transport import HttpClient
from . import loopback, oauth, store, tokens


def _progress(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _client(settings: Settings) -> HttpClient:
    return HttpClient(timeout=20.0, proxy=settings.proxy, max_retries=1, verbose=settings.verbose)


def do_login(
    settings: Settings,
    *,
    env: Optional[Mapping[str, str]] = None,
    no_browser: bool = False,
    manual_paste: bool = False,
    from_official: bool = False,
    wait_seconds: float = 180.0,
) -> Dict[str, Any]:
    """Run the OAuth PKCE login and persist credentials. Returns a status dict."""
    if from_official:
        if tokens.import_from_official_grok(env):
            state = store.load(env) or {}
            _progress("Imported existing login from the official Grok CLI (~/.grok).")
            return {"status": "ok", "method": "import", "account": state.get("account", {})}
        raise AuthError(
            "No reusable login found in ~/.grok/auth.json to import.",
            code="official_import_failed",
        )

    client = _client(settings)
    _progress("Signing in to xAI Grok (SuperGrok / X Premium+)...")
    discovery = oauth.discover(client)
    verifier = oauth.generate_code_verifier()
    challenge = oauth.code_challenge(verifier)
    state_token = oauth.random_state()
    nonce = oauth.random_state()

    use_manual = manual_paste or loopback.is_remote_session(env)
    callback, redirect_uri = _collect_callback(
        discovery=discovery,
        challenge=challenge,
        state_token=state_token,
        nonce=nonce,
        no_browser=no_browser,
        use_manual=use_manual,
        env=env,
        wait_seconds=wait_seconds,
    )

    code = _validate_callback(callback, expected_state=state_token, manual=use_manual)
    _progress("Exchanging authorization code for tokens...")
    payload = oauth.exchange_code(
        client,
        token_endpoint=discovery["token_endpoint"],
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        challenge=challenge,
    )
    token_block = oauth.normalize_tokens(payload)
    _verify_nonce(token_block, expected_nonce=nonce)
    account = _account_from_tokens(token_block)
    state = store.new_state(
        tokens=token_block,
        discovery=discovery,
        redirect_uri=redirect_uri,
        base_url=settings.base_url,
        account=account,
    )
    store.save(state, env)
    return {"status": "ok", "method": "oauth", "account": account, "home": str(settings.home)}


def _collect_callback(
    *,
    discovery: Mapping[str, str],
    challenge: str,
    state_token: str,
    nonce: str,
    no_browser: bool,
    use_manual: bool,
    env: Optional[Mapping[str, str]],
    wait_seconds: float,
):
    """Return ``(callback_result, redirect_uri)`` via loopback or manual paste."""
    if use_manual:
        redirect_uri = f"http://{oauth.REDIRECT_HOST}:{oauth.REDIRECT_PORT}{oauth.REDIRECT_PATH}"
        loopback.validate_loopback_redirect(redirect_uri)
        authorize_url = oauth.build_authorize_url(
            authorization_endpoint=discovery["authorization_endpoint"],
            redirect_uri=redirect_uri,
            challenge=challenge,
            state=state_token,
            nonce=nonce,
        )
        _progress("\nOpen this URL in a browser to authorize grokcli:\n" + authorize_url)
        return loopback.prompt_manual_paste(redirect_uri), redirect_uri

    server = loopback.CallbackServer()
    redirect_uri = server.redirect_uri
    loopback.validate_loopback_redirect(redirect_uri)
    authorize_url = oauth.build_authorize_url(
        authorization_endpoint=discovery["authorization_endpoint"],
        redirect_uri=redirect_uri,
        challenge=challenge,
        state=state_token,
        nonce=nonce,
    )
    _progress("\nOpen this URL in a browser to authorize grokcli:\n" + authorize_url)
    _progress(f"\nWaiting for the callback on {redirect_uri} ...")
    if not no_browser and loopback.can_open_browser(env):
        if loopback.open_browser(authorize_url):
            _progress("Opened your browser for authorization.")
    try:
        return server.wait(wait_seconds), redirect_uri
    except AuthError:
        # Timed out — offer manual paste if we have an interactive stdin.
        if _stdin_is_tty():
            _progress("\nTimed out. If the browser reached a failed 127.0.0.1 page,")
            return loopback.prompt_manual_paste(redirect_uri), redirect_uri
        raise


def _validate_callback(callback: Mapping[str, Optional[str]], *, expected_state: str, manual: bool) -> str:
    if callback.get("error"):
        detail = callback.get("error_description") or callback.get("error")
        raise AuthError(f"Authorization failed: {detail}", code="authorization_failed")
    incoming_state = callback.get("state")
    # A bare pasted code (no state) is still bound by PKCE, so accept it.
    if incoming_state is None and manual:
        incoming_state = expected_state
    if incoming_state != expected_state:
        raise AuthError("Authorization failed: state mismatch (possible CSRF).", code="state_mismatch")
    code = str(callback.get("code") or "").strip()
    if not code:
        raise AuthError("Authorization failed: no code returned.", code="code_missing")
    return code


def _verify_nonce(token_block: Mapping[str, Any], *, expected_nonce: str) -> None:
    """Reject a replayed id_token whose nonce doesn't match what we sent (OIDC §3.1.3.7).

    If the id_token carries no nonce claim, there is nothing to bind against — the
    access token is still PKCE-bound — so we don't fail the login.
    """
    claims = tokens.decode_jwt_claims(str(token_block.get("id_token") or ""))
    actual = claims.get("nonce")
    if actual and actual != expected_nonce:
        raise AuthError("Authorization failed: id_token nonce mismatch (possible replay).", code="oidc_nonce_mismatch")


def _account_from_tokens(token_block: Mapping[str, Any]) -> Dict[str, Any]:
    claims = tokens.decode_jwt_claims(str(token_block.get("id_token") or ""))
    if not claims:
        claims = tokens.decode_jwt_claims(str(token_block.get("access_token") or ""))
    return {
        "email": claims.get("email", ""),
        "user_id": claims.get("sub", ""),
        "name": claims.get("name", ""),
    }


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def do_logout(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Remove stored credentials."""
    removed = store.clear(env)
    return {"status": "ok", "removed": removed}


def do_status(settings: Settings, *, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Report the current login state without performing a network refresh."""
    state = store.load(env)
    if state is None:
        return {"logged_in": False, "home": str(settings.home)}
    token_block = state.get("tokens") or {}
    access = str(token_block.get("access_token") or "")
    exp = tokens.access_token_expiry(access)
    expiring = tokens.is_expiring(state)
    result: Dict[str, Any] = {
        "logged_in": True,
        "home": str(settings.home),
        "provider": state.get("provider"),
        "base_url": state.get("base_url"),
        "account": state.get("account", {}),
        "expiring": expiring,
        "last_refresh": state.get("last_refresh"),
    }
    if exp is not None:
        result["expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))
        result["expires_in_seconds"] = max(0, int(exp - time.time()))
    if state.get("last_auth_error"):
        result["last_auth_error"] = state["last_auth_error"]
    return result

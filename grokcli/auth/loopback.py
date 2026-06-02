"""Local OAuth callback: loopback HTTP listener, manual paste, browser launch.

After the user approves access, xAI redirects the browser to
``http://127.0.0.1:<port>/callback?code=...&state=...``. We run a tiny HTTP
server to capture that, with the quirks real xAI logins require:

* CORS headers for ``accounts.x.ai`` / ``auth.x.ai`` (the consent page issues a
  cross-origin request to the loopback) plus an OPTIONS preflight handler.
* Port fallback: if 56121 is taken, bind an OS-assigned port and reflect it in
  the redirect URI (which is then sent in both the authorize and token steps).
* A ``--manual-paste`` path for headless/remote consoles where the browser
  cannot reach the loopback.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from ..errors import AuthError
from . import oauth

_CORS_ORIGINS = frozenset({"https://accounts.x.ai", "https://auth.x.ai"})
_CONSOLE_BROWSERS = frozenset({"w3m", "lynx", "links", "links2", "elinks", "www-browser", "browsh"})

CallbackResult = Dict[str, Optional[str]]


def _make_handler(expected_path: str, result: CallbackResult, lock: threading.Lock):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # silence access log
            return

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in _CORS_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self) -> None:  # noqa: N802 - http.server API
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            incoming = {
                "code": _first(params.get("code")),
                "state": _first(params.get("state")),
                "error": _first(params.get("error")),
                "error_description": _first(params.get("error_description")),
            }
            if incoming["code"] is None and incoming["error"] is None:
                self._respond(400, "No authorization code in callback. Re-run `grokcli login`.")
                return
            with lock:
                if not (result.get("code") or result.get("error")):
                    result.update(incoming)
            if incoming["error"]:
                self._respond(200, "Authorization failed. You can close this tab.")
            else:
                self._respond(200, "Authorization received. You can close this tab and return to the terminal.")

        def _respond(self, status: int, message: str) -> None:
            body = f"<html><body><h2>grokcli</h2><p>{message}</p></body></html>".encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


def _first(values: Optional[list]) -> Optional[str]:
    return values[0] if values else None


class CallbackServer:
    """A running loopback callback listener bound to ``redirect_uri``."""

    def __init__(self, preferred_port: int = oauth.REDIRECT_PORT) -> None:
        self.result: CallbackResult = {"code": None, "state": None, "error": None, "error_description": None}
        self._lock = threading.Lock()
        handler = _make_handler(oauth.REDIRECT_PATH, self.result, self._lock)
        self._server = self._bind(preferred_port, handler)
        host, port = self._server.server_address[0], self._server.server_address[1]
        self.redirect_uri = f"http://{host}:{port}{oauth.REDIRECT_PATH}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._thread.start()

    @staticmethod
    def _bind(preferred_port: int, handler) -> ThreadingHTTPServer:
        class _Server(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        last_error: Optional[OSError] = None
        for port in (preferred_port, 0):  # fall back to an OS-assigned port
            try:
                return _Server((oauth.REDIRECT_HOST, port), handler)
            except OSError as exc:
                last_error = exc
        raise AuthError(
            f"Could not bind the OAuth callback listener on {oauth.REDIRECT_HOST}: {last_error}",
            code="callback_bind_failed",
        )

    def wait(self, timeout_seconds: float) -> CallbackResult:
        """Block until a callback arrives or ``timeout_seconds`` elapse."""
        deadline = time.monotonic() + max(5.0, timeout_seconds)
        try:
            while time.monotonic() < deadline:
                if self.result.get("code") or self.result.get("error"):
                    return self.result
                time.sleep(0.1)
        finally:
            self.close()
        raise AuthError(
            "Timed out waiting for the browser to complete authorization.",
            code="callback_timeout",
        )

    def close(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
        self._thread.join(timeout=1.0)


def parse_pasted_callback(raw: str) -> CallbackResult:
    """Parse a pasted callback URL, ``?code=...`` fragment, or bare code value."""
    result: CallbackResult = {"code": None, "state": None, "error": None, "error_description": None}
    stripped = (raw or "").strip()
    if not stripped:
        return result
    if stripped.startswith(("http://", "https://")):
        query = urlparse(stripped).query
    elif stripped.startswith("?"):
        query = stripped[1:]
    elif "=" in stripped:
        query = stripped
    else:
        result["code"] = stripped  # bare opaque code, no state
        return result
    params = parse_qs(query)
    for key in ("code", "state", "error", "error_description"):
        result[key] = _first(params.get(key))
    return result


def prompt_manual_paste(redirect_uri: str) -> CallbackResult:
    """Prompt the user to paste the callback URL (headless/remote fallback)."""
    sys.stderr.write(
        "\n--- Manual callback paste ---\n"
        f"After approving, your browser will try to load {redirect_uri}\n"
        "(which fails on a remote machine — that's expected). Paste the FULL URL\n"
        "from the address bar, a bare '?code=...&state=...' fragment, or, if the\n"
        "consent page shows a code in-page, the bare code value.\n"
    )
    try:
        raw = input("Callback URL: ")
    except (EOFError, KeyboardInterrupt):
        raw = ""
    return parse_pasted_callback(raw)


def is_remote_session(env: Optional[Mapping[str, str]] = None) -> bool:
    """Detect SSH / browser-only cloud consoles where loopback can't be reached."""
    env = os.environ if env is None else env
    if env.get("SSH_CLIENT") or env.get("SSH_TTY"):
        return True
    return any(
        env.get(var)
        for var in ("CLOUD_SHELL", "CODESPACES", "CODESPACE_NAME", "GITPOD_WORKSPACE_ID", "REPL_ID", "STACKBLITZ")
    )


def can_open_browser(env: Optional[Mapping[str, str]] = None) -> bool:
    """True only when a real graphical browser is likely to open."""
    env = os.environ if env is None else env
    browser_env = env.get("BROWSER", "")
    if browser_env and _is_console_browser(browser_env):
        return False
    if sys.platform.startswith("linux") and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) and not browser_env:
        return False
    try:
        controller = webbrowser.get()
    except webbrowser.Error:
        return False
    name = getattr(controller, "name", "") or getattr(controller, "basename", "") or ""
    return not _is_console_browser(name)


def _is_console_browser(value: str) -> bool:
    token = value.strip().split()[0] if value.strip() else ""
    return os.path.basename(token).lower() in _CONSOLE_BROWSERS


def open_browser(url: str) -> bool:
    """Best-effort browser launch; returns whether it likely opened."""
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def validate_loopback_redirect(redirect_uri: str) -> Tuple[str, int]:
    """Confirm a redirect URI is http on 127.0.0.1 with an explicit port."""
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname != oauth.REDIRECT_HOST or not parsed.port:
        raise AuthError(
            "OAuth redirect URI must be http://127.0.0.1:<port>.",
            code="redirect_invalid",
        )
    return oauth.REDIRECT_HOST, int(parsed.port)

"""Authenticated xAI API client: bearer injection + reactive refresh on 401.

Sits above :class:`grokcli.transport.HttpClient` and the auth token resolver.
Every call resolves a (proactively refreshed) access token, attaches it as a
Bearer header against the configured base URL, and — if the server still answers
401 (e.g. an opaque token revoked mid-window) — forces one refresh and retries.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Mapping, Optional

from .config import Settings
from .errors import AuthError
from .transport import HttpClient, Response
from .auth import tokens


class GrokClient:
    """High-level client for the xAI REST API, bound to one :class:`Settings`."""

    def __init__(self, settings: Settings, *, env: Optional[Mapping[str, str]] = None) -> None:
        self.settings = settings
        self.env = env
        self.http = HttpClient(
            timeout=settings.timeout, proxy=settings.proxy, verbose=settings.verbose
        )
        self.account: Dict[str, Any] = {}

    # -- auth ---------------------------------------------------------------

    def _auth_headers(self, *, force_refresh: bool = False) -> Dict[str, str]:
        creds = tokens.resolve_runtime_credentials(
            env=self.env, force_refresh=force_refresh, settings=self.settings
        )
        self.account = creds.get("account") or {}
        return {"Authorization": f"{creds['token_type']} {creds['access_token']}"}

    def _url(self, path: str) -> str:
        # Absolute URLs pass through for hardcoded service constants (e.g. the
        # billing proxy) — never user input, so the base_url pin stays intact.
        if path.startswith(("http://", "https://")):
            return path
        return self.settings.base_url.rstrip("/") + "/" + path.lstrip("/")

    # -- requests -----------------------------------------------------------

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """JSON request with one reactive refresh+retry on a 401."""
        return self._with_refresh_retry(
            lambda h: self.http.request_json(
                method, self._url(path), json_body=json_body, headers=h, timeout=timeout
            ),
            headers,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Response:
        """Raw request returning the :class:`Response` (for binary payloads)."""
        return self._with_refresh_retry(
            lambda h: self.http.request(
                method, self._url(path), body=body, headers=h, timeout=timeout
            ),
            headers,
        )

    def stream(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[Dict[str, str]]:
        """SSE stream; refreshes and reopens once if the initial open returns 401."""
        merged = {**self._auth_headers(), **dict(headers or {})}
        try:
            yield from self.http.stream_sse(
                method, self._url(path), json_body=json_body, headers=merged, timeout=timeout
            )
        except AuthError as exc:
            if exc.status_code != 401:
                raise
            merged = {**self._auth_headers(force_refresh=True), **dict(headers or {})}
            yield from self.http.stream_sse(
                method, self._url(path), json_body=json_body, headers=merged, timeout=timeout
            )

    def download(self, url: str, dest: Any, *, progress: Optional[Any] = None, timeout: Optional[float] = None) -> Any:
        """Download a (typically pre-signed, unauthenticated) result URL to disk."""
        return self.http.download(url, dest, progress=progress, timeout=timeout)

    def _with_refresh_retry(self, call, headers: Optional[Mapping[str, str]]):
        merged = {**self._auth_headers(), **dict(headers or {})}
        try:
            return call(merged)
        except AuthError as exc:
            if exc.status_code != 401:
                raise
            merged = {**self._auth_headers(force_refresh=True), **dict(headers or {})}
            return call(merged)

"""Standard-library HTTP transport for the xAI REST API.

Built on ``urllib.request`` — no third-party HTTP library. Provides JSON
requests, Server-Sent-Events streaming, and file downloads, with retry/backoff
on transient failures and a single mapping from HTTP status to :mod:`grokcli.errors`.

This layer is auth-agnostic: callers pass an ``Authorization`` header. The
refresh-on-401 retry lives one level up in :mod:`grokcli.client`.
"""

from __future__ import annotations

import gzip
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping, Optional
from urllib.parse import urlparse

from . import __version__
from .errors import (
    APIError,
    AuthError,
    ContentFilterError,
    GrokError,
    NetworkError,
    QuotaError,
    RequestTimeoutError,
    TierDeniedError,
)

DEFAULT_USER_AGENT = f"grokcli/{__version__}"
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
# Only methods with no side effects are retried — a 5xx after a POST means the
# server may have already acted, so replaying it could duplicate an image/video job.
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
# Hard cap on a buffered (non-streamed) response body, to bound memory against a
# malformed or hostile server. Large media is downloaded via stream, not buffered.
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_ERROR_BYTES = 64 * 1024
_QUOTA_KEYWORDS = ("quota", "usage limit", "rate limit", "too many requests")
_BILLING_KEYWORDS = ("billing", "balance", "credits", "spend cap", "payment")


class _StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Drop the Authorization header when a redirect crosses to a different host.

    urllib's default redirect handler copies all request headers (including
    ``Authorization``) to the redirect target. If an xAI endpoint ever 3xx-ed to
    a foreign host, the OAuth bearer would be leaked. We strip it on host change.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            new_req.remove_header("Authorization")
        return new_req


@dataclass
class Response:
    """A completed (non-streaming) HTTP response."""

    status: int
    headers: Dict[str, str]
    body: bytes

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except ValueError as exc:
            raise APIError(
                f"xAI returned a non-JSON response: {exc}",
                status_code=self.status,
                code="invalid_json",
            ) from exc


class HttpClient:
    """Thin urllib-based HTTP client with retries and typed error mapping."""

    def __init__(
        self,
        *,
        timeout: float = 300.0,
        proxy: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 2,
        verbose: bool = False,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.verbose = verbose
        handlers: list = [_StripAuthOnCrossHostRedirect()]
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        else:
            handlers.append(urllib.request.ProxyHandler())  # honor *_PROXY env vars
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._opener = urllib.request.build_opener(*handlers)

    # -- public API ---------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[bytes] = None,
        timeout: Optional[float] = None,
    ) -> Response:
        """Perform a request, retrying transient failures, return the Response."""
        req = self._build_request(method, url, headers, body)
        deadline_timeout = self.timeout if timeout is None else timeout
        idempotent = method.upper() in _IDEMPOTENT_METHODS
        last_exc: Optional[GrokError] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._opener.open(req, timeout=deadline_timeout)
                return self._read_response(raw)
            except urllib.error.HTTPError as exc:
                status = exc.code
                exc_headers = dict(exc.headers or {})
                payload = self._safe_read(exc)
                if status in _RETRYABLE_STATUS and idempotent and attempt < self.max_retries:
                    last_exc = self._map_status(status, payload, exc_headers)
                    self._backoff(attempt, exc_headers)
                    continue
                raise self._map_status(status, payload, exc_headers)
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                mapped = self._map_transport(exc)
                # Retry transport failures only for idempotent methods: a POST may
                # have reached the server before the connection dropped.
                if idempotent and attempt < self.max_retries:
                    last_exc = mapped
                    self._backoff(attempt)
                    continue
                raise mapped
        # Loop exhausted on a retryable status/transport error.
        raise last_exc or NetworkError("Request failed after retries.")

    def request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """POST/GET JSON and parse the JSON response."""
        merged = dict(headers or {})
        body: Optional[bytes] = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            merged.setdefault("Content-Type", "application/json")
        return self.request(method, url, headers=merged, body=body, timeout=timeout).json()

    def stream_sse(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[Dict[str, str]]:
        """Open an SSE stream and yield ``{"event", "data"}`` dicts per event.

        No retry: a stream cannot be safely resumed mid-flight.
        """
        # identity encoding: the SSE parser reads the raw byte stream and cannot
        # transparently inflate gzip mid-stream.
        merged = {"Accept": "text/event-stream", "Accept-Encoding": "identity", **dict(headers or {})}
        body: Optional[bytes] = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            merged.setdefault("Content-Type", "application/json")
        req = self._build_request(method, url, merged, body)
        try:
            raw = self._opener.open(req, timeout=self.timeout if timeout is None else timeout)
        except urllib.error.HTTPError as exc:
            raise self._map_status(exc.code, self._safe_read(exc), dict(exc.headers or {}))
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise self._map_transport(exc)
        with raw:
            yield from _iter_sse(raw)

    def download(
        self,
        url: str,
        dest: Any,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        progress: Optional[Any] = None,
    ) -> Any:
        """Stream ``url`` to ``dest`` atomically (tmp file + rename)."""
        import os
        import uuid
        from pathlib import Path

        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        req = self._build_request("GET", url, headers, None)
        try:
            raw = self._opener.open(req, timeout=self.timeout if timeout is None else timeout)
        except urllib.error.HTTPError as exc:
            raise self._map_status(exc.code, self._safe_read(exc), dict(exc.headers or {}))
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise self._map_transport(exc)
        total = int(raw.headers.get("Content-Length") or 0)
        tmp = dest_path.with_name(f"{dest_path.name}.part.{os.getpid()}.{uuid.uuid4().hex}")
        downloaded = 0
        try:
            with raw, open(tmp, "wb") as out:
                while True:
                    chunk = raw.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)
            os.replace(tmp, dest_path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return dest_path

    # -- internals ----------------------------------------------------------

    def _build_request(
        self,
        method: str,
        url: str,
        headers: Optional[Mapping[str, str]],
        body: Optional[bytes],
    ) -> urllib.request.Request:
        final_headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        final_headers.update({k: v for k, v in (headers or {}).items() if v is not None})
        if self.verbose:
            import sys

            sys.stderr.write(f"> {method} {url}\n> Authorization: {_mask_auth(final_headers.get('Authorization'))}\n")
        return urllib.request.Request(url, data=body, headers=final_headers, method=method.upper())

    def _read_response(self, raw: Any) -> Response:
        with raw:
            data = raw.read(_MAX_RESPONSE_BYTES + 1)
        if len(data) > _MAX_RESPONSE_BYTES:
            raise APIError(f"Response exceeded {_MAX_RESPONSE_BYTES} bytes; refusing to buffer.", code="response_too_large")
        headers = {k: v for k, v in raw.headers.items()}
        if (headers.get("Content-Encoding") or "").lower() == "gzip":
            data = gzip.decompress(data)
        if self.verbose:
            import sys

            sys.stderr.write(f"< {raw.status} ({len(data)} bytes)\n")
        return Response(status=raw.status, headers=headers, body=data)

    @staticmethod
    def _safe_read(exc: urllib.error.HTTPError) -> bytes:
        try:
            data = exc.read(_MAX_ERROR_BYTES)
        except Exception:  # pragma: no cover - defensive
            return b""
        if (exc.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                return gzip.decompress(data)
            except OSError:
                return data
        return data

    def _backoff(self, attempt: int, headers: Optional[Mapping[str, str]] = None) -> None:
        if headers:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    time.sleep(min(30.0, max(0.1, float(retry_after))))
                    return
                except ValueError:
                    pass
        time.sleep(0.3 * (2 ** attempt))

    def _map_status(self, status: int, body: bytes, headers: Mapping[str, str]) -> GrokError:
        message = _extract_api_message(body) or f"HTTP {status}"
        lowered = message.lower()
        if status == 401:
            return AuthError(
                f"Authentication failed (HTTP 401): {message}",
                code="unauthorized",
                status_code=401,
                relogin_required=True,
                hint="Run `grokcli login` to re-authenticate.",
            )
        if status == 403:
            return self._classify_403(message, lowered)
        if status == 429:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            wait_hint = f" Retry after {retry_after}s." if retry_after else ""
            return QuotaError(
                f"Rate limited (HTTP 429): {message}",
                code="rate_limited",
                status_code=429,
                hint=f"You hit a rate or usage limit.{wait_hint} Check your plan if it persists.",
            )
        if status in (400, 422) and any(k in lowered for k in ("content policy", "moderation", "safety", "blocked")):
            return ContentFilterError(
                f"Content blocked (HTTP {status}): {message}", status_code=status, code="content_filter"
            )
        return APIError(f"xAI API error (HTTP {status}): {message}", status_code=status)

    @staticmethod
    def _classify_403(message: str, lowered: str) -> GrokError:
        if any(k in lowered for k in _QUOTA_KEYWORDS):
            return QuotaError(f"Quota exceeded (HTTP 403): {message}", status_code=403, code="quota")
        if any(k in lowered for k in _BILLING_KEYWORDS):
            return QuotaError(
                f"Billing problem (HTTP 403): {message}",
                status_code=403,
                code="billing",
                hint="Resolve billing/credits at https://x.ai/grok.",
            )
        return TierDeniedError(f"Access denied (HTTP 403): {message}", status_code=403)

    @staticmethod
    def _map_transport(exc: Exception) -> GrokError:
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return RequestTimeoutError("Request timed out.", code="timeout")
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return RequestTimeoutError("Request timed out.", code="timeout")
        if isinstance(reason, ssl.SSLError):
            return NetworkError(f"TLS error: {reason}", code="tls_error")
        return NetworkError(
            f"Could not reach xAI: {reason}",
            code="network",
            hint="Check your internet connection or proxy settings.",
        )


def _mask_auth(auth: Optional[str]) -> str:
    """Redact a bearer for verbose logs, exposing at most 4 token chars."""
    if not auth:
        return "(none)"
    if auth.startswith("Bearer "):
        token = auth[7:]
        return f"Bearer {token[:4]}…({len(token)} chars)" if len(token) > 8 else "Bearer [REDACTED]"
    return "[REDACTED]"


def _extract_api_message(body: bytes) -> str:
    """Pull a human message from an OpenAI-style error body, else the raw text."""
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text[:500]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or text)[:500]
        if isinstance(err, str):
            return err[:500]
        if "message" in data:
            return str(data["message"])[:500]
    return text[:500]


def _iter_sse(raw: Any) -> Iterator[Dict[str, str]]:
    """Parse a Server-Sent-Events byte stream into event dicts.

    Accumulates ``event:``/``data:`` field lines until a blank line, then yields
    ``{"event": <type or "">, "data": <joined data lines>}``. Stops at ``[DONE]``.
    """
    event_type = ""
    data_lines = []
    for raw_line in raw:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                data = "\n".join(data_lines)
                if data.strip() == "[DONE]":
                    return
                yield {"event": event_type, "data": data}
            event_type = ""
            data_lines = []
            continue
        if line.startswith(":"):  # SSE comment / heartbeat
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:  # flush a final event with no trailing blank line
        data = "\n".join(data_lines)
        if data.strip() != "[DONE]":
            yield {"event": event_type, "data": data}

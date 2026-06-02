"""Error taxonomy and exit-code contract for grokcli.

Every user-facing failure is raised as a :class:`GrokError` (or subclass) that
carries an :class:`ExitCode` and an optional actionable ``hint``. The CLI's
top-level handler (:func:`grokcli.cli.main`) catches these, renders them to
stderr (text) or stdout (json), and exits with the carried code.

Design borrowed from established CLIs (MiniMax `cli`, Moore `grok-cli`):
status/progress/errors go to stderr; only results go to stdout.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional


class ExitCode(IntEnum):
    """Process exit codes. Stable contract for scripting against grokcli."""

    OK = 0
    GENERAL = 1
    USAGE = 2          # bad arguments / invalid invocation
    AUTH = 3           # not logged in, token invalid, tier/entitlement denied
    QUOTA = 4          # rate limit / quota / billing
    TIMEOUT = 5        # request or polling deadline exceeded
    NETWORK = 6        # connection refused, DNS failure, TLS error
    CONTENT_FILTER = 10  # prompt/response blocked by moderation
    INTERRUPT = 130    # SIGINT (Ctrl-C)


class GrokError(Exception):
    """Base class for every expected, user-facing error.

    Attributes:
        message: Human-readable description (no trailing newline).
        exit_code: Process exit code to use.
        hint: Optional next-step suggestion shown indented below the error.
        code: Optional machine-readable error code (e.g. ``xai_token_expired``).
        relogin_required: True when the fix is to re-run ``grokcli login``.
        entitlement_denied: True when the account lacks the required tier
            (a 403 that re-login cannot fix).
        status_code: Originating HTTP status, when applicable.
    """

    exit_code: ExitCode = ExitCode.GENERAL

    def __init__(
        self,
        message: str,
        *,
        exit_code: Optional[ExitCode] = None,
        hint: Optional[str] = None,
        code: Optional[str] = None,
        relogin_required: bool = False,
        entitlement_denied: bool = False,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code
        self.hint = hint
        self.code = code
        self.relogin_required = relogin_required
        self.entitlement_denied = entitlement_denied
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for ``--output json`` error rendering."""
        payload: Dict[str, Any] = {
            "code": int(self.exit_code),
            "message": self.message,
        }
        if self.code:
            payload["error_code"] = self.code
        if self.hint:
            payload["hint"] = self.hint
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.relogin_required:
            payload["relogin_required"] = True
        if self.entitlement_denied:
            payload["entitlement_denied"] = True
        return payload


class UsageError(GrokError):
    """Invalid CLI invocation (missing required flag, bad value)."""

    exit_code = ExitCode.USAGE


class AuthError(GrokError):
    """Not authenticated, or stored credentials are invalid/expired."""

    exit_code = ExitCode.AUTH


class TierDeniedError(AuthError):
    """A 403 caused by subscription tier/entitlement, not a stale token.

    Re-login does not help; the user must upgrade their xAI subscription.
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "xai_oauth_tier_denied")
        kwargs.setdefault(
            "hint",
            "Your account is not entitled to this xAI API surface. "
            "Re-login will not help; upgrade at https://x.ai/grok.",
        )
        kwargs["entitlement_denied"] = True
        kwargs["relogin_required"] = False
        super().__init__(message, **kwargs)


class QuotaError(GrokError):
    """Rate limit, quota exhaustion, or billing problem."""

    exit_code = ExitCode.QUOTA


class RequestTimeoutError(GrokError):
    """A request or polling loop exceeded its deadline.

    Named to avoid shadowing the builtin ``TimeoutError`` raised by sockets.
    """

    exit_code = ExitCode.TIMEOUT


class NetworkError(GrokError):
    """Transport failure: connection refused, DNS failure, TLS error."""

    exit_code = ExitCode.NETWORK


class ContentFilterError(GrokError):
    """The prompt or generated content was blocked by moderation."""

    exit_code = ExitCode.CONTENT_FILTER


class APIError(GrokError):
    """A non-2xx HTTP response that does not map to a more specific class."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(message, status_code=status_code, **kwargs)

"""``grokcli doctor`` — diagnose auth, connectivity, and entitlement end to end.

Runs a sequence of checks, each producing a :class:`Check`, and never aborts on
a single failure: it gathers every result so the user sees the full picture. The
process exit code reflects the most severe failure (auth > network > general).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import List, Mapping, Optional

from . import output
from .client import GrokClient
from .config import Settings
from .errors import AuthError, ExitCode, GrokError, NetworkError, TierDeniedError
from .transport import HttpClient
from .auth import oauth, store, tokens

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Check:
    name: str
    level: str  # OK | WARN | FAIL
    detail: str = ""
    hint: str = ""
    exit_code: Optional[ExitCode] = None

    def to_dict(self) -> dict:
        out = {"name": self.name, "level": self.level, "detail": self.detail}
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass
class DoctorReport:
    checks: List[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.level != FAIL for c in self.checks)

    def exit_code(self) -> ExitCode:
        for check in self.checks:
            if check.level == FAIL:
                return check.exit_code or ExitCode.GENERAL
        return ExitCode.OK

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": [c.to_dict() for c in self.checks]}


def run_doctor(
    settings: Settings,
    *,
    env: Optional[Mapping[str, str]] = None,
    online: bool = True,
    network_client: Optional[HttpClient] = None,
    api_client: Optional[GrokClient] = None,
) -> DoctorReport:
    """Run all health checks and return a :class:`DoctorReport`."""
    report = DoctorReport()
    report.checks.append(_check_python())
    report.checks.append(_check_home(settings))

    state = store.load(env)
    cred_check = _check_credentials(state)
    report.checks.append(cred_check)
    if state is None:
        return report  # nothing downstream can pass without credentials

    report.checks.append(_check_token(state))

    if not online:
        return report

    report.checks.append(_check_network(network_client or HttpClient(timeout=15.0, proxy=settings.proxy)))
    refresh_check = _check_refresh(settings, env)
    report.checks.append(refresh_check)
    if refresh_check.level == FAIL:
        return report  # an unusable token makes the API ping pointless
    report.checks.append(_check_api(api_client or GrokClient(settings, env=env)))
    return report


def _check_python() -> Check:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 9):
        return Check("Python version", FAIL, f"{version} (need >= 3.9)", exit_code=ExitCode.GENERAL)
    return Check("Python version", OK, version)


def _check_home(settings: Settings) -> Check:
    home = settings.home
    if not home.exists():
        return Check("Config home", WARN, f"{home} (created on first login)")
    return Check("Config home", OK, str(home))


def _check_credentials(state: Optional[Mapping]) -> Check:
    if state is None:
        return Check(
            "Credentials",
            FAIL,
            "not logged in",
            hint="Run `grokcli login` to authenticate with your SuperGrok / X Premium+ subscription.",
            exit_code=ExitCode.AUTH,
        )
    account = state.get("account") or {}
    who = account.get("email") or account.get("user_id") or "stored"
    return Check("Credentials", OK, f"present ({who})")


def _check_token(state: Mapping) -> Check:
    access = str((state.get("tokens") or {}).get("access_token") or "")
    exp = tokens.access_token_expiry(access)
    if exp is None:
        return Check("Access token", OK, "opaque token (expiry checked on use)")
    remaining = int(exp - time.time())
    when = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(exp))
    if remaining <= 0:
        return Check("Access token", WARN, f"expired {when} (will refresh on next call)")
    if tokens.is_expiring(state):
        return Check("Access token", WARN, f"expiring soon ({when}); a refresh is due")
    return Check("Access token", OK, f"valid until {when} ({remaining // 60} min)")


def _check_network(client: HttpClient) -> Check:
    try:
        client.request_json("GET", oauth.DISCOVERY_URL)
        return Check("Network (auth.x.ai)", OK, "reachable")
    except NetworkError as exc:
        return Check("Network (auth.x.ai)", FAIL, exc.message, hint=exc.hint or "", exit_code=ExitCode.NETWORK)
    except GrokError as exc:
        return Check("Network (auth.x.ai)", WARN, f"unexpected response: {exc.message}")


def _check_refresh(settings: Settings, env: Optional[Mapping[str, str]]) -> Check:
    try:
        tokens.resolve_runtime_credentials(env=env, settings=settings)
        return Check("Token refresh", OK, "valid access token available")
    except TierDeniedError as exc:
        return Check("Token refresh", FAIL, exc.message, hint=exc.hint or "", exit_code=ExitCode.AUTH)
    except AuthError as exc:
        hint = exc.hint or ("Run `grokcli login` again." if exc.relogin_required else "")
        return Check("Token refresh", FAIL, exc.message, hint=hint, exit_code=ExitCode.AUTH)


def _check_api(client: GrokClient) -> Check:
    try:
        data = client.request_json("GET", "/models")
        count = _count_models(data)
        return Check("API (/v1/models)", OK, f"authorized{f'; {count} models' if count else ''}")
    except TierDeniedError as exc:
        return Check("API (/v1/models)", FAIL, exc.message, hint=exc.hint or "", exit_code=ExitCode.AUTH)
    except GrokError as exc:
        return Check("API (/v1/models)", FAIL, exc.message, hint=exc.hint or "", exit_code=exc.exit_code)


def _count_models(data) -> int:
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return len(data["data"])
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return len(data["models"])
    return 0


def render_report(report: DoctorReport, settings: Settings) -> None:
    """Print the report: JSON to stdout, or a symboled checklist to stdout."""
    if settings.output_format == "json":
        output.print_json(report.to_dict())
        return
    style = output.Style(settings.color)
    symbols = {
        OK: style.green("✓"),
        WARN: style.yellow("⚠"),
        FAIL: style.red("✗"),
    }
    output.stdout(style.bold("grokcli doctor"))
    for check in report.checks:
        symbol = symbols.get(check.level, "?")
        output.stdout(f"  {symbol} {check.name}: {check.detail}")
        if check.hint:
            output.stdout(f"      {style.dim('→ ' + check.hint)}")
    summary = style.green("All checks passed.") if report.ok else style.red("Some checks failed.")
    output.stdout("\n" + summary)

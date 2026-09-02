"""Subscription quota: usage period and credits via the Grok CLI billing proxy.

The xAI REST API exposes no usage endpoint for OAuth subscription access
(``GET /v1/usage`` answers 404); the quota surface is the proxy the official
``grok`` CLI itself talks to (verified live 2026-09, mirrored from the local
quota-watch integration):

    GET https://cli-chat-proxy.grok.com/v1/billing?format=credits

Auth is the same Bearer token as every other call, plus a client-version gate
and — when the login stored it — ``x-userid`` routing metadata (some account
states 403 without it). The response's ``config`` carries two shapes: the
current unified-credits view (``currentPeriod`` + ``creditUsagePercent``,
weekly for SuperGrok) and the legacy absolute-credits fallback
(``monthlyLimit``/``used``). A 403 here is entitlement/routing denial, so the
client's reactive refresh-retry correctly stays cold.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from . import output
from .auth import store
from .client import GrokClient
from .config import Settings
from .errors import APIError

BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
# Mirrors the official grok CLI's version gate; bump alongside it.
CLIENT_VERSION = "0.2.118"

_PERIOD_TYPES = {
    "USAGE_PERIOD_TYPE_WEEKLY": "weekly",
    "USAGE_PERIOD_TYPE_MONTHLY": "monthly",
    "USAGE_PERIOD_TYPE_DAILY": "daily",
}


def fetch_billing(client: GrokClient, *, user_id: str = "") -> Dict[str, Any]:
    """GET the billing endpoint and return its ``config`` object."""
    headers = {"x-grok-client-version": CLIENT_VERSION}
    if user_id:
        headers["x-userid"] = user_id
    data = client.request_json("GET", BILLING_URL, headers=headers)
    config = data.get("config") if isinstance(data, dict) else None
    if not isinstance(config, dict):
        raise APIError("Unexpected billing response: no config object.")
    return config


def normalize(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Flatten a billing ``config`` into a stable summary dict.

    Credits shape first; legacy ``monthlyLimit``/``used`` only when the credits
    fields are absent (same response, judged field-by-field like quota-watch).
    """
    period = config.get("currentPeriod")
    period = period if isinstance(period, dict) else {}
    used_pct = config.get("creditUsagePercent")
    if isinstance(period.get("type"), str) and isinstance(used_pct, (int, float)):
        used = max(0.0, min(100.0, float(used_pct)))
        return {
            "source": "credits",
            "period": {
                "type": _PERIOD_TYPES.get(period["type"], "unknown"),
                "start": period.get("start"),
                "end": period.get("end"),
            },
            "used_percent": round(used, 1),
            "remaining_percent": round(100.0 - used, 1),
            "resets_at": period.get("end"),
            "products": _products(config.get("productUsage")),
        }
    limit = _num((config.get("monthlyLimit") or {}).get("val")) if isinstance(config.get("monthlyLimit"), dict) else None
    used_credits = _num((config.get("used") or {}).get("val")) if isinstance(config.get("used"), dict) else None
    if limit is not None or used_credits is not None:
        limit = limit or 0.0
        used_credits = used_credits or 0.0
        # total >= used keeps remaining truthful: over-limit reads 0 left, and
        # limit 0 is "blocked" upstream (403 spending-limit), not unlimited.
        total = max(limit, used_credits)
        return {
            "source": "legacy",
            "period": {"type": "monthly", "start": None, "end": config.get("billingPeriodEnd")},
            "used": used_credits,
            "limit": limit,
            "remaining": round(total - used_credits, 1),
            "used_percent": round(100.0 * used_credits / total, 1) if total > 0 else None,
            "remaining_percent": round(100.0 * (total - used_credits) / total, 1) if total > 0 else 0.0,
            "resets_at": config.get("billingPeriodEnd"),
            "products": [],
        }
    raise APIError("Unexpected billing response: no recognizable usage fields.")


def _products(raw: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, dict) and item.get("product"):
            items.append({"name": str(item["product"]), "used_percent": _num(item.get("usagePercent"))})
    return items


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt_time(iso: Any) -> str:
    if not isinstance(iso, str) or not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return iso
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _format_text(summary: Mapping[str, Any]) -> str:
    if summary["source"] == "credits":
        label = {"weekly": "Weekly", "monthly": "Monthly", "daily": "Daily"}.get(
            summary["period"]["type"], "Current-period"
        )
        head = f"{label} quota: {summary['used_percent']:g}% used ({summary['remaining_percent']:g}% left)"
        reset = _fmt_time(summary.get("resets_at"))
        if reset:
            head += f" · resets {reset}"
        lines = [head]
        for product in summary.get("products") or []:
            pct = product.get("used_percent")
            suffix = f"  {pct:g}% used" if pct is not None else ""
            lines.append(f"  {product['name']}{suffix}")
        return "\n".join(lines)
    used_pct = summary.get("used_percent")
    head = "Monthly credits: "
    head += f"{used_pct:g}% used ({summary['remaining_percent']:g}% left) · " if used_pct is not None else ""
    head += f"{summary['used']:g} / {summary['limit']:g} credits used"
    reset = _fmt_time(summary.get("resets_at"))
    if reset:
        head += f" · resets {reset}"
    return head


def run_quota(settings: Settings, *, env: Optional[Mapping[str, str]] = None) -> int:
    """Fetch and print the subscription quota summary; returns the exit code."""
    state = store.load(env)
    user_id = str(((state or {}).get("account") or {}).get("user_id") or "").strip()
    client = GrokClient(settings, env=env)
    summary = normalize(fetch_billing(client, user_id=user_id))
    style = output.Style(settings.color)
    output.emit_result(settings.output_format, summary, style.bold(_format_text(summary)))
    return 0

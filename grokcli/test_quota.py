"""Tests for the subscription quota command (billing proxy readout)."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from grokcli import quota
from grokcli.client import GrokClient
from grokcli.config import resolve_settings
from grokcli.errors import APIError

_CREDITS_PAYLOAD = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-08-25T19:32:00Z",
            "end": "2026-09-01T19:32:00Z",
        },
        "creditUsagePercent": 42.5,
        "productUsage": [
            {"product": "GrokBuild", "usagePercent": 99.0},
            {"product": "GrokChat", "usagePercent": 1.0},
        ],
    }
}

_LEGACY_PAYLOAD = {
    "config": {"monthlyLimit": {"val": 100}, "used": {"val": 30}, "billingPeriodEnd": "2026-09-30T00:00:00Z"}
}


def _client():
    settings = resolve_settings({"no_color": True, "output_format": "text"}, env={}, file_cfg={})
    return GrokClient(settings, env={})


class FetchBillingTest(unittest.TestCase):
    def test_sends_version_gate_and_userid(self):
        client = _client()
        client.request_json = mock.Mock(return_value=_CREDITS_PAYLOAD)
        quota.fetch_billing(client, user_id="uid-123")
        _, kwargs = client.request_json.call_args
        self.assertEqual(kwargs["headers"]["x-grok-client-version"], quota.CLIENT_VERSION)
        self.assertEqual(kwargs["headers"]["x-userid"], "uid-123")
        self.assertEqual(client.request_json.call_args.args[:2], ("GET", quota.BILLING_URL))

    def test_userid_header_omitted_when_unknown(self):
        client = _client()
        client.request_json = mock.Mock(return_value=_CREDITS_PAYLOAD)
        quota.fetch_billing(client)
        headers = client.request_json.call_args.kwargs["headers"]
        self.assertNotIn("x-userid", headers)

    def test_missing_config_object_is_api_error(self):
        client = _client()
        client.request_json = mock.Mock(return_value={"unrelated": True})
        with self.assertRaises(APIError):
            quota.fetch_billing(client)


class NormalizeTest(unittest.TestCase):
    def test_credits_shape(self):
        summary = quota.normalize(_CREDITS_PAYLOAD["config"])
        self.assertEqual(summary["source"], "credits")
        self.assertEqual(summary["period"]["type"], "weekly")
        self.assertEqual(summary["used_percent"], 42.5)
        self.assertEqual(summary["remaining_percent"], 57.5)
        self.assertEqual(summary["resets_at"], "2026-09-01T19:32:00Z")
        self.assertEqual([p["name"] for p in summary["products"]], ["GrokBuild", "GrokChat"])

    def test_credits_shape_clamps_and_maps_unknown_period(self):
        summary = quota.normalize({"currentPeriod": {"type": "SOMETHING_NEW", "end": ""}, "creditUsagePercent": 140.0})
        self.assertEqual(summary["period"]["type"], "unknown")
        self.assertEqual(summary["used_percent"], 100.0)
        self.assertEqual(summary["remaining_percent"], 0.0)

    def test_malformed_product_entries_skipped(self):
        summary = quota.normalize(
            {"currentPeriod": {"type": "USAGE_PERIOD_TYPE_DAILY"}, "creditUsagePercent": 0.0,
             "productUsage": [{"product": "GrokChat", "usagePercent": 5}, {"nope": 1}, "junk"]}
        )
        self.assertEqual(summary["products"], [{"name": "GrokChat", "used_percent": 5.0}])

    def test_legacy_shape(self):
        summary = quota.normalize(_LEGACY_PAYLOAD["config"])
        self.assertEqual(summary["source"], "legacy")
        self.assertEqual((summary["used"], summary["limit"], summary["remaining"]), (30.0, 100.0, 70.0))
        self.assertEqual(summary["used_percent"], 30.0)
        self.assertEqual(summary["resets_at"], "2026-09-30T00:00:00Z")

    def test_legacy_over_limit_reads_exhausted(self):
        summary = quota.normalize({"monthlyLimit": {"val": 10}, "used": {"val": 30}})
        self.assertEqual(summary["remaining"], 0.0)
        self.assertEqual(summary["remaining_percent"], 0.0)

    def test_no_recognizable_fields_is_api_error(self):
        with self.assertRaises(APIError):
            quota.normalize({"config": {"somethingElse": 1}}["config"])


class RunQuotaTest(unittest.TestCase):
    def test_run_quota_prints_summary(self):
        client = _client()
        client.request_json = mock.Mock(return_value=_CREDITS_PAYLOAD)
        buf = io.StringIO()
        with mock.patch.object(quota, "GrokClient", return_value=client), \
                mock.patch.object(quota.store, "load", return_value={"account": {"user_id": "uid-9"}}), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(quota.run_quota(client.settings), 0)
        text = buf.getvalue()
        self.assertIn("Weekly quota", text)
        self.assertIn("42.5% used", text)
        self.assertIn("2026-09-01 19:32 UTC", text)

    def test_run_quota_json_mode(self):
        client = _client()
        client.request_json = mock.Mock(return_value=_LEGACY_PAYLOAD)
        buf = io.StringIO()
        settings = resolve_settings({"no_color": True, "output_format": "json"}, env={}, file_cfg={})
        with mock.patch.object(quota, "GrokClient", return_value=client), \
                mock.patch.object(quota.store, "load", return_value=None), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(quota.run_quota(settings), 0)
        self.assertIn('"source": "legacy"', buf.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""Tests for the error taxonomy and exit-code contract."""

from __future__ import annotations

import unittest

from grokcli import errors
from grokcli.errors import ExitCode


class ExitCodeTest(unittest.TestCase):
    def test_each_class_carries_expected_exit_code(self):
        cases = {
            errors.UsageError: ExitCode.USAGE,
            errors.AuthError: ExitCode.AUTH,
            errors.TierDeniedError: ExitCode.AUTH,
            errors.QuotaError: ExitCode.QUOTA,
            errors.RequestTimeoutError: ExitCode.TIMEOUT,
            errors.NetworkError: ExitCode.NETWORK,
            errors.ContentFilterError: ExitCode.CONTENT_FILTER,
            errors.APIError: ExitCode.GENERAL,
        }
        for cls, code in cases.items():
            self.assertEqual(cls("x").exit_code, code, cls.__name__)

    def test_base_error_defaults_to_general(self):
        self.assertEqual(errors.GrokError("boom").exit_code, ExitCode.GENERAL)


class ToDictTest(unittest.TestCase):
    def test_to_dict_includes_all_set_fields(self):
        err = errors.APIError("bad", status_code=418, hint="try tea", code="teapot")
        payload = err.to_dict()
        self.assertEqual(payload["code"], int(ExitCode.GENERAL))
        self.assertEqual(payload["message"], "bad")
        self.assertEqual(payload["status_code"], 418)
        self.assertEqual(payload["hint"], "try tea")
        self.assertEqual(payload["error_code"], "teapot")

    def test_tier_denied_sets_entitlement_and_no_relogin(self):
        err = errors.TierDeniedError("nope")
        payload = err.to_dict()
        self.assertTrue(payload["entitlement_denied"])
        self.assertNotIn("relogin_required", payload)
        self.assertEqual(err.code, "xai_oauth_tier_denied")
        self.assertFalse(err.relogin_required)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

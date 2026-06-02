"""Tests for the doctor health-check orchestration and severity → exit code."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from unittest import mock

from grokcli import doctor
from grokcli.config import resolve_settings
from grokcli.errors import ExitCode, TierDeniedError
from grokcli.auth import store


def make_jwt(claims: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(claims)}.sig"


class DoctorOfflineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}
        self.settings = resolve_settings({}, env=self.env, file_cfg={})

    def tearDown(self):
        self._tmp.cleanup()

    def _save(self, access):
        store.save(
            store.new_state(
                tokens={"access_token": access, "refresh_token": "r"},
                discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
                redirect_uri="http://127.0.0.1:56121/callback",
                base_url="https://api.x.ai/v1",
                account={"email": "me@x.ai"},
            ),
            self.env,
        )

    def test_not_logged_in_fails_with_auth_exit(self):
        report = doctor.run_doctor(self.settings, env=self.env, online=False)
        self.assertFalse(report.ok)
        self.assertEqual(report.exit_code(), ExitCode.AUTH)
        names = [c.name for c in report.checks]
        self.assertIn("Credentials", names)
        # Downstream checks are skipped when not logged in.
        self.assertNotIn("Access token", names)

    def test_logged_in_offline_passes(self):
        self._save(make_jwt({"exp": time.time() + 3600, "email": "me@x.ai"}))
        report = doctor.run_doctor(self.settings, env=self.env, online=False)
        self.assertTrue(report.ok)
        self.assertEqual(report.exit_code(), ExitCode.OK)

    def test_expiring_token_warns(self):
        self._save(make_jwt({"exp": time.time() + 30}))
        report = doctor.run_doctor(self.settings, env=self.env, online=False)
        token_check = next(c for c in report.checks if c.name == "Access token")
        self.assertEqual(token_check.level, doctor.WARN)
        self.assertTrue(report.ok)  # a warning is not a failure


class DoctorOnlineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}
        self.settings = resolve_settings({}, env=self.env, file_cfg={})
        store.save(
            store.new_state(
                tokens={"access_token": make_jwt({"exp": time.time() + 3600}), "refresh_token": "r"},
                discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
                redirect_uri="http://127.0.0.1:56121/callback",
                base_url="https://api.x.ai/v1",
            ),
            self.env,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_green_when_network_and_api_ok(self):
        net = mock.Mock()
        net.request_json.return_value = {"token_endpoint": "x"}
        api = mock.Mock()
        api.request_json.return_value = {"data": [{"id": "grok-4"}, {"id": "grok-3"}]}
        with mock.patch.object(doctor.tokens, "resolve_runtime_credentials", return_value={"access_token": "t"}):
            report = doctor.run_doctor(
                self.settings, env=self.env, online=True, network_client=net, api_client=api
            )
        self.assertTrue(report.ok)
        api_check = next(c for c in report.checks if c.name.startswith("API"))
        self.assertEqual(api_check.level, doctor.OK)
        self.assertIn("2 models", api_check.detail)

    def test_tier_denied_refresh_fails_and_skips_api(self):
        net = mock.Mock()
        net.request_json.return_value = {}
        api = mock.Mock()
        with mock.patch.object(
            doctor.tokens, "resolve_runtime_credentials", side_effect=TierDeniedError("no entitlement")
        ):
            report = doctor.run_doctor(
                self.settings, env=self.env, online=True, network_client=net, api_client=api
            )
        self.assertFalse(report.ok)
        self.assertEqual(report.exit_code(), ExitCode.AUTH)
        names = [c.name for c in report.checks]
        self.assertNotIn("API (/v1/models)", names)  # skipped after refresh failure
        api.request_json.assert_not_called()


class RenderReportTest(unittest.TestCase):
    def _report(self, ok):
        level = doctor.OK if ok else doctor.FAIL
        return doctor.DoctorReport(checks=[doctor.Check("Credentials", level, "detail", hint="fix it")])

    def test_json_render(self):
        import contextlib
        import io

        settings = resolve_settings({"output_format": "json"}, env={}, file_cfg={})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.render_report(self._report(False), settings)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"][0]["hint"], "fix it")

    def test_text_render_shows_fail_symbol(self):
        import contextlib
        import io

        settings = resolve_settings({"output_format": "text", "no_color": True}, env={}, file_cfg={})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.render_report(self._report(False), settings)
        out = buf.getvalue()
        self.assertIn("✗", out)
        self.assertIn("Some checks failed", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

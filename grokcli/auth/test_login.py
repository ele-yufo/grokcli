"""Tests for login/logout/status orchestration (network + browser mocked)."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import tempfile
import time
import unittest
from unittest import mock

from grokcli.config import resolve_settings
from grokcli.auth import login, oauth, store
from grokcli.errors import AuthError


def make_jwt(claims: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(claims)}.sig"


class ValidateCallbackTest(unittest.TestCase):
    def test_error_raises(self):
        with self.assertRaises(AuthError):
            login._validate_callback({"error": "access_denied"}, expected_state="s", manual=False)

    def test_state_mismatch_raises(self):
        with self.assertRaises(AuthError):
            login._validate_callback({"code": "c", "state": "other"}, expected_state="s", manual=False)

    def test_matching_state_returns_code(self):
        code = login._validate_callback({"code": "c", "state": "s"}, expected_state="s", manual=False)
        self.assertEqual(code, "c")

    def test_bare_code_accepted_in_manual_mode(self):
        code = login._validate_callback({"code": "c", "state": None}, expected_state="s", manual=True)
        self.assertEqual(code, "c")

    def test_missing_code_raises(self):
        with self.assertRaises(AuthError):
            login._validate_callback({"code": "", "state": "s"}, expected_state="s", manual=False)


class StatusLogoutTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}
        self.settings = resolve_settings({}, env=self.env, file_cfg={})

    def tearDown(self):
        self._tmp.cleanup()

    def test_status_when_logged_out(self):
        self.assertFalse(login.do_status(self.settings, env=self.env)["logged_in"])

    def test_status_when_logged_in(self):
        state = store.new_state(
            tokens={"access_token": make_jwt({"exp": time.time() + 3600, "email": "me@x.ai"}), "refresh_token": "r"},
            discovery={"token_endpoint": oauth.DEFAULT_TOKEN_ENDPOINT},
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
            account={"email": "me@x.ai"},
        )
        store.save(state, self.env)
        status = login.do_status(self.settings, env=self.env)
        self.assertTrue(status["logged_in"])
        self.assertFalse(status["expiring"])
        self.assertEqual(status["account"]["email"], "me@x.ai")
        self.assertIn("expires_at", status)

    def test_logout_reports_removal(self):
        store.save(
            store.new_state(
                tokens={"access_token": "a", "refresh_token": "r"},
                discovery={},
                redirect_uri="",
                base_url="https://api.x.ai/v1",
            ),
            self.env,
        )
        self.assertTrue(login.do_logout(self.env)["removed"])
        self.assertFalse(login.do_logout(self.env)["removed"])


class LoginFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}
        self.settings = resolve_settings({}, env=self.env, file_cfg={})

    def tearDown(self):
        self._tmp.cleanup()

    def test_manual_login_persists_credentials(self):
        discovery = {
            "authorization_endpoint": oauth.DEFAULT_AUTHORIZATION_ENDPOINT,
            "token_endpoint": oauth.DEFAULT_TOKEN_ENDPOINT,
        }
        token_payload = {"access_token": make_jwt({"email": "me@x.ai", "sub": "u1"}), "refresh_token": "r"}
        with mock.patch.object(login.oauth, "discover", return_value=discovery), mock.patch.object(
            login.loopback,
            "prompt_manual_paste",
            return_value={"code": "CODE", "state": None, "error": None, "error_description": None},
        ), mock.patch.object(login.oauth, "exchange_code", return_value=token_payload) as exchange, contextlib.redirect_stderr(io.StringIO()):
            result = login.do_login(self.settings, env=self.env, manual_paste=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["account"]["email"], "me@x.ai")
        exchange.assert_called_once()
        loaded = store.load(self.env)
        assert loaded is not None
        self.assertEqual(loaded["account"]["email"], "me@x.ai")

    def test_from_official_failure_raises(self):
        with mock.patch.object(login.tokens, "import_from_official_grok", return_value=False):
            with self.assertRaises(AuthError):
                login.do_login(self.settings, env=self.env, from_official=True)


class VerifyNonceTest(unittest.TestCase):
    def test_mismatch_raises(self):
        block = {"id_token": make_jwt({"nonce": "BAD"})}
        with self.assertRaises(AuthError):
            login._verify_nonce(block, expected_nonce="GOOD")

    def test_match_ok(self):
        block = {"id_token": make_jwt({"nonce": "GOOD"})}
        login._verify_nonce(block, expected_nonce="GOOD")  # no raise

    def test_no_nonce_claim_ok(self):
        block = {"id_token": make_jwt({"sub": "u"})}
        login._verify_nonce(block, expected_nonce="GOOD")  # no raise (PKCE still binds)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""Tests for JWT expiry, proactive refresh, runtime resolution, and import."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from grokcli.auth import oauth, store, tokens
from grokcli.errors import AuthError


def make_jwt(claims: dict) -> str:
    """Build an unsigned JWT with the given payload claims (header.payload.sig)."""

    def b64(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(claims)}.sig"


class JwtTest(unittest.TestCase):
    def test_decode_claims(self):
        token = make_jwt({"email": "a@b.c", "sub": "u1", "exp": 123})
        claims = tokens.decode_jwt_claims(token)
        self.assertEqual(claims["email"], "a@b.c")
        self.assertEqual(claims["sub"], "u1")

    def test_decode_garbage_returns_empty(self):
        self.assertEqual(tokens.decode_jwt_claims("not-a-jwt"), {})

    def test_access_token_expiry_reads_exp(self):
        token = make_jwt({"exp": 9999999999})
        self.assertEqual(tokens.access_token_expiry(token), 9999999999.0)

    def test_access_token_expiry_none_without_exp(self):
        self.assertIsNone(tokens.access_token_expiry(make_jwt({"sub": "x"})))


class IsExpiringTest(unittest.TestCase):
    def test_missing_token_is_expiring(self):
        self.assertTrue(tokens.is_expiring({"tokens": {}}))

    def test_future_jwt_not_expiring(self):
        state = {"tokens": {"access_token": make_jwt({"exp": time.time() + 3600})}}
        self.assertFalse(tokens.is_expiring(state))

    def test_past_jwt_is_expiring(self):
        state = {"tokens": {"access_token": make_jwt({"exp": time.time() - 10})}}
        self.assertTrue(tokens.is_expiring(state))

    def test_within_skew_is_expiring(self):
        state = {"tokens": {"access_token": make_jwt({"exp": time.time() + 60})}}
        self.assertTrue(tokens.is_expiring(state, skew_seconds=300))

    def test_falls_back_to_last_refresh_plus_expires_in(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1000))
        state = {"tokens": {"access_token": "opaque", "expires_in": 100}, "last_refresh": old}
        self.assertTrue(tokens.is_expiring(state))

    def test_unknown_expiry_is_not_expiring(self):
        state = {"tokens": {"access_token": "opaque"}}
        self.assertFalse(tokens.is_expiring(state))


class EnsureFreshTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, access):
        return store.new_state(
            tokens={"access_token": access, "refresh_token": "r0"},
            discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
        )

    def test_no_refresh_when_fresh(self):
        state = self._state(make_jwt({"exp": time.time() + 3600}))
        with mock.patch.object(oauth, "refresh") as refresh:
            out, refreshed = tokens.ensure_fresh(state, env=self.env)
        self.assertFalse(refreshed)
        refresh.assert_not_called()

    def test_refreshes_when_expiring(self):
        state = self._state(make_jwt({"exp": time.time() - 10}))
        store.save(state, self.env)
        with mock.patch.object(oauth, "refresh", return_value={"access_token": "NEW", "refresh_token": "r1"}):
            out, refreshed = tokens.ensure_fresh(state, env=self.env)
        self.assertTrue(refreshed)
        self.assertEqual(out["tokens"]["access_token"], "NEW")
        reloaded = store.load(self.env)
        assert reloaded is not None
        self.assertEqual(reloaded["tokens"]["access_token"], "NEW")

    def test_force_refresh_even_when_fresh(self):
        state = self._state(make_jwt({"exp": time.time() + 3600}))
        store.save(state, self.env)
        with mock.patch.object(oauth, "refresh", return_value={"access_token": "FORCED"}):
            out, refreshed = tokens.ensure_fresh(state, env=self.env, force=True)
        self.assertTrue(refreshed)
        self.assertEqual(out["tokens"]["access_token"], "FORCED")
        # refresh_token preserved because the response omitted it
        self.assertEqual(out["tokens"]["refresh_token"], "r0")

    def test_terminal_refresh_records_error_and_raises(self):
        state = self._state(make_jwt({"exp": time.time() - 10}))
        store.save(state, self.env)
        boom = AuthError("dead grant", code="xai_grant_invalid", relogin_required=True)
        with mock.patch.object(oauth, "refresh", side_effect=boom):
            with self.assertRaises(AuthError):
                tokens.ensure_fresh(state, env=self.env)
        reloaded = store.load(self.env)
        assert reloaded is not None
        self.assertEqual(reloaded["last_auth_error"]["code"], "xai_grant_invalid")


class ResolveRuntimeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def test_not_logged_in_raises(self):
        with self.assertRaises(AuthError) as ctx:
            tokens.resolve_runtime_credentials(env=self.env)
        self.assertTrue(ctx.exception.relogin_required)

    def test_returns_access_token_when_fresh(self):
        state = store.new_state(
            tokens={"access_token": make_jwt({"exp": time.time() + 3600}), "refresh_token": "r"},
            discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
        )
        store.save(state, self.env)
        creds = tokens.resolve_runtime_credentials(env=self.env)
        self.assertTrue(creds["access_token"])
        self.assertEqual(creds["base_url"], "https://api.x.ai/v1")


class EnsureFreshConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def test_skips_refresh_when_disk_already_fresh(self):
        # Caller holds a STALE expiring state, but another process already wrote a
        # fresh token to disk. ensure_fresh must re-read under the lock and skip.
        fresh = store.new_state(
            tokens={"access_token": make_jwt({"exp": time.time() + 3600}), "refresh_token": "r1"},
            discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
        )
        store.save(fresh, self.env)
        stale = dict(fresh)
        stale["tokens"] = {"access_token": make_jwt({"exp": time.time() - 10}), "refresh_token": "r1"}
        with mock.patch.object(oauth, "refresh") as refresh:
            out, refreshed = tokens.ensure_fresh(stale, env=self.env)
        self.assertFalse(refreshed)
        refresh.assert_not_called()  # disk was fresh; no redundant (would-fail) refresh

    def test_discovers_endpoint_when_missing(self):
        state = store.new_state(
            tokens={"access_token": make_jwt({"exp": time.time() - 10}), "refresh_token": "r"},
            discovery={},  # no token_endpoint stored
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
        )
        store.save(state, self.env)
        with mock.patch.object(oauth, "discover", return_value={"token_endpoint": oauth.DEFAULT_TOKEN_ENDPOINT, "authorization_endpoint": oauth.DEFAULT_AUTHORIZATION_ENDPOINT}) as discover, mock.patch.object(
            oauth, "refresh", return_value={"access_token": "NEW", "refresh_token": "r"}
        ):
            tokens.ensure_fresh(state, env=self.env)
        discover.assert_called_once()


class FindOfficialEntryTest(unittest.TestCase):
    def test_falls_back_to_issuer_match(self):
        data = {"some-other-key": {"oidc_issuer": oauth.ISSUER, "key": "A", "refresh_token": "R"}}
        entry = tokens._find_official_entry(data)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["key"], "A")

    def test_import_corrupt_json_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "auth.json"
            bad.write_text("{not json")
            self.assertFalse(tokens.import_from_official_grok({"GROKCLI_HOME": tmp}, official_path=bad))


class ImportOfficialTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def test_imports_keyed_entry(self):
        official = Path(self._tmp.name) / "official.json"
        official.write_text(
            json.dumps(
                {
                    f"{oauth.ISSUER}::{oauth.CLIENT_ID}": {
                        "key": "ACCESS",
                        "refresh_token": "REFRESH",
                        "email": "me@x.ai",
                        "user_id": "u9",
                        "oidc_issuer": oauth.ISSUER,
                    }
                }
            )
        )
        self.assertTrue(tokens.import_from_official_grok(self.env, official_path=official))
        loaded = store.load(self.env)
        assert loaded is not None
        self.assertEqual(loaded["tokens"]["access_token"], "ACCESS")
        self.assertEqual(loaded["account"]["email"], "me@x.ai")

    def test_returns_false_when_absent(self):
        missing = Path(self._tmp.name) / "nope.json"
        self.assertFalse(tokens.import_from_official_grok(self.env, official_path=missing))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

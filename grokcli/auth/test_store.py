"""Tests for credential storage (round-trip, perms, clear, error recording)."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest

from grokcli import config
from grokcli.auth import store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self):
        return store.new_state(
            tokens={"access_token": "a", "refresh_token": "r"},
            discovery={"token_endpoint": "https://auth.x.ai/oauth2/token"},
            redirect_uri="http://127.0.0.1:56121/callback",
            base_url="https://api.x.ai/v1",
            account={"email": "x@y.z"},
        )

    def test_load_missing_returns_none(self):
        self.assertIsNone(store.load(self.env))

    def test_save_then_load_round_trip(self):
        store.save(self._state(), self.env)
        loaded = store.load(self.env)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["tokens"]["access_token"], "a")
        self.assertEqual(loaded["account"]["email"], "x@y.z")
        self.assertEqual(loaded["provider"], store.PROVIDER)

    def test_auth_file_is_owner_only(self):
        store.save(self._state(), self.env)
        mode = stat.S_IMODE(os.stat(config.auth_path(self.env)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_clear_removes_file(self):
        store.save(self._state(), self.env)
        self.assertTrue(store.clear(self.env))
        self.assertIsNone(store.load(self.env))
        self.assertFalse(store.clear(self.env))  # already gone

    def test_load_ignores_state_without_tokens(self):
        config_home = config.home_dir(self.env)
        config_home.mkdir(parents=True, exist_ok=True)
        config.auth_path(self.env).write_text('{"provider": "xai-oauth"}')
        self.assertIsNone(store.load(self.env))

    def test_record_error_persists(self):
        store.save(self._state(), self.env)
        store.record_error(None, {"code": "boom", "message": "kaput"}, self.env)
        loaded = store.load(self.env)
        assert loaded is not None
        self.assertEqual(loaded["last_auth_error"]["code"], "boom")
        self.assertIn("at", loaded["last_auth_error"])

    def test_record_error_reloads_disk_and_preserves_fresh_tokens(self):
        # Disk has a freshly-refreshed token; a stale caller records an error.
        # The fresh token must survive (regression: record_error must re-read disk).
        fresh = self._state()
        fresh["tokens"] = {"access_token": "FRESH", "refresh_token": "r2"}
        store.save(fresh, self.env)
        stale = self._state()  # holds the original "a" access_token
        store.record_error(stale, {"code": "stale_failure", "message": "x"}, self.env)
        loaded = store.load(self.env)
        assert loaded is not None
        self.assertEqual(loaded["tokens"]["access_token"], "FRESH")  # not clobbered by stale state
        self.assertEqual(loaded["last_auth_error"]["code"], "stale_failure")

    def test_load_corrupt_returns_none(self):
        config.home_dir(self.env).mkdir(parents=True, exist_ok=True)
        config.auth_path(self.env).write_text("{not valid json")
        self.assertIsNone(store.load(self.env))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

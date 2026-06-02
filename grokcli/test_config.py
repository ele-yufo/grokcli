"""Tests for configuration paths, base-URL pinning, and settings precedence."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from grokcli import config
from grokcli.errors import UsageError


class PathsTest(unittest.TestCase):
    def test_home_dir_honors_override(self):
        self.assertEqual(config.home_dir({"GROKCLI_HOME": "/tmp/x"}), Path("/tmp/x"))

    def test_home_dir_default(self):
        self.assertEqual(config.home_dir({}), Path.home() / ".config" / "grokcli")

    def test_auth_and_config_paths_live_under_home(self):
        env = {"GROKCLI_HOME": "/tmp/x"}
        self.assertEqual(config.auth_path(env), Path("/tmp/x/auth.json"))
        self.assertEqual(config.config_path(env), Path("/tmp/x/config.json"))


class BaseUrlPinTest(unittest.TestCase):
    def test_accepts_xai_https(self):
        self.assertEqual(config.validate_base_url("https://api.x.ai/v1/"), "https://api.x.ai/v1")

    def test_accepts_xai_subdomain(self):
        self.assertEqual(config.validate_base_url("https://staging.x.ai/v1"), "https://staging.x.ai/v1")

    def test_rejects_foreign_host(self):
        self.assertEqual(config.validate_base_url("https://evil.example/v1"), config.DEFAULT_BASE_URL)

    def test_rejects_http_scheme(self):
        self.assertEqual(config.validate_base_url("http://api.x.ai/v1"), config.DEFAULT_BASE_URL)

    def test_empty_returns_fallback(self):
        self.assertEqual(config.validate_base_url(""), config.DEFAULT_BASE_URL)


class OutputDetectionTest(unittest.TestCase):
    def test_non_tty_defaults_to_json(self):
        self.assertEqual(config.detect_output_format(io.StringIO()), "json")

    def test_tty_defaults_to_text(self):
        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        self.assertEqual(config.detect_output_format(FakeTTY()), "text")

    def test_no_color_env_disables_color(self):
        self.assertFalse(config.detect_color({"NO_COLOR": "1"}))


class ResolveSettingsTest(unittest.TestCase):
    def test_precedence_flag_over_env_over_file(self):
        s = config.resolve_settings(
            {"chat_model": "flag-model"},
            env={"GROKCLI_CHAT_MODEL": "env-model"},
            file_cfg={"chat_model": "file-model"},
        )
        self.assertEqual(s.chat_model, "flag-model")

    def test_env_over_file(self):
        s = config.resolve_settings(
            {},
            env={"GROKCLI_CHAT_MODEL": "env-model"},
            file_cfg={"chat_model": "file-model"},
        )
        self.assertEqual(s.chat_model, "env-model")

    def test_file_over_default(self):
        s = config.resolve_settings({}, env={}, file_cfg={"chat_model": "file-model"})
        self.assertEqual(s.chat_model, "file-model")

    def test_default_when_nothing_set(self):
        s = config.resolve_settings({}, env={}, file_cfg={})
        self.assertEqual(s.chat_model, config.DEFAULT_CHAT_MODEL)

    def test_bad_timeout_falls_back_to_default(self):
        s = config.resolve_settings({}, env={"GROKCLI_TIMEOUT": "not-a-number"}, file_cfg={})
        self.assertEqual(s.timeout, config.DEFAULT_TIMEOUT_SECONDS)

    def test_base_url_override_is_pinned(self):
        s = config.resolve_settings({"base_url": "https://evil.example/v1"}, env={}, file_cfg={})
        self.assertEqual(s.base_url, config.DEFAULT_BASE_URL)


class ConfigFileRoundTripTest(unittest.TestCase):
    def test_save_then_load_keeps_known_keys_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GROKCLI_HOME": tmp}
            config.save_config_file({"chat_model": "grok-4.3", "junk": "drop-me"}, env)
            loaded = config.load_config_file(env)
            self.assertEqual(loaded.get("chat_model"), "grok-4.3")
            self.assertNotIn("junk", loaded)

    def test_set_config_value_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError):
                config.set_config_value("bogus", "x", {"GROKCLI_HOME": tmp})

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.load_config_file({"GROKCLI_HOME": tmp}), {})

    def test_load_corrupt_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GROKCLI_HOME": tmp}
            config.home_dir(env).mkdir(parents=True, exist_ok=True)
            config.config_path(env).write_text("{bad json")
            self.assertEqual(config.load_config_file(env), {})

    def test_set_base_url_valid_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GROKCLI_HOME": tmp}
            config.set_config_value("base_url", "https://api.x.ai/v1", env)
            self.assertEqual(config.load_config_file(env)["base_url"], "https://api.x.ai/v1")

    def test_set_base_url_invalid_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError):
                config.set_config_value("base_url", "https://evil.example/v1", {"GROKCLI_HOME": tmp})


class TruthyAndVerboseTest(unittest.TestCase):
    def test_truthy_values(self):
        for falsey in ("", "0", "false", "no", "off", "FALSE"):
            self.assertFalse(config._truthy(falsey), falsey)
        for truthy in ("1", "true", "yes", "on", "anything"):
            self.assertTrue(config._truthy(truthy), truthy)

    def test_verbose_env_zero_does_not_enable(self):
        s = config.resolve_settings({}, env={"GROKCLI_VERBOSE": "0"}, file_cfg={})
        self.assertFalse(s.verbose)

    def test_verbose_env_one_enables(self):
        s = config.resolve_settings({}, env={"GROKCLI_VERBOSE": "1"}, file_cfg={})
        self.assertTrue(s.verbose)

    def test_invalid_output_format_falls_back_to_text(self):
        s = config.resolve_settings({}, env={"GROKCLI_OUTPUT": "xml"}, file_cfg={})
        self.assertEqual(s.output_format, "text")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

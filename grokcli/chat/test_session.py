"""Tests for bounded local chat-session persistence."""

from __future__ import annotations

import os
import stat
import tempfile
import time
import unittest

from grokcli.chat import session


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, sid, msgs):
        s = session.new_session(model="grok-4.3", session_id=sid)
        for i in range(msgs):
            s.add("user", f"q{i}")
            s.add("assistant", f"a{i}")
        return s

    def test_save_and_load_round_trip(self):
        s = self._make("alpha", 2)
        session.save(s, self.env)
        loaded = session.load("alpha", self.env)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(len(loaded.messages), 4)
        self.assertEqual(loaded.model, "grok-4.3")

    def test_session_file_is_owner_only(self):
        session.save(self._make("p", 1), self.env)
        mode = stat.S_IMODE(os.stat(session.session_path("p", self.env)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_per_session_message_cap_trims_oldest(self):
        env = {**self.env, "GROKCLI_MAX_SESSION_MESSAGES": "4"}
        s = self._make("big", 5)  # 10 messages
        session.save(s, env)
        loaded = session.load("big", env)
        assert loaded is not None
        self.assertLessEqual(len(loaded.messages), 4)
        # Oldest trimmed; the most recent exchange survives.
        self.assertEqual(loaded.messages[-1], {"role": "assistant", "content": "a4"})
        # Never left starting on a dangling assistant turn.
        self.assertEqual(loaded.messages[0]["role"], "user")

    def test_lru_cap_prunes_oldest_sessions(self):
        env = {**self.env, "GROKCLI_MAX_SESSIONS": "3"}
        for i in range(5):
            session.save(self._make(f"s{i}", 1), env)
            time.sleep(0.01)  # ensure distinct mtimes
        remaining = {item["id"] for item in session.list_sessions(env)}
        self.assertLessEqual(len(remaining), 3)
        self.assertIn("s4", remaining)  # newest kept
        self.assertNotIn("s0", remaining)  # oldest pruned

    def test_latest_returns_most_recent(self):
        session.save(self._make("old", 1), self.env)
        time.sleep(0.01)
        session.save(self._make("new", 1), self.env)
        latest = session.latest(self.env)
        assert latest is not None
        self.assertEqual(latest.id, "new")

    def test_resolve_named_creates_then_continues(self):
        first = session.resolve(name="work", model="grok-4.3", env=self.env)
        first.add("user", "hi")
        first.add("assistant", "hello")
        session.save(first, self.env)
        again = session.resolve(name="work", env=self.env)
        self.assertEqual(again.id, "work")
        self.assertEqual(len(again.messages), 2)  # continued, not fresh

    def test_resolve_force_new_ignores_continue(self):
        session.save(self._make("x", 1), self.env)
        fresh = session.resolve(continue_latest=True, force_new=True, env=self.env)
        self.assertEqual(fresh.messages, [])

    def test_sanitize_id_strips_unsafe(self):
        self.assertEqual(session.sanitize_id("../../etc/passwd"), "etc-passwd")
        self.assertTrue(session.sanitize_id("///").strip())  # falls back to a generated id

    def test_clear_one_and_all(self):
        session.save(self._make("a", 1), self.env)
        session.save(self._make("b", 1), self.env)
        self.assertEqual(session.clear("a", env=self.env), 1)
        self.assertEqual(len(session.list_sessions(self.env)), 1)
        self.assertEqual(session.clear(all_sessions=True, env=self.env), 1)
        self.assertEqual(session.list_sessions(self.env), [])

    def test_load_missing_returns_none(self):
        self.assertIsNone(session.load("nope", self.env))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

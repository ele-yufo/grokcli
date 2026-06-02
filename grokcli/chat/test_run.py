"""Tests for one-shot chat orchestration (rendering, streaming, json mode)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock

from grokcli.chat import run
from grokcli.config import resolve_settings
from grokcli.errors import UsageError


def settings(fmt="text"):
    return resolve_settings({"output_format": fmt, "no_color": True}, env={}, file_cfg={})


class RunChatTest(unittest.TestCase):
    def test_empty_prompt_raises(self):
        with self.assertRaises(UsageError):
            run.run_chat(settings(), prompt="   ", model="grok-4", env={})

    def test_json_mode_emits_single_object(self):
        result = {"text": "hi there", "citations": ["https://x.ai"], "usage": {"total_tokens": 3}}
        buf = io.StringIO()
        with mock.patch.object(run.api, "complete", return_value=result), contextlib.redirect_stdout(buf):
            code = run.run_chat(settings("json"), prompt="hi", model="grok-4", env={})
        self.assertEqual(code, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["text"], "hi there")
        self.assertEqual(parsed["citations"], ["https://x.ai"])

    def test_text_non_stream_prints_answer(self):
        result = {"text": "the answer", "citations": [], "usage": None}
        buf = io.StringIO()
        with mock.patch.object(run.api, "complete", return_value=result), contextlib.redirect_stdout(buf):
            run.run_chat(settings("text"), prompt="q", model="grok-4", stream=False, env={})
        self.assertEqual(buf.getvalue().strip(), "the answer")

    def test_streaming_writes_deltas(self):
        class FakeStream:
            def __init__(self, *a, **k):
                self.text = "Hello"
                self.citations = []

            def __iter__(self):
                return iter(["Hel", "lo"])

        buf = io.StringIO()
        with mock.patch.object(run.api, "ChatStream", FakeStream), contextlib.redirect_stdout(buf):
            run.run_chat(settings("text"), prompt="q", model="grok-4", stream=True, env={})
        self.assertEqual(buf.getvalue(), "Hello\n")

    def test_streaming_no_deltas_falls_back_to_text(self):
        class FakeStream:
            def __init__(self, *a, **k):
                self.text = "fallback"
                self.citations = []

            def __iter__(self):
                return iter([])

        buf = io.StringIO()
        with mock.patch.object(run.api, "ChatStream", FakeStream), contextlib.redirect_stdout(buf):
            run.run_chat(settings("text"), prompt="q", model="grok-4", stream=True, env={})
        self.assertEqual(buf.getvalue().strip(), "fallback")


class HandleCommandTest(unittest.TestCase):
    def _style(self):
        from grokcli import output

        return output.Style(False)

    def test_exit_and_quit(self):
        self.assertEqual(run._handle_command("/exit", [], self._style()), "exit")
        self.assertEqual(run._handle_command("/quit", [], self._style()), "exit")

    def test_reset_clears_history(self):
        history = [{"role": "user", "content": "x"}]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run._handle_command("/reset", history, self._style()), "reset")
        self.assertEqual(history, [])

    def test_system_and_model(self):
        self.assertEqual(run._handle_command("/system be terse", [], self._style()), "set_system")
        self.assertEqual(run._handle_command("/model grok-4.3", [], self._style()), "set_model")

    def test_help_and_unknown(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run._handle_command("/help", [], self._style()), "handled")
            self.assertEqual(run._handle_command("/bogus", [], self._style()), "handled")


class ReplTest(unittest.TestCase):
    def test_repl_requires_tty(self):
        from grokcli.errors import UsageError

        with mock.patch.object(run, "_stdin_is_tty", return_value=False):
            with self.assertRaises(UsageError):
                run.run_repl(settings("text"), model="grok-4", env={})

    def test_repl_exits_on_eof(self):
        with mock.patch.object(run, "_stdin_is_tty", return_value=True), mock.patch(
            "builtins.input", side_effect=EOFError
        ), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run.run_repl(settings("text"), model="grok-4", env={}), 0)

    def test_repl_survives_a_failed_turn(self):
        from grokcli.errors import APIError

        inputs = iter(["hello", EOFError()])

        def fake_input(_prompt=""):
            value = next(inputs)
            if isinstance(value, BaseException):
                raise value
            return value

        err = io.StringIO()
        with mock.patch.object(run, "_stdin_is_tty", return_value=True), mock.patch(
            "builtins.input", side_effect=fake_input
        ), mock.patch.object(run.api, "ChatStream", side_effect=APIError("boom")), contextlib.redirect_stdout(
            io.StringIO()
        ), contextlib.redirect_stderr(err):
            code = run.run_repl(settings("text"), model="grok-4", stream=True, env={})
        self.assertEqual(code, 0)
        self.assertIn("boom", err.getvalue())  # the failed turn was reported, loop continued


class ChatSessionTest(unittest.TestCase):
    def test_continue_persists_then_resumes_with_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GROKCLI_HOME": tmp}
            with mock.patch.object(run.api, "complete", return_value={"text": "A1", "citations": [], "usage": None}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                run.run_chat(settings("json"), prompt="Q1", model="grok-4.3", env=env, continue_session=True)

            captured = {}

            def cap(client, *, model, messages, instructions=None, tools=None):
                captured["messages"] = list(messages)
                return {"text": "A2", "citations": [], "usage": None}

            with mock.patch.object(run.api, "complete", side_effect=cap), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                run.run_chat(settings("json"), prompt="Q2", model="grok-4.3", env=env, continue_session=True)
            self.assertEqual([m["content"] for m in captured["messages"]], ["Q1", "A1", "Q2"])

    def test_no_session_flag_is_stateless(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GROKCLI_HOME": tmp}
            with mock.patch.object(run.api, "complete", return_value={"text": "x", "citations": [], "usage": None}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                run.run_chat(settings("json"), prompt="hi", model="grok-4.3", env=env)
            from grokcli.chat import session

            self.assertEqual(session.list_sessions(env), [])  # nothing persisted


class PrintCitationsTest(unittest.TestCase):
    def test_text_mode_writes_sources_to_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            run._print_citations(["https://a", "https://b"], settings("text"))
        self.assertIn("https://a", err.getvalue())

    def test_json_mode_prints_nothing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            run._print_citations(["https://a"], settings("json"))
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

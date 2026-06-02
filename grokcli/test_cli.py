"""Tests for CLI parsing, settings resolution, dispatch, and error rendering."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

from grokcli import cli
from grokcli.errors import AuthError, TierDeniedError


class ParserTest(unittest.TestCase):
    def test_no_command_prints_help_and_usage_exit(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main([])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.getvalue().lower())

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_global_options_after_subcommand(self):
        parser = cli.build_parser()
        args = parser.parse_args(["chat", "hello", "--output", "json", "--verbose"])
        self.assertEqual(args.command, "chat")
        self.assertEqual(args.prompt, "hello")
        self.assertEqual(args.output, "json")
        self.assertTrue(args.verbose)


class SettingsFromArgsTest(unittest.TestCase):
    def test_overrides_applied(self):
        parser = cli.build_parser()
        args = parser.parse_args(["doctor", "--timeout", "12", "--output", "json"])
        with mock.patch.dict("os.environ", {"GROKCLI_HOME": "/tmp/x"}, clear=False):
            settings = cli._settings_from_args(args)
        self.assertEqual(settings.timeout, 12.0)
        self.assertEqual(settings.output_format, "json")


class DispatchTest(unittest.TestCase):
    def test_status_dispatches_and_returns_auth_exit_when_logged_out(self):
        with mock.patch("grokcli.auth.login.do_status", return_value={"logged_in": False}), contextlib.redirect_stdout(
            io.StringIO()
        ):
            code = cli.main(["status", "--output", "json"])
        self.assertEqual(code, 3)

    def test_doctor_dispatch(self):
        from grokcli import doctor as doctor_mod

        report = doctor_mod.DoctorReport(checks=[doctor_mod.Check("X", doctor_mod.OK, "fine")])
        with mock.patch("grokcli.doctor.run_doctor", return_value=report), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["doctor", "--offline", "--output", "json"])
        self.assertEqual(code, 0)


class ErrorRenderingTest(unittest.TestCase):
    def test_grok_error_renders_text_and_exit_code(self):
        with mock.patch("grokcli.auth.login.do_logout", side_effect=AuthError("nope", hint="do x")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["logout"])
        self.assertEqual(code, 3)
        self.assertIn("Error: nope", err.getvalue())
        self.assertIn("do x", err.getvalue())

    def test_error_json_mode(self):
        with mock.patch("grokcli.auth.login.do_logout", side_effect=TierDeniedError("denied")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["logout", "--output", "json"])
        self.assertEqual(code, 3)
        payload = json.loads(err.getvalue())
        self.assertTrue(payload["error"]["entitlement_denied"])

    def test_keyboard_interrupt_returns_130(self):
        with mock.patch("grokcli.auth.login.do_logout", side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["logout"]), 130)

    def test_broken_pipe_returns_0(self):
        with mock.patch("grokcli.auth.login.do_logout", side_effect=BrokenPipeError):
            self.assertEqual(cli.main(["logout"]), 0)


class HelpAtomicityTest(unittest.TestCase):
    """Help must be self-contained: a context-free agent learns everything from --help."""

    def _help(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            cli.main(argv + ["--help"])
        return buf.getvalue()

    def test_main_help_teaches_prerequisite_and_contract(self):
        text = self._help([])
        # An agent with no context must learn: log in first, the exit codes, and examples.
        for needle in ("grokcli login", "GETTING STARTED", "EXIT CODES", "EXAMPLES:", "OUTPUT", "--output"):
            self.assertIn(needle, text, needle)
        # Every command must be discoverable from the top-level help.
        for cmd in ("chat", "search", "image", "video", "tts", "transcribe", "voices", "models", "sessions", "config", "doctor", "status", "logout"):
            self.assertIn(cmd, text, cmd)

    def test_every_command_help_has_examples(self):
        commands = [
            ["login"], ["logout"], ["status"], ["doctor"], ["chat"], ["search"],
            ["image"], ["video"], ["tts"], ["voices"], ["transcribe"],
            ["sessions"], ["models"], ["config"],
        ]
        for argv in commands:
            text = self._help(argv)
            self.assertIn("EXAMPLES:", text, f"{argv} help has no EXAMPLES section")
            self.assertIn("grokcli " + argv[0], text, f"{argv} help lacks a concrete invocation")

    def test_subcommand_help_includes_global_options(self):
        # Each command's own --help is complete on its own (incl. global flags).
        self.assertIn("--output", self._help(["chat"]))
        self.assertIn("--verbose", self._help(["image"]))

    def test_help_command_prints_full_manual_in_one_call(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["help"]), 0)
        manual = buf.getvalue()
        # One call yields the overview + every command's section with examples.
        self.assertIn("GETTING STARTED", manual)
        self.assertGreaterEqual(manual.count("EXAMPLES:"), 10)
        for cmd in ("grokcli chat", "grokcli image", "grokcli tts", "grokcli search"):
            self.assertIn(cmd, manual)

    def test_help_command_single_topic(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["help", "chat"]), 0)
        self.assertIn("usage: grokcli chat", buf.getvalue())

    def test_help_command_unknown_topic_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["help", "nonexistent"]), 2)


class MediaDispatchTest(unittest.TestCase):
    """Each media subcommand must wire its argparse args to the right handler kwargs."""

    def test_image_dispatch(self):
        with mock.patch("grokcli.media.image.run_image", return_value=0) as run:
            self.assertEqual(cli.main(["image", "a fox", "-a", "16:9", "-r", "1k", "-n", "2"]), 0)
        kw = run.call_args.kwargs
        self.assertEqual((kw["prompt"], kw["aspect_ratio"], kw["resolution"], kw["n"]), ("a fox", "16:9", "1k", 2))

    def test_video_dispatch(self):
        with mock.patch("grokcli.media.video.run_video", return_value=0) as run:
            cli.main(["video", "a wave", "-i", "img.png", "-d", "6"])
        kw = run.call_args.kwargs
        self.assertEqual((kw["prompt"], kw["image"], kw["duration"]), ("a wave", "img.png", 6))

    def test_tts_dispatch(self):
        with mock.patch("grokcli.media.tts.run_tts", return_value=0) as run:
            cli.main(["tts", "hello", "--voice", "Rex", "--language", "en", "-f", "wav"])
        kw = run.call_args.kwargs
        self.assertEqual((kw["text"], kw["voice"], kw["language"], kw["fmt"]), ("hello", "Rex", "en", "wav"))

    def test_voices_dispatch(self):
        with mock.patch("grokcli.media.tts.run_voices", return_value=0) as run:
            self.assertEqual(cli.main(["voices"]), 0)
        run.assert_called_once()

    def test_transcribe_dispatch(self):
        with mock.patch("grokcli.media.transcribe.run_transcribe", return_value=0) as run:
            cli.main(["transcribe", "a.mp3"])
        self.assertEqual(run.call_args.kwargs["audio_path"], "a.mp3")

    def test_search_dispatch_passes_both_tools_by_default(self):
        with mock.patch("grokcli.chat.run.run_chat", return_value=0) as run:
            cli.main(["search", "who won?"])
        tools = run.call_args.kwargs["tools"]
        types = sorted(t["type"] for t in tools)
        self.assertEqual(types, ["web_search", "x_search"])

    def test_chat_dispatch_no_tools_when_no_flags(self):
        with mock.patch("grokcli.chat.run.run_chat", return_value=0) as run:
            cli.main(["chat", "hi"])
        self.assertIsNone(run.call_args.kwargs["tools"])

    def test_chat_continue_flag_dispatched(self):
        with mock.patch("grokcli.chat.run.run_chat", return_value=0) as run:
            cli.main(["chat", "hi", "-c", "--session", "work", "--new"])
        kw = run.call_args.kwargs
        self.assertTrue(kw["continue_session"])
        self.assertEqual(kw["session_name"], "work")
        self.assertTrue(kw["force_new"])


class SessionsCommandTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_empty(self):
        out = io.StringIO()
        with mock.patch.dict("os.environ", self.env, clear=False), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["sessions", "list", "--output", "text"]), 0)
        self.assertIn("no saved sessions", out.getvalue())

    def test_list_show_clear_roundtrip(self):
        from grokcli.chat import session

        s = session.new_session(model="grok-4.3", session_id="demo")
        s.add("user", "hello there")
        s.add("assistant", "hi")
        session.save(s, self.env)
        with mock.patch.dict("os.environ", self.env, clear=False):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["sessions", "list"])
            self.assertIn("demo", out.getvalue())
            show = io.StringIO()
            with contextlib.redirect_stdout(show):
                cli.main(["sessions", "show", "demo"])
            self.assertIn("hello there", show.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["sessions", "clear", "--all", "--output", "json"]), 0)
            self.assertEqual(session.list_sessions(self.env), [])


class ReadPromptTest(unittest.TestCase):
    def test_dash_reads_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("piped text")):
            self.assertEqual(cli._read_prompt("-"), "piped text")

    def test_none_piped_reads_stdin(self):
        with mock.patch.object(cli, "_stdin_is_tty", return_value=False), mock.patch("sys.stdin", io.StringIO("data")):
            self.assertEqual(cli._read_prompt(None), "data")

    def test_none_on_tty_returns_none(self):
        with mock.patch.object(cli, "_stdin_is_tty", return_value=True):
            self.assertIsNone(cli._read_prompt(None))

    def test_explicit_prompt_passthrough(self):
        self.assertEqual(cli._read_prompt("hello"), "hello")


class CoerceTest(unittest.TestCase):
    def test_int(self):
        self.assertEqual(cli._coerce("30"), 30)

    def test_float(self):
        self.assertEqual(cli._coerce("3.5"), 3.5)

    def test_string(self):
        self.assertEqual(cli._coerce("grok-4.3"), "grok-4.3")


class ModelIdsTest(unittest.TestCase):
    def test_data_key(self):
        self.assertEqual(cli._model_ids({"data": [{"id": "b"}, {"id": "a"}]}), ["a", "b"])

    def test_models_key(self):
        self.assertEqual(cli._model_ids({"models": [{"id": "x"}]}), ["x"])

    def test_empty(self):
        self.assertEqual(cli._model_ids({}), [])


class ConfigCommandTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"GROKCLI_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def test_set_then_get_via_cli(self):
        with mock.patch.dict("os.environ", self.env, clear=False), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["config", "set", "chat_model", "grok-4.3"]), 0)
        out = io.StringIO()
        with mock.patch.dict("os.environ", self.env, clear=False), contextlib.redirect_stdout(out):
            cli.main(["config", "get", "chat_model"])
        self.assertIn("grok-4.3", out.getvalue())

    def test_get_missing_key_is_usage_error(self):
        with mock.patch.dict("os.environ", self.env, clear=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["config", "get", "chat_model"]), 2)

    def test_set_bad_base_url_rejected(self):
        with mock.patch.dict("os.environ", self.env, clear=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["config", "set", "base_url", "https://evil.example/v1"]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

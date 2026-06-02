"""Tests for output styling, JSON/text rendering, spinner, progress bar."""

from __future__ import annotations

import io
import json
import unittest

from grokcli import output


class StyleTest(unittest.TestCase):
    def test_color_disabled_is_passthrough(self):
        s = output.Style(enabled=False)
        self.assertEqual(s.green("hi"), "hi")

    def test_color_enabled_wraps_ansi(self):
        s = output.Style(enabled=True)
        painted = s.red("x")
        self.assertTrue(painted.startswith("\033["))
        self.assertIn("x", painted)


class EmitResultTest(unittest.TestCase):
    def test_json_mode_prints_json(self):
        buf = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(buf):
            output.emit_result("json", {"a": 1}, "ignored text")
        self.assertEqual(json.loads(buf.getvalue()), {"a": 1})

    def test_text_mode_prints_text(self):
        buf = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(buf):
            output.emit_result("text", {"a": 1}, "hello")
        self.assertEqual(buf.getvalue().strip(), "hello")


class SpinnerTest(unittest.TestCase):
    def test_disabled_spinner_writes_message_once(self):
        buf = io.StringIO()  # not a tty -> spinner is a no-op printer
        sp = output.Spinner("working", enabled=True, stream=buf)
        self.assertFalse(sp.enabled)  # StringIO has no isatty truthy
        sp.start()
        sp.stop()
        self.assertIn("working", buf.getvalue())


class ProgressBarTest(unittest.TestCase):
    def test_noop_when_not_tty(self):
        buf = io.StringIO()
        output.progress_bar(5, 10, enabled=True, stream=buf)
        self.assertEqual(buf.getvalue(), "")

    def test_renders_on_tty_and_newline_on_complete(self):
        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        buf = FakeTTY()
        output.progress_bar(10, 10, enabled=True, stream=buf)
        out = buf.getvalue()
        self.assertIn("100.0%", out)
        self.assertTrue(out.endswith("\n"))


class SpinnerFinalTest(unittest.TestCase):
    def test_stop_with_final_writes_line(self):
        buf = io.StringIO()
        sp = output.Spinner("working", enabled=True, stream=buf)  # not a tty -> disabled
        sp.start()
        sp.stop(final="done!")
        self.assertIn("done!", buf.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

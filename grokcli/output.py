"""Terminal output helpers: color, spinner, progress, JSON/text rendering.

Strict stream discipline (borrowed from mature CLIs): **results go to stdout,
everything else — status, spinners, progress, errors — goes to stderr**. That
keeps ``grokcli chat "q" | jq`` and file redirection clean.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Optional, TextIO

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_COLORS = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "cyan": "36",
}


class Style:
    """ANSI styling that becomes a no-op when color is disabled."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def paint(self, name: str, text: str) -> str:
        code = _COLORS.get(name)
        if not self.enabled or not code:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t: str) -> str:
        return self.paint("bold", t)

    def dim(self, t: str) -> str:
        return self.paint("dim", t)

    def green(self, t: str) -> str:
        return self.paint("green", t)

    def red(self, t: str) -> str:
        return self.paint("red", t)

    def yellow(self, t: str) -> str:
        return self.paint("yellow", t)

    def cyan(self, t: str) -> str:
        return self.paint("cyan", t)


def stdout(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def stderr(text: str = "") -> None:
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def print_json(obj: Any) -> None:
    """Render an object as pretty JSON on stdout."""
    stdout(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def emit_result(output_format: str, data: Any, text: str) -> None:
    """Render a command result: JSON object in json mode, ``text`` otherwise."""
    if output_format == "json":
        print_json(data)
    elif text:
        stdout(text)


class Spinner:
    """A TTY-only braille spinner on stderr; a no-op when not interactive."""

    def __init__(self, message: str = "", *, enabled: bool = True, stream: Optional[TextIO] = None) -> None:
        self.message = message
        self._stream = stream or sys.stderr
        self.enabled = enabled and self._isatty()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (AttributeError, ValueError):
            return False

    def __enter__(self) -> "Spinner":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def start(self) -> None:
        if not self.enabled:
            if self.message:
                self._stream.write(self.message + "\n")
                self._stream.flush()
            return
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            self._stream.write(f"\r{frame} {self.message}\033[K")
            self._stream.flush()
            i += 1
            time.sleep(0.08)

    def update(self, message: str) -> None:
        self.message = message
        if not self.enabled and message:
            self._stream.write(message + "\n")
            self._stream.flush()

    def stop(self, final: str = "") -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)
            # Only clear the line if the spin thread actually exited; otherwise the
            # two threads would interleave escape sequences on stderr.
            if not self._thread.is_alive():
                self._stream.write("\r\033[K")
                self._stream.flush()
        if final:
            self._stream.write(final + "\n")
            self._stream.flush()


def progress_bar(downloaded: int, total: int, *, width: int = 30, enabled: bool = True, stream: Optional[TextIO] = None) -> None:
    """Render an in-place download progress bar on stderr (no-op if disabled)."""
    out = stream or sys.stderr
    try:
        if not enabled or not out.isatty():
            return
    except (AttributeError, ValueError):
        return
    if total > 0:
        filled = int(width * downloaded / total)
        bar = "█" * filled + "░" * (width - filled)
        pct = 100 * downloaded / total
        out.write(f"\r  [{bar}] {pct:5.1f}% ({downloaded}/{total} bytes)\033[K")
    else:
        out.write(f"\r  downloaded {downloaded} bytes\033[K")
    out.flush()
    if total > 0 and downloaded >= total:
        out.write("\n")
        out.flush()

"""Tests for atomic writes, secure directory perms, and advisory locking."""

from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from grokcli import fsutil


class AtomicWriteTest(unittest.TestCase):
    def test_write_bytes_is_owner_only_and_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "sub" / "secret.json"
            fsutil.atomic_write_bytes(dest, b'{"k":1}')
            self.assertEqual(dest.read_bytes(), b'{"k":1}')
            mode = stat.S_IMODE(os.stat(dest).st_mode)
            self.assertEqual(mode, 0o600)

    def test_write_text_overwrites_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.txt"
            fsutil.atomic_write_text(dest, "one")
            fsutil.atomic_write_text(dest, "two")
            self.assertEqual(dest.read_text(), "two")

    def test_no_leftover_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.txt"
            fsutil.atomic_write_text(dest, "x")
            leftovers = [p.name for p in Path(tmp).iterdir() if ".tmp." in p.name]
            self.assertEqual(leftovers, [])


class SecureDirTest(unittest.TestCase):
    def test_creates_dir_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "deep" / "nest"
            fsutil.secure_dir(d)
            self.assertTrue(d.is_dir())
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)


class FileLockTest(unittest.TestCase):
    def test_lock_serializes_critical_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "x.lock"
            order = []

            def worker(tag: str, hold: float):
                with fsutil.file_lock(lock):
                    order.append(f"{tag}-in")
                    time.sleep(hold)
                    order.append(f"{tag}-out")

            t1 = threading.Thread(target=worker, args=("a", 0.15))
            t1.start()
            time.sleep(0.02)
            t2 = threading.Thread(target=worker, args=("b", 0.0))
            t2.start()
            t1.join()
            t2.join()
            # b must not enter until a has exited (flock is exclusive).
            self.assertEqual(order, ["a-in", "a-out", "b-in", "b-out"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

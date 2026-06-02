"""Filesystem helpers: atomic writes, owner-only permissions, advisory locks.

Credential files are written with mode 0600 and their parent directory tightened
to 0700, created atomically (O_EXCL temp + rename) to avoid a TOCTOU window
where the default umask could briefly expose tokens to other local users.
"""

from __future__ import annotations

import contextlib
import os
import stat
import uuid
from pathlib import Path
from typing import Generator, Union

try:  # POSIX advisory locking; absent on some platforms (e.g. plain Windows).
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore

PathLike = Union[str, "os.PathLike[str]"]

_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0o600
_OWNER_RWX = stat.S_IRWXU  # 0o700


def secure_dir(path: PathLike) -> Path:
    """Create ``path`` (and parents) if needed and tighten it to 0700.

    Permission tightening is best-effort: it is a no-op error on filesystems or
    platforms that do not enforce POSIX mode bits.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(_OWNER_RWX)
    return directory


def atomic_write_bytes(path: PathLike, data: bytes, *, mode: int = _OWNER_RW) -> Path:
    """Atomically write ``data`` to ``path`` with the given permission ``mode``.

    The bytes are written to a uniquely named temp file in the same directory
    (created via ``O_EXCL`` with the final mode, so it is never world-readable),
    fsynced, then ``os.replace``-d over the destination. The parent directory is
    fsynced too so the rename survives a crash.
    """
    dest = Path(path)
    secure_dir(dest.parent)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        # O_EXCL + explicit mode closes the umask window where tokens could be
        # briefly world-readable between open() and a later chmod().
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            handle = os.fdopen(fd, "wb")
        except BaseException:  # fdopen did not take ownership of fd
            os.close(fd)
            raise
        with handle:  # closes fd exactly once, on normal exit or exception
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()
    with contextlib.suppress(OSError):
        dest.chmod(mode)
    return dest


def atomic_write_text(path: PathLike, text: str, *, mode: int = _OWNER_RW) -> Path:
    """Atomically write UTF-8 ``text`` to ``path``."""
    return atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename within it is durable. Best-effort."""
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:  # pragma: no cover - some filesystems reject dir fsync
        pass
    finally:
        os.close(dir_fd)


@contextlib.contextmanager
def file_lock(lock_path: PathLike) -> Generator[None, None, None]:
    """Cross-process advisory lock guarding credential reads/writes.

    Uses ``fcntl.flock`` where available; degrades to a no-op (still safe within
    a single process) when ``fcntl`` is missing. The lock file itself is created
    with owner-only permissions.
    """
    if fcntl is None:  # pragma: no cover - platform dependent
        yield
        return
    lock_file = Path(lock_path)
    secure_dir(lock_file.parent)
    fd = os.open(str(lock_file), os.O_WRONLY | os.O_CREAT, _OWNER_RW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

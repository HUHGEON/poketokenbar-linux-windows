"""One live daemon and one live tray per login session.

The Windows installer and the login shortcut are both allowed to launch the
application.  Without a process-wide guard, reinstalling creates another
daemon with its own in-memory companion state and the copies race to overwrite
the same save.  A named mutex is the native Windows solution; advisory file
locking provides the equivalent for the Unix front ends.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import platform_paths


class SingleInstance:
    """A non-blocking, process-lifetime lock for one application component."""

    def __init__(self, name: str, *, system: str | None = None,
                 directory: Path | None = None) -> None:
        self.name = name
        self.system = system or sys.platform
        self.directory = directory
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        if self._handle is not None or self._file is not None:
            return True
        if self.system.startswith("win"):
            return self._acquire_windows()
        return self._acquire_unix()

    def _acquire_windows(self) -> bool:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateMutexW
        create.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        create.restype = ctypes.c_void_p
        close = kernel32.CloseHandle
        close.argtypes = (ctypes.c_void_p,)
        close.restype = ctypes.c_bool

        handle = create(None, False, f"Local\\PokeTokenBar.{self.name}")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            close(handle)
            return False
        self._handle = (kernel32, handle)
        return True

    def _acquire_unix(self) -> bool:
        import fcntl

        directory = self.directory or platform_paths.runtime_base() / "poketokenbar"
        directory.mkdir(parents=True, exist_ok=True)
        lock_file = (directory / f"{self.name}.lock").open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            return False
        self._file = lock_file
        return True

    def release(self) -> None:
        if self._handle is not None:
            kernel32, handle = self._handle
            self._handle = None
            kernel32.CloseHandle(handle)
        if self._file is not None:
            import fcntl

            lock_file, self._file = self._file, None
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def __enter__(self):
        return self if self.acquire() else None

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.release()

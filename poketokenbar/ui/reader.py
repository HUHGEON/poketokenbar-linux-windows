"""state.json, polled.

The daemon writes atomically, so a torn read should not happen; it still can,
and a parse failure keeps the last good snapshot rather than blanking the
window. Only a run of them is reported.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import l10n, state as state_module

# How stale the file may get before the UI says the daemon looks stopped. The
# daemon's own default refresh is 120s, so this is several missed polls.
STALE_AFTER_SECONDS = 600

# Consecutive unparseable reads before the error surfaces. One is a torn read
# racing a rename; a run of them is a real problem.
PARSE_FAILURES_BEFORE_REPORTING = 3


class StateReader:
    """Reads and caches the daemon's state file."""

    def __init__(self, path: Path | None = None, clock=time.time) -> None:
        self.path = path or state_module.default_path()
        self._clock = clock
        self._parse_failures = 0
        self._signature: tuple[int, int, int] | None = None
        self.state: dict | None = None
        self.error: str = ""

    def read(self) -> dict | None:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0))
            if signature == self._signature:
                return self.state
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            # "Not running yet" is the normal state right after install and
            # must not read as a fault.
            self.error = (
                "Cannot read state file" if self.state else "Waiting for poketokend…"
            )
            return self.state

        try:
            parsed = json.loads(raw)
        except ValueError:
            self._parse_failures += 1
            if self._parse_failures >= PARSE_FAILURES_BEFORE_REPORTING:
                self.error = "state.json is not valid JSON"
            return self.state

        if not isinstance(parsed, dict):
            return self.state

        self._parse_failures = 0
        self._signature = signature
        self.state = parsed
        self.error = ""
        return self.state

    def age_seconds(self) -> float | None:
        updated_at = (self.state or {}).get("updated_at")
        if not updated_at:
            return None
        return max(0.0, self._clock() - updated_at)

    def is_stale(self) -> bool:
        age = self.age_seconds()
        return age is not None and age > STALE_AFTER_SECONDS

    def text(self, key: str) -> str:
        """One string from the daemon's catalogue, then the local catalogue.

        Normally the daemon resolves every string and ships it.  During an
        update, however, the newly installed UI can briefly read state written
        by the older daemon.  Falling back locally keeps newly added labels
        translated until the daemon restarts and publishes its new catalogue.
        """
        if self.state is None:
            return key
        state = self.state
        translated = (state.get("strings") or {}).get(key)
        if translated is not None:
            return translated
        language = (state.get("config") or {}).get("language", "en")
        return l10n.t(key, language)

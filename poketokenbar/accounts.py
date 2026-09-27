"""Which Claude logins this machine has — ports the discovery half of e5b4800.

Claude Code keeps one login per config folder, so two accounts side by side are
two folders: the default one, whatever `CLAUDE_CONFIG_DIR` points at, and the
`~/.claude-work` style folders people make for a second login. Usage logs carry
no account marker, but limits do, so each folder's limits are read on their own.

Only folders Claude Code is actually logged in to count: a folder without
credentials has nothing to ask the endpoint with.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CREDENTIALS = ".credentials.json"
# The shapes people give a second login. Claude Code itself only ever writes
# the default folder or $CLAUDE_CONFIG_DIR; these are conventions.
PATTERNS = (".claude-*", ".claude_*")


@dataclass(frozen=True, slots=True)
class ClaudeAccount:
    """One logged-in config folder."""

    id: str
    config_dir: Path
    is_default: bool

    @property
    def credentials(self) -> Path:
        return self.config_dir / CREDENTIALS

    @property
    def account_file(self) -> Path:
        """Claude Code's global config, which names the logged-in account."""
        return self.config_dir / ".claude.json"


def _logged_in(directory: Path) -> bool:
    try:
        return (directory / CREDENTIALS).is_file()
    except OSError:
        return False


def default_dir(home: Path | None = None, env=None) -> Path:
    """The folder the rest of the app already means by "the Claude account"."""
    values = os.environ if env is None else env
    configured = (values.get("CLAUDE_CONFIG_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return (home or Path.home()) / ".claude"


def discover(home: Path | None = None, env=None, extra=()) -> list[ClaudeAccount]:
    """Every logged-in Claude config folder, the default one first.

    `extra` is the folders someone listed in the settings, for a login that
    follows neither convention. The default folder is always first and always
    listed, logged in or not: it is the account every other part of the app
    already reports on, and dropping it when the login expires would take the
    limits section away instead of saying the login needs renewing.
    """
    home = home or Path.home()
    default = default_dir(home, env)
    out = [ClaudeAccount(id="default", config_dir=default, is_default=True)]
    seen = {_resolved(default)}

    candidates: list[Path] = []
    for pattern in PATTERNS:
        try:
            candidates.extend(sorted(home.glob(pattern)))
        except OSError:
            continue
    candidates.extend(Path(str(one)).expanduser() for one in extra)

    for directory in candidates:
        key = _resolved(directory)
        if key in seen or not directory.is_dir() or not _logged_in(directory):
            continue
        seen.add(key)
        out.append(ClaudeAccount(id=directory.name, config_dir=directory, is_default=False))
    return out


def _resolved(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)

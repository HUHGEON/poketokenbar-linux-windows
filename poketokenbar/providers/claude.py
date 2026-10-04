"""Claude Code usage — ports the Claude half of LocalUsageReader.swift.

Rule: keep `type == "assistant"` rows, sum the four token fields of
`message.usage`, deduplicate on `(message.id, requestId)` keeping the entry
with the LARGEST total, and bucket by local date from `timestamp`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from datetime import date as _date
from datetime import datetime
from pathlib import Path

from .. import pricing
from ..cache import ScanCache
from ..models import DailyUsage, Entry, ProviderEnrichment

from .base import ScanningProvider, dedup_keep_max, loads as _loads, number, parse_iso, to_int as _int

# Re-exported under their original names: the tests and the Codex provider
# already import them from here.
_parse_timestamp = parse_iso


def parse_line(line: str) -> Entry | None:
    try:
        obj = _loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    date = _parse_timestamp(obj.get("timestamp", ""))
    if date is None:
        return None
    return Entry(
        id=f"{msg.get('id') or ''}|{obj.get('requestId') or ''}",
        date=date,
        local_day=date.astimezone().strftime("%Y-%m-%d"),
        model=msg.get("model") or "unknown",
        # Only top-level fields. usage["iterations"] repeats these numbers.
        input=_int(usage.get("input_tokens")),
        output=_int(usage.get("output_tokens")),
        cache_write=_int(usage.get("cache_creation_input_tokens")),
        cache_read=_int(usage.get("cache_read_input_tokens")),
    )


def parse_file(path: Path) -> list[Entry]:
    out: list[Entry] = []
    ledger: dict[str, float] = {}
    session = path.parent.parent.name if path.parent.name == "subagents" else path.stem
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"cost-state"' in line:
                    try:
                        obj = _loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict) or obj.get("type") != "cost-state":
                        continue
                    usage = obj.get("modelUsage")
                    if isinstance(usage, dict):
                        costs: dict[str, float] = {}
                        for model, fields in usage.items():
                            cost = number(fields.get("costUSD")) if isinstance(fields, dict) else None
                            if cost is not None and cost >= 0:
                                key = model.split("[", 1)[0]
                                costs[key] = costs.get(key, 0.0) + cost
                        if costs:
                            ledger = costs
                    continue
                # Substring prefilter before JSON decode — the cold scan reads
                # hundreds of MB and most lines are not assistant turns.
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                entry = parse_line(line)
                if entry is not None:
                    entry.session_id = session
                    out.append(entry)
    except OSError:
        return []
    out = dedup_keep_max(out)
    for model, cost in ledger.items():
        matching = [e for e in out if e.total > 0 and e.model.split("[", 1)[0] == model]
        total = sum(e.total for e in matching)
        remaining = cost
        for index, entry in enumerate(matching):
            share = remaining if index == len(matching) - 1 else cost * entry.total / total
            entry.explicit_cost = max(0.0, share)
            remaining -= share
    return out


def project_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    """Existing Claude project roots, symlink-deduplicated.

    macOS also probes ~/Library/Application Support/Claude for Claude Desktop
    embedded sessions. That path cannot exist on Linux, so it is omitted rather
    than branched on.
    """
    home = home or Path.home()
    env = os.environ if env is None else env

    candidates = [home / ".claude" / "projects", home / ".config" / "claude" / "projects"]
    configured = env.get("CLAUDE_CONFIG_DIR")
    if configured:
        candidates.extend(Path(part.strip()).expanduser() / "projects"
                          for part in configured.split(",") if part.strip())

    from ..claude_accounts import discover_roots
    candidates.extend(root / "projects" for root in discover_roots(home=home, env=env))

    seen: set[Path] = set()
    roots: list[Path] = []
    for path in candidates:
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(path)
    return roots


def jsonl_files(root: Path) -> Iterator[Path]:
    """Every *.jsonl under root, including inside hidden directories."""
    yield from root.rglob("*.jsonl")


class ClaudeProvider(ScanningProvider):
    """Claude Code local usage."""

    id = "claude_code"
    display_name = "Claude Code"
    reports_cost = True
    # Bump when parse_line changes shape, to invalidate cached blobs.
    PARSER_VERSION = 2

    def configure_account_roots(self, roots) -> None:
        """Accept a mapping or a callback so config reloads take effect immediately."""
        self._account_roots = roots

    def curated_roots(self) -> list[Path]:
        roots = getattr(self, "_account_roots", {})
        roots = roots() if callable(roots) else roots
        return project_roots(home=self._home) + [Path(root) / "projects" for root in roots.values()]

    def fetch_accounts(self, account_roots: dict[str, Path], today: str | None = None,
                       entries: list[Entry] | None = None) -> dict[str, DailyUsage]:
        day = today or _date.today().strftime("%Y-%m-%d")
        groups = attribute_entries(self.scan_entries() if entries is None else entries, account_roots)
        return {account: self.aggregate_daily(day, [e for e in turns if e.local_day == day])
                for account, turns in groups.items()}

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_file(path)


def prompt_history(config_root: Path) -> dict[str, list[datetime]]:
    """Read only session and prompt timestamps; discard prompt content."""
    from .sqlite_source import date_value
    prompts: dict[str, list[datetime]] = {}
    try:
        with (config_root / "history.jsonl").open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                # Do not cache a trailing record while the CLI is writing it.
                if not line.endswith("\n"):
                    continue
                try:
                    obj = _loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                session = obj.get("sessionId")
                stamp = obj.get("timestamp")
                when = parse_iso(stamp) if isinstance(stamp, str) else date_value(stamp)
                if isinstance(session, str) and session and when is not None:
                    prompts.setdefault(session, []).append(when)
    except OSError:
        return {}
    return {session: sorted(times) for session, times in prompts.items()}


def account_owner(entry: Entry, histories: dict[str, dict[str, list[datetime]]]) -> str | None:
    """Latest prompt before the original turn owns it; ties favor account order."""
    latest = earliest = None
    at = entry.date.astimezone()
    for account, sessions in histories.items():
        for session in entry.claude_session_ids:
            for raw in sessions.get(session, []):
                when = raw.astimezone()
                if earliest is None or when < earliest[0]:
                    earliest = (when, account)
                if when <= at and (latest is None or when > latest[0]):
                    latest = (when, account)
    found = latest or earliest
    return found[1] if found else None


def attribute_entries(entries: list[Entry], account_roots: dict[str, Path]) -> dict[str, list[Entry]]:
    """Account-id buckets; the empty key retains unattributed usage."""
    histories = {account: prompt_history(root) for account, root in account_roots.items()}
    groups: dict[str, list[Entry]] = {account: [] for account in account_roots}
    groups[""] = []
    for entry in entries:
        groups.setdefault(account_owner(entry, histories) or "", []).append(entry)
    return groups

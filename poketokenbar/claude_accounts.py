"""Discover independent Claude config folders and cache each account separately."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from . import limits
from .limits_source import LimitsSource


def account_id(root: Path) -> str:
    normalized = os.path.normcase(str(Path(root).expanduser().resolve()))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def discover_roots(home: Path | None = None, env=None, additional: str = "") -> list[Path]:
    home = home or Path.home()
    env = os.environ if env is None else env
    excluded = {(home / ".claude").resolve(), (home / ".config" / "claude").resolve()}
    candidates = []
    for raw in (env.get("CLAUDE_CONFIG_DIR", ""), additional):
        for part in re.split(r"[,\n]", raw or ""):
            part = part.strip()
            if part == "~" or part.startswith("~/") or part.startswith("~\\"):
                path = home / part[2:] if len(part) > 1 else home
            else:
                path = Path(part).expanduser()
            if part and path.is_absolute():
                candidates.append(path)
    try:
        for root in sorted(home.iterdir()):
            if root.name.startswith((".claude-", ".claude_")) and limits.read_account(root / ".claude.json"):
                candidates.append(root)
    except OSError:
        pass
    out, seen = [], set(excluded)
    for path in candidates:
        resolved = path.resolve()
        if path.is_dir() and resolved not in seen:
            out.append(resolved)
            seen.add(resolved)
    return out


class ClaudeAccountsSource:
    """The old primary get() contract plus explicit snapshots for all account tabs."""
    def __init__(self, state_dir: Path, home: Path | None = None, env=None, http=None):
        self.state_dir = Path(state_dir)
        self.home = home or Path.home()
        self.env = os.environ if env is None else env
        self.http = http
        self.account_statuses = {}
        self.account_errors = {}
        self.account_metadata = {}
        self._sources = {}
        self._fingerprints = {}
        self.last_error = ""
        self.configure("")

    def configure(self, additional_config_dirs: str = "") -> None:
        roots = [("default", self.home / ".claude")]
        roots += [(account_id(root), root) for root in discover_roots(self.home, self.env, additional_config_dirs)]
        metadata = {}
        for identity, root in roots:
            account_path = self.home / ".claude.json" if identity == "default" else root / ".claude.json"
            metadata[identity] = {"id": identity, "root": str(root), "account": limits.read_account(account_path)}
            if identity not in self._sources:
                self._sources[identity] = LimitsSource(fetch=lambda r=root, i=identity: self._fetch(r, i))
        self.account_metadata = metadata
        for identity, row in metadata.items():
            row["has_session_key"] = self.session_key_store(identity).load() is not None
            row["stale"] = bool(self.account_errors.get(identity))
        self._sources = {key: source for key, source in self._sources.items() if key in metadata}
        self.account_statuses = {key: status for key, status in self.account_statuses.items() if key in metadata}
        self.account_errors = {key: error for key, error in self.account_errors.items() if key in metadata}

    def session_key_store(self, identity: str = "default"):
        from .session_key import SessionKeyStore
        root = Path(self.account_metadata[identity]["root"])
        return SessionKeyStore(self.state_dir, None if identity == "default" else root)

    def _fetch(self, root: Path, identity: str):
        from .session_key import SessionKeyProvider
        store = self.session_key_store(identity)
        key_error = None
        status = None
        if store.load():
            try:
                account = self.account_metadata[identity]["account"]
                provider = SessionKeyProvider(store, preferred_organization_id=account.get("organization_id"),
                                              **({"http": self.http} if self.http else {}))
                status = provider.fetch()
            except limits.LimitsError as exc:
                key_error = exc
        credential = None
        if status is None:
            try:
                credential = limits.read_credentials(root / ".credentials.json")
                if self.http:
                    from urllib.request import Request
                    payload = self.http(Request(limits.USAGE_URL, headers={
                        "Authorization": f"Bearer {credential.access_token}", "anthropic-beta": limits.OAUTH_BETA}))
                else:
                    payload = limits.fetch(credential)
                status = limits.parse(payload)
            except limits.LimitsError as exc:
                raise key_error or exc
        if credential is None:
            try:
                credential = limits.read_credentials(root / ".credentials.json")
            except limits.LimitsError:
                pass
        if credential:
            status.subscription_type = credential.subscription_type
            status.rate_limit_tier = credential.rate_limit_tier
        account_path = self.home / ".claude.json" if identity == "default" else root / ".claude.json"
        status.account = limits.read_account(account_path)
        return status

    def invalidate(self) -> None:
        for source in self._sources.values():
            source.invalidate()

    def get(self):
        for identity, source in self._sources.items():
            root = Path(self.account_metadata[identity]["root"])
            identity_file = self.home / ".claude.json" if identity == "default" else root / ".claude.json"
            paths = (root / ".credentials.json", identity_file, self.session_key_store(identity).path)
            fingerprint = []
            for path in paths:
                try:
                    stat = path.stat()
                    fingerprint.append((stat.st_mtime_ns, stat.st_size))
                except OSError:
                    fingerprint.append(None)
            fingerprint = tuple(fingerprint)
            if identity in self._fingerprints and fingerprint != self._fingerprints[identity]:
                source.invalidate(clear_cache=True)
            self._fingerprints[identity] = fingerprint
            self.account_metadata[identity]["account"] = limits.read_account(identity_file)
            key_before = self.session_key_store(identity).load()
            self.account_statuses[identity] = source.get()
            self.account_errors[identity] = source.last_error
            key_after = self.session_key_store(identity).load()
            if key_before and key_after and key_before.key == key_after.key and key_before != key_after:
                # Organization discovery persists its choice during fetch. That
                # write does not represent a different login or a stale quota.
                try:
                    stat = paths[-1].stat()
                    self._fingerprints[identity] = (*fingerprint[:-1], (stat.st_mtime_ns, stat.st_size))
                except OSError:
                    pass
            self.account_metadata[identity]["has_session_key"] = key_after is not None
            self.account_metadata[identity]["stale"] = bool(source.last_error and self.account_statuses[identity])
        self.last_error = self.account_errors.get("default", "")
        return self.account_statuses.get("default")

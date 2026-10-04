"""Per-account Claude browser session keys and organization-aware official limits."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request

from . import limits
from .limits_http import request_json


class SessionKeyError(limits.AuthExpiredError):
    """The saved browser key must be replaced in Settings."""


@dataclass(slots=True)
class SessionKeyCredential:
    key: str
    organization_id: str | None = None


class SessionKeyStore:
    def __init__(self, directory: Path, config_root: Path | None = None):
        from .claude_accounts import account_id
        suffix = f"-{account_id(config_root)}" if config_root else ""
        self.path = Path(directory) / f"session-key{suffix}.json"

    @staticmethod
    def normalize(raw: str) -> str:
        key = raw.strip()
        if not 40 <= len(key) <= 2048 or not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]+", key):
            raise ValueError("Enter a valid Claude session key")
        return key

    def load(self) -> SessionKeyCredential | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            key = self.normalize(raw["key"])
            organization = raw.get("organization_id", raw.get("organizationID"))
            return SessionKeyCredential(key, organization if isinstance(organization, str) and organization else None)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save(self, key: str, organization_id: str | None = None) -> None:
        credential = {"key": self.normalize(key), "organization_id": organization_id or None}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".session-key-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(credential, stream)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class SessionKeyProvider:
    def __init__(self, store: SessionKeyStore, http=request_json, preferred_organization_id=None):
        self.store = store
        self.http = http
        self.preferred_organization_id = preferred_organization_id

    def _get(self, path: str, key: str):
        request = Request("https://claude.ai/api/" + path, headers={
            "Cookie": "sessionKey=" + key,
            "Accept": "application/json",
            "Origin": "https://claude.ai",
            "Referer": "https://claude.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        })
        try:
            return self.http(request)
        except limits.HTTPStatusError as exc:
            if exc.status == 401:
                raise SessionKeyError("Claude session key expired; replace it in Settings") from exc
            raise

    def _usage(self, organization_id: str, key: str):
        return limits.parse(self._get(f"organizations/{quote(organization_id, safe='')}/usage", key))

    def organizations(self, key: str) -> list[dict]:
        key = self.store.normalize(key)
        try:
            rows = self._get("organizations", key)
        except limits.HTTPStatusError as exc:
            if exc.status == 403:
                raise SessionKeyError("Claude session key expired; replace it in Settings") from exc
            raise
        if not isinstance(rows, list):
            raise limits.LimitsError("invalid Claude organizations response")
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("uuid"), str)]
        candidates = [row for row in rows if "capabilities" not in row or "chat" in (row.get("capabilities") or [])]
        out = []
        for row in candidates or rows:
            try:
                status = self._usage(row["uuid"], key)
            except limits.HTTPStatusError:
                continue
            windows = [status.session, status.weekly] + [entry.window for entry in status.scoped]
            out.append({"id": row["uuid"], "name": row.get("name") or row["uuid"],
                        "has_usage": any(w and (w.utilization > 0 or w.resets_at) for w in windows),
                        "limits": status})
        return out

    def fetch(self) -> limits.LimitStatus:
        credential = self.store.load()
        if credential is None:
            raise SessionKeyError("No Claude session key configured")
        if credential.organization_id:
            try:
                return self._usage(credential.organization_id, credential.key)
            except limits.HTTPStatusError as exc:
                if exc.status != 403:
                    raise
        candidates = self.organizations(credential.key)
        if not candidates:
            raise SessionKeyError("Claude session key has no accessible organization")
        chosen = next((row for row in candidates if row["id"] == self.preferred_organization_id), None)
        chosen = chosen or next((row for row in candidates if row["has_usage"]), candidates[0])
        self.store.save(credential.key, chosen["id"])
        return chosen["limits"]

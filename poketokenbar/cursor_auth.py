"""One in-memory refreshed Cursor login shared by usage and quota requests.

Cursor remains the sole owner of its SQLite credentials. Sources include the
selected root, so neither refresh tokens nor cached grants cross login roots.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from threading import RLock
from urllib.parse import unquote
from urllib.request import Request

from . import limits
from .limits_http import request_json

TOKEN_URL = "https://api2.cursor.sh/oauth/token"
CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"


@dataclass(frozen=True)
class Source:
    root: str | None
    access_token: str
    refresh_token: str | None


@dataclass(frozen=True)
class Credential:
    source: Source
    access_token: str
    refresh_token: str | None


_lock = RLock()
_refreshed: Credential | None = None


def _selected(home=None, env=None) -> Source | None:
    import os
    from .cursor_limits import read_auth
    env = os.environ if env is None else env
    if env.get("CURSOR_USAGE_API") == "0":
        return None
    override = (env.get("CURSOR_SESSION_TOKEN") or "").strip()
    if override:
        return Source(None, override, None)
    auth = read_auth(home, env)
    token = auth.get("accessToken")
    if not token:
        return None
    return Source(auth.get("root") or str(home or "default"), token, auth.get("refreshToken"))


def current(home=None, env=None) -> Credential | None:
    global _refreshed
    source = _selected(home, env)
    with _lock:
        if source is None:
            _refreshed = None
            return None
        if _refreshed and _refreshed.source == source:
            return _refreshed
        _refreshed = None
        return Credential(source, source.access_token, source.refresh_token)


def refresh(rejected: Credential, *, home=None, env=None, http=request_json) -> Credential:
    global _refreshed
    with _lock:
        selected = current(home, env)
        if selected is None or selected.source != rejected.source or selected.source.root is None:
            raise limits.AuthExpiredError("Cursor login changed or expired; sign in to Cursor")
        if selected.access_token != rejected.access_token:
            return selected
        if not selected.refresh_token:
            raise limits.AuthExpiredError("Cursor login expired; sign in to Cursor")
        try:
            payload = http(Request(TOKEN_URL, data=json.dumps({
                "grant_type": "refresh_token", "client_id": CLIENT_ID,
                "refresh_token": selected.refresh_token}).encode(), headers={"Content-Type": "application/json"}))
        except limits.HTTPStatusError as exc:
            if exc.status in (400, 401, 403):
                raise limits.AuthExpiredError("Cursor login expired; sign in to Cursor") from exc
            raise
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token.strip() or payload.get("shouldLogout") is True:
            raise limits.AuthExpiredError("Cursor login expired; sign in to Cursor")
        if _selected(home, env) != selected.source:
            raise limits.AuthExpiredError("Cursor login changed during refresh")
        replacement = payload.get("refresh_token")
        replacement = replacement.strip() if isinstance(replacement, str) else ""
        _refreshed = Credential(selected.source, token.strip(), replacement or selected.refresh_token)
        return _refreshed


def bearer(token: str) -> str:
    return unquote(token).split("::", 1)[-1]

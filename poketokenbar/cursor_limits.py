"""Cursor dashboard allowance, authenticated by its existing local IDE login."""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request

from . import limits, cursor_auth
from .limits_http import request_json
from .limits_source import LimitsSource
from .providers.cursor import user_data_dirs

USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
TOKEN_URL = cursor_auth.TOKEN_URL
CLIENT_ID = cursor_auth.CLIENT_ID


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _epoch(raw):
    try:
        seconds = float(raw)
        if seconds > 1e12:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds > 1e9 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_status(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        raise limits.LimitsError("invalid Cursor quota response")
    usage = payload.get("planUsage")
    if not isinstance(usage, dict):
        return None
    percent = _number(usage.get("totalPercentUsed"))
    allowance, included, remaining = (_number(usage.get(key)) for key in ("limit", "includedSpend", "remaining"))
    if percent is None and allowance and allowance > 0 and included is not None:
        percent = included / allowance * 100
    if percent is None and not (allowance and allowance > 0):
        return None
    return {"utilization": percent, "resets_at": _epoch(payload.get("billingCycleEnd")),
            "starts_at": _epoch(payload.get("billingCycleStart")),
            "remaining_dollars": remaining / 100 if remaining is not None else None,
            "limit_dollars": allowance / 100 if allowance is not None else None,
            "display_message": payload.get("displayMessage")}


def read_auth(home: Path | None = None, env=None) -> dict:
    env = os.environ if env is None else env
    for root in user_data_dirs(home=home, env=env):
        path = root / "state.vscdb"
        if not path.is_file():
            continue
        try:
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as connection:
                rows = connection.execute(
                    "SELECT key, value FROM ItemTable WHERE key IN (?, ?)",
                    ("cursorAuth/accessToken", "cursorAuth/refreshToken"))
                auth = {key.rsplit("/", 1)[-1]: value.strip() for key, value in rows if isinstance(value, str) and value.strip()}
                if auth.get("accessToken"):
                    return {**auth, "root": str(root.resolve())}
        except (OSError, sqlite3.Error):
            continue
    return {}


class CursorProvider:
    def __init__(self, home: Path | None = None, env=None, http=request_json):
        self.home = home
        self.env = os.environ if env is None else env
        self.http = http

    def _usage(self, token):
        return parse_status(self.http(Request(USAGE_URL, data=b"{}", headers={
            "Content-Type": "application/json", "Connect-Protocol-Version": "1",
            "Authorization": f"Bearer {token}"})))

    def fetch(self):
        if self.env.get("CURSOR_USAGE_API") == "0":
            return None
        credential = cursor_auth.current(self.home, self.env)
        if credential is None:
            return None
        try:
            return self._usage(cursor_auth.bearer(credential.access_token))
        except limits.HTTPStatusError as exc:
            if exc.status not in (401, 403):
                raise
            refreshed = cursor_auth.refresh(credential, home=self.home, env=self.env, http=self.http)
            return self._usage(cursor_auth.bearer(refreshed.access_token))



class CursorLimitsSource(LimitsSource):
    def __init__(self, home: Path | None = None, env=None, http=request_json, **kwargs):
        self.provider = CursorProvider(home, env, http)
        super().__init__(fetch=self.provider.fetch, **kwargs)

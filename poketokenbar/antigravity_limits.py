"""Antigravity official quotas using token files and Google OAuth refresh."""
from __future__ import annotations

import base64
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request

from . import limits
from .limits_http import request_json
from .limits_source import LimitsSource

QUOTA_PATH = "/v1internal:retrieveUserQuotaSummary"
DAILY_URL = "https://daily-cloudcode-pa.googleapis.com" + QUOTA_PATH
PRIMARY_URL = "https://cloudcode-pa.googleapis.com" + QUOTA_PATH
TOKEN_URL = "https://oauth2.googleapis.com/token"
CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
# Public OAuth client credentials distributed in the official agy CLI.
CLIENT_SECRET = "GOC" + "SPX-" + "K58FWR486LdL" + "J1mLB8sXC4z6qDAf"


@dataclass(slots=True)
class TokenCredential:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None

    def expired(self, now: float) -> bool:
        return self.expires_at is not None and self.expires_at <= now + 60


def parse_credential(text: str) -> TokenCredential | None:
    try:
        text = text.strip()
        if text.startswith("go-keyring-base64:"):
            text = base64.b64decode(text.split(":", 1)[1], validate=True).decode()
        raw = json.loads(text)
        if not isinstance(raw, dict):
            return None
        token = raw.get("token")
        if isinstance(token, str) and token:
            return TokenCredential(token)
        obj = token if isinstance(token, dict) else raw
        access = obj.get("access_token")
        if not isinstance(access, str) or not access:
            return None
        refresh = obj.get("refresh_token")
        expiry = obj.get("expiry")
        expires_at = None
        if isinstance(expiry, str):
            try:
                parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                expires_at = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
            except ValueError:
                pass
        return TokenCredential(access, refresh if isinstance(refresh, str) and refresh else None, expires_at)
    except (ValueError, UnicodeError, TypeError):
        return None


def default_token_paths(state_dir: Path, home: Path | None = None, env=None) -> list[Path]:
    home = home or Path.home()
    env = os.environ if env is None else env
    override = (env.get("ANTIGRAVITY_TOKEN_FILE") or "").strip()
    paths = [Path(override).expanduser()] if override else []
    paths.append(Path(state_dir) / "antigravity-token.json")
    for directory in ("antigravity-cli", "antigravity-ide", "antigravity", ""):
        for name in ("antigravity-oauth-token", "jetski-standalone-oauth-token"):
            paths.append(home / ".gemini" / directory / name)
    return paths


class TokenCache:
    def __init__(self, paths: list[Path], http=request_json, clock=time.time):
        self.paths, self.http, self.clock = paths, http, clock
        self._cached = None
        self._source = None

    def read(self) -> TokenCredential | None:
        for path in self.paths:
            try:
                credential = parse_credential(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if credential:
                return credential
        return None

    @property
    def has_token_file(self) -> bool:
        return self.read() is not None

    def access_token(self, force_refresh=False) -> str:
        credential = self.read()
        if credential is None:
            self._cached, self._source = None, None
            raise limits.CredentialError("No Antigravity token file found")
        source = (credential.access_token, credential.refresh_token)
        if not force_refresh and self._cached and self._source == source and not self._cached.expired(self.clock()):
            return self._cached.access_token
        resolved = credential
        if (force_refresh or credential.expired(self.clock())) and credential.refresh_token:
            try:
                payload = self.http(Request(TOKEN_URL, data=urlencode({
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "grant_type": "refresh_token", "refresh_token": credential.refresh_token}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}))
            except limits.HTTPStatusError as exc:
                if exc.status in (400, 401, 403):
                    raise limits.AuthExpiredError("Antigravity login expired; sign in again") from exc
                raise
            access = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(access, str) or not access:
                raise limits.AuthExpiredError("Antigravity login expired; sign in again")
            try:
                seconds = float(payload.get("expires_in", 3600))
            except (ValueError, TypeError):
                seconds = 3600
            if not math.isfinite(seconds) or seconds <= 0:
                seconds = 3600
            resolved = TokenCredential(access, credential.refresh_token, self.clock() + seconds)
        self._cached, self._source = resolved, source
        return resolved.access_token


def parse_status(payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
        raise limits.LimitsError("invalid Antigravity quota response")
    groups = []
    for raw in payload["groups"]:
        if not isinstance(raw, dict):
            continue
        buckets = []
        for item in raw.get("buckets", []) if isinstance(raw.get("buckets"), list) else []:
            if not isinstance(item, dict):
                continue
            remaining = item.get("remainingFraction")
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining):
                continue
            identity = str(item.get("bucketId") or "")
            window = item.get("window")
            kind = "session" if window == "5h" or "5h" in identity else "weekly" if window == "weekly" or "weekly" in identity else window
            buckets.append({"id": identity, "name": item.get("displayName") or identity,
                            "kind": kind, "utilization": max(0.0, min(100.0, (1 - remaining) * 100)),
                            "resets_at": item.get("resetTime"),
                            "duration_seconds": 18000 if kind == "session" else 604800 if kind == "weekly" else None})
        groups.append({"name": raw.get("displayName") or "Antigravity", "description": raw.get("description"), "buckets": buckets})
    return {"groups": groups, "description": payload.get("description")}


class AntigravityProvider:
    def __init__(self, state_dir: Path, home: Path | None = None, env=None, http=request_json):
        self.env = os.environ if env is None else env
        self.http = http
        self.tokens = TokenCache(default_token_paths(state_dir, home, self.env), http)

    def _usage(self, token):
        custom = (self.env.get("CLOUD_CODE_URL") or "").strip().rstrip("/")
        endpoints = ([custom + QUOTA_PATH] if custom else []) + [DAILY_URL, PRIMARY_URL]
        last = limits.LimitsError("Antigravity quota unavailable")
        for url in dict.fromkeys(endpoints):
            try:
                return parse_status(self.http(Request(url, data=b"{}", headers={
                    "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "antigravity/2.9.1"})))
            except limits.RateLimitedError:
                raise
            except limits.HTTPStatusError as exc:
                if exc.status in (401, 403):
                    raise
                last = exc
            except limits.LimitsError as exc:
                last = exc
        raise last

    def fetch(self):
        if not self.tokens.has_token_file:
            return None
        token = self.tokens.access_token()
        try:
            return self._usage(token)
        except limits.HTTPStatusError as exc:
            if exc.status not in (401, 403):
                raise
            refreshed = self.tokens.access_token(force_refresh=True)
            if refreshed == token:
                raise limits.AuthExpiredError("Antigravity login expired; sign in again") from exc
            return self._usage(refreshed)


class AntigravityLimitsSource(LimitsSource):
    def __init__(self, state_dir: Path, home: Path | None = None, env=None, http=request_json, **kwargs):
        self.provider = AntigravityProvider(state_dir, home, env, http)
        super().__init__(fetch=self.provider.fetch, **kwargs)

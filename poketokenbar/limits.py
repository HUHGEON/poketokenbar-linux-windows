"""Official Claude 5-hour / weekly limits — ports OAuthLimitsProvider.swift.

On macOS the OAuth token lives in the Keychain, which is why the Swift code
carries LAContext, UI-fail policies, and a user-facing opt-out. On Linux Claude
Code writes ~/.claude/.credentials.json in plaintext, so that entire subsystem
reduces to reading a file.

Limits are best effort: a failure here hides the limits section and never
affects the token counts, which come from local logs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"


class LimitsError(Exception):
    """Base for every limits failure."""


class CredentialError(LimitsError):
    """Credentials missing or unreadable."""


class NeedsLoginError(LimitsError):
    """Credentials exist but hold no Claude account OAuth — re-login required."""


class AuthExpiredError(LimitsError):
    """The endpoint rejected the token (401/403)."""


class NetworkError(LimitsError):
    """The endpoint could not be reached at all: no DNS, no route, a timeout.

    Kept apart from the other failures because it is the one that fixes
    itself — most often it is the daemon starting before the network has,
    right after login — so it is worth retrying soon and not worth quoting.
    """


class RateLimitedError(LimitsError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


@dataclass(slots=True)
class Credential:
    access_token: str
    expires_at: int | None = None
    subscription_type: str | None = None
    rate_limit_tier: str | None = None


@dataclass(slots=True)
class LimitWindow:
    utilization: float
    resets_at: str | None = None
    severity: str | None = None


@dataclass(slots=True)
class LimitStatus:
    session: LimitWindow | None = None
    weekly: LimitWindow | None = None
    subscription_type: str | None = None
    rate_limit_tier: str | None = None
    account: dict | None = None


def _config_dir(env) -> Path | None:
    configured = ((os.environ if env is None else env).get("CLAUDE_CONFIG_DIR") or "").strip()
    return Path(configured).expanduser() if configured else None


def default_credentials_path(env=None) -> Path:
    """Where Claude Code keeps its login.

    Under $CLAUDE_CONFIG_DIR when that is set, as the usage scan already
    assumes; reading ~/.claude regardless meant limits for a different login,
    or none, than the usage beside them. The Linux counterpart of upstream's
    fixes for resolving the right account (e81e620, c9c016d).
    """
    configured = _config_dir(env)
    base = configured if configured is not None else Path.home() / ".claude"
    return base / ".credentials.json"


def default_account_path(env=None) -> Path:
    """Claude Code's global config, which names the logged-in account.

    With $CLAUDE_CONFIG_DIR set Claude Code writes it inside that directory.
    """
    configured = _config_dir(env)
    if configured is not None:
        return configured / ".claude.json"
    return Path.home() / ".claude.json"


def read_account(path: Path | None = None) -> dict:
    """Who the limits belong to.

    Session logs carry no account marker, so token totals from several accounts
    on one machine are indistinguishable and get summed. Limits, by contrast,
    come from whichever account is currently logged in. Surfacing the account
    keeps that difference visible instead of silently misleading.
    """
    path = path or default_account_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    account = raw.get("oauthAccount")
    if not isinstance(account, dict):
        return {}
    return {
        "uuid": account.get("accountUuid") or "",
        "email": account.get("emailAddress") or "",
        "display_name": account.get("displayName") or account.get("fullName") or "",
        "organization": account.get("organizationName") or "",
    }


def read_credentials(path: Path | None = None) -> Credential:
    path = path or default_credentials_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CredentialError("credentials file is not an object")

    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        # Only MCP server OAuth present — observed on Claude Code 2.1.x.
        raise NeedsLoginError("no Claude account OAuth in credentials")

    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        raise NeedsLoginError("credentials hold no access token")

    return Credential(
        access_token=token,
        expires_at=oauth.get("expiresAt"),
        subscription_type=oauth.get("subscriptionType"),
        rate_limit_tier=oauth.get("rateLimitTier"),
    )


def retry_after_seconds(headers) -> float | None:
    """Seconds form only, capped at an hour. HTTP-date form yields None."""
    raw = headers.get("Retry-After") if headers else None
    if not raw:
        return None
    try:
        seconds = float(str(raw).strip())
    except ValueError:
        return None  # HTTP-date form — fall back to the caller's default
    if seconds <= 0:
        return None
    return min(seconds, 3600.0)


def _window(util, resets_at, severity=None) -> LimitWindow | None:
    if util is None:
        return None
    try:
        return LimitWindow(float(util), resets_at, severity)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> LimitStatus:
    """Prefer the newer limits[] array, falling back to legacy fields.

    A missing window stays None rather than becoming 0.0 — 0% and "unknown"
    must not render the same, since 0% reads as plenty of headroom.
    """
    status = LimitStatus()

    entries = payload.get("limits")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            window = _window(
                entry.get("percent"), entry.get("resets_at"), entry.get("severity")
            )
            if window is None:
                continue
            if entry.get("kind") == "session":
                status.session = window
            elif entry.get("kind") == "weekly_all":
                status.weekly = window

    if status.session is None:
        legacy = payload.get("five_hour")
        if isinstance(legacy, dict):
            status.session = _window(legacy.get("utilization"), legacy.get("resets_at"))
    if status.weekly is None:
        legacy = payload.get("seven_day")
        if isinstance(legacy, dict):
            status.weekly = _window(legacy.get("utilization"), legacy.get("resets_at"))

    return status


def level(utilization: float, warn: float = 80, crit: float = 95) -> str:
    """Colour band for a utilization percentage.

    A boundary value belongs to the more severe band: 80 with warn=80 is a
    warning, not still-fine.
    """
    if utilization >= crit:
        return "crit"
    if utilization >= warn:
        return "warn"
    return "ok"


def windows(status: LimitStatus | None, mode: str) -> list[LimitWindow]:
    """The windows the panel should show, in display order."""
    if status is None:
        return []
    out: list[LimitWindow] = []
    if mode in ("session", "both") and status.session is not None:
        out.append(status.session)
    if mode in ("weekly", "both") and status.weekly is not None:
        out.append(status.weekly)
    return out


def format_percent(value: float) -> str:
    return f"{value:.0f}%" if value == round(value) else f"{value:.1f}%"


def _format(window: LimitWindow | None, label: str) -> str:
    if window is None:
        return ""
    value = window.utilization
    text = f"{value:.0f}%" if value == round(value) else f"{value:.1f}%"
    return f"{label} {text}"


def panel_text(status: LimitStatus | None, mode: str) -> str:
    """Panel string, e.g. '5h 91% · 7d 17%'."""
    if status is None:
        return ""
    parts: list[str] = []
    if mode in ("session", "both"):
        parts.append(_format(status.session, "5h"))
    if mode in ("weekly", "both"):
        parts.append(_format(status.weekly, "7d"))
    return " · ".join(p for p in parts if p)


def fetch(credential: Credential, timeout: float = 15.0) -> dict:
    """Call the usage endpoint. Raises a LimitsError subclass on failure."""
    request = urllib.request.Request(USAGE_URL)
    request.add_header("Authorization", f"Bearer {credential.access_token}")
    request.add_header("anthropic-beta", OAUTH_BETA)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitedError(retry_after_seconds(exc.headers)) from exc
        if exc.code in (401, 403):
            raise AuthExpiredError(f"HTTP {exc.code}") from exc
        raise LimitsError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(str(exc)) from exc
    except ValueError as exc:
        raise LimitsError(str(exc)) from exc


def fetch_status(path: Path | None = None) -> LimitStatus:
    """Read credentials, call the endpoint, and parse the result."""
    credential = read_credentials(path)
    status = parse(fetch(credential))
    # Plan info comes from the credentials file, not the usage response.
    status.subscription_type = credential.subscription_type
    status.rate_limit_tier = credential.rate_limit_tier
    status.account = read_account()
    return status

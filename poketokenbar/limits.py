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
from dataclasses import dataclass, field
from pathlib import Path

from . import format as fmt

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
class ScopedWindow:
    """A limits[] entry the legacy five_hour/seven_day fields cannot carry.

    Model-scoped weekly limits arrive only here, as kind="weekly_scoped" with
    the model under scope.model.display_name — which is what the popup renders
    as "Weekly Fable". seven_day_opus/seven_day_sonnet are null now, so a
    front end reading only the legacy fields shows one row too few.
    """

    kind: str | None
    model: str | None
    window: LimitWindow


@dataclass(slots=True)
class LimitStatus:
    session: LimitWindow | None = None
    weekly: LimitWindow | None = None
    scoped: list = field(default_factory=list)
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
            kind = entry.get("kind")
            if kind == "session":
                status.session = window
            elif kind == "weekly_all":
                status.weekly = window
            else:
                # Everything the legacy fields cannot express. Matching
                # scopedLimitEntries: the filter is on kind, not on a list of
                # known scoped kinds, so a window Anthropic adds later still
                # appears instead of being silently dropped.
                scope = entry.get("scope")
                model = None
                if isinstance(scope, dict) and isinstance(scope.get("model"), dict):
                    model = scope["model"].get("display_name") or None
                status.scoped.append(ScopedWindow(kind=kind, model=model, window=window))

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


def named_windows(status: LimitStatus | None, mode: str) -> list[tuple[str, LimitWindow]]:
    """The windows the panel should show, in display order, each with its kind.

    The kind is what says how long the window is, which is what a pace needs.
    """
    if status is None:
        return []
    out: list[tuple[str, LimitWindow]] = []
    if mode in ("session", "both") and status.session is not None:
        out.append(("session", status.session))
    if mode in ("weekly", "both") and status.weekly is not None:
        out.append(("weekly", status.weekly))
    return out


def windows(status: LimitStatus | None, mode: str) -> list[LimitWindow]:
    """The windows the panel should show, in display order."""
    return [window for _kind, window in named_windows(status, mode)]


def display_percent(utilization: float, mode: str | None) -> float:
    """The percentage to show: used as is, or what is left, never below 0.

    Warning colours and notifications keep using the real utilization; only
    the number and the bar's fill follow the setting.
    """
    if mode == "remaining":
        return max(0.0, 100.0 - utilization)
    return utilization


def format_percent(value: float) -> str:
    return fmt.percent(value)


def _format(window: LimitWindow | None, label: str, percent_mode: str = "used") -> str:
    if window is None:
        return ""
    # No "left" suffix on the panel: it is a narrow surface and the direction is
    # the setting the reader chose, the way a battery percentage works. The
    # self-explaining suffix belongs on the popup rows.
    return f"{label} {format_percent(display_percent(window.utilization, percent_mode))}"


def panel_text(status: LimitStatus | None, mode: str, percent_mode: str = "used") -> str:
    """Panel string, e.g. '5h 91% · 7d 17%'."""
    if status is None:
        return ""
    parts: list[str] = []
    if mode in ("session", "both"):
        parts.append(_format(status.session, "5h", percent_mode))
    if mode in ("weekly", "both"):
        parts.append(_format(status.weekly, "7d", percent_mode))
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


def plan_display(status: LimitStatus | None) -> str | None:
    """"Max 5x" from subscription_type="max" and a tier carrying a multiplier.

    Ported from OAuthUsage.planDisplay: the multiplier is appended whenever the
    tier has one, not only for Max — and when it has none the grade stands
    alone ("Pro"). Upper-casing the whole thing, which is what this used to do,
    printed "MAX" and lost the 5x entirely.
    """
    grade = (status.subscription_type or "").strip() if status else ""
    if not grade:
        return None
    label = grade[:1].upper() + grade[1:]
    multiplier = _tier_multiplier(status.rate_limit_tier or "")
    return f"{label} {multiplier}" if multiplier else label


def _tier_multiplier(tier: str) -> str | None:
    for part in tier.split("_"):
        if part.endswith("x") and part[:-1].isdigit() and len(part) > 1:
            return part
    return None


def account_display(status: LimitStatus | None) -> str | None:
    """"email · organisation", dropping a personal plan's generated org name.

    A personal organisation is named "<email>'s Organization", so printing it
    repeats the email. No email means no label at all: an organisation on its
    own does not identify which login these limits belong to.
    """
    account = (status.account if status else None) or {}
    email = (account.get("email") or "").strip()
    if not email:
        return None
    organization = (account.get("organization") or "").strip()
    if not organization or email in organization:
        return email
    return f"{email} · {organization}"

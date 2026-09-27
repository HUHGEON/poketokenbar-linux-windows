"""Cached, backoff-aware access to the Claude limits endpoint.

Separated from limits.py so the daemon can be handed a fake in tests: the poll
loop must not reach the network on every unit test run.

Three behaviours matter here:
  - Limits refresh on their own TTL, not once per log poll.
  - A failure keeps serving the last good value, so a network blip does not
    blank the panel.
  - 429 and 401 back off. Retrying a rate limit every poll makes it worse, and
    an expired login will not fix itself.
  - A change of login skips all of that: the cached value, and any backoff,
    belong to the login that was replaced.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import limits

# Backoff when the server gives no Retry-After.
DEFAULT_RATE_LIMIT_BACKOFF = 300.0
# An expired or missing login needs human action; probing it is pure waste.
AUTH_BACKOFF = 900.0
# No network at all. Typically the daemon came up before the connection did,
# right after login, and the full TTL would leave the section blank for five
# minutes after the network is back.
NETWORK_RETRY = 30.0


def _credentials_marker(path=None) -> object:
    """(mtime, size) of a Claude credentials file, or None without one."""
    try:
        stat = (path or limits.default_credentials_path()).stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class LimitsSource:
    def __init__(
        self,
        fetch: Callable[[], limits.LimitStatus] | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = 300.0,
        wall_clock: Callable[[], float] = time.time,
        login_marker: Callable[[], object] | None = None,
    ) -> None:
        self._fetch = fetch or limits.fetch_status
        # Something that changes when Claude Code logs in again, possibly as
        # someone else. The real source watches the credentials file; a test
        # handing in its own fetch has no such file, so it opts in explicitly.
        self._login_marker = login_marker or (_credentials_marker if fetch is None else None)
        self._login: object = self._read_login()
        self._clock = clock
        self._ttl = ttl
        self._cached: limits.LimitStatus | None = None
        self._fetched_at: float | None = None
        self._blocked_until: float = 0.0
        self.last_error: str = ""
        # Wall-clock time of the last successful fetch, for "updated N ago".
        self._wall_clock = wall_clock
        self.updated_at: float | None = None
        # True while the last failure was the network itself rather than the
        # endpoint, so the UI can say "offline" instead of quoting a socket
        # error nobody can act on.
        self.offline: bool = False

    @property
    def stale(self) -> bool:
        """Serving the last good value while fetching it again is failing.

        The section used to keep showing that value with nothing on it to say
        so, and the only sign of trouble was an error line in the footer
        (upstream ce65fde gave Antigravity the marker Claude's limits had).
        """
        return self._cached is not None and bool(self.last_error)

    def invalidate(self) -> None:
        """Force the next get() to refetch — used by a manual refresh.

        Clears the backoff too: a person pressing refresh is an explicit
        request, not the poll loop hammering a rate limit.
        """
        self._fetched_at = None
        self._blocked_until = 0.0

    def _read_login(self) -> object:
        return self._login_marker() if self._login_marker is not None else None

    def get(self) -> limits.LimitStatus | None:
        now = self._clock()

        # Upstream 3214f83: an account switched in place used to wait out the
        # TTL (or a 15-minute auth backoff) showing the previous account's
        # limits. A stat per poll is all it costs to notice at once.
        login = self._read_login()
        if login != self._login:
            self._login = login
            self.invalidate()

        if now < self._blocked_until:
            return self._cached
        if self._fetched_at is not None and (now - self._fetched_at) < self._ttl:
            return self._cached

        self.offline = False
        try:
            self._cached = self._fetch()
            self._fetched_at = now
            self.updated_at = self._wall_clock()
            self.last_error = ""
        except limits.NetworkError as exc:
            # Keep the stale value and try again soon, not after the TTL.
            self._fetched_at = None
            self._blocked_until = now + NETWORK_RETRY
            self.offline = True
            self.last_error = str(exc)
        except limits.RateLimitedError as exc:
            wait = exc.retry_after or DEFAULT_RATE_LIMIT_BACKOFF
            self._blocked_until = now + wait
            self.last_error = f"rate limited, retrying in {int(wait)}s"
        except (limits.AuthExpiredError, limits.NeedsLoginError) as exc:
            self._blocked_until = now + AUTH_BACKOFF
            self.last_error = f"{exc} — run `claude login`"
        except limits.LimitsError as exc:
            # Keep the stale value; a blip should not blank the section.
            self._fetched_at = now
            self.last_error = str(exc)

        return self._cached


class AccountLimits:
    """One account's limits, and who they belong to.

    A thin pairing of a config folder with its own LimitsSource: every account
    keeps its own cache, its own backoff and its own error, so one expired
    login cannot blank another account's numbers or pin everyone's refresh.
    """

    def __init__(self, account, ttl: float = 300.0, source=None) -> None:
        self.account = account
        self.source = source or LimitsSource(
            fetch=lambda: limits.fetch_status(account.credentials),
            ttl=ttl,
            login_marker=lambda: _credentials_marker(account.credentials),
        )

    def get(self):
        status = self.source.get()
        if status is not None and not status.account:
            # Each folder names its own login; the default reader would answer
            # with the default account for every one of them.
            status.account = limits.read_account(self.account.account_file)
        return status

    @property
    def label(self) -> str:
        """What to call this account before its own name is known."""
        status = self.source._cached
        who = (status.account or {}) if status is not None else {}
        return who.get("email") or who.get("display_name") or (
            "" if self.account.is_default else self.account.id)


class MultiAccountLimits:
    """Every logged-in Claude account, with the default one still in front.

    A drop-in for LimitsSource: `get()` answers with the default account, which
    is what the panel, the companion mood and the forecast follow, and
    `accounts()` carries the rest for the popup (upstream e5b4800). With one
    login — which is the normal case — nothing behaves differently.
    """

    def __init__(self, discover=None, ttl: float = 300.0, factory=None) -> None:
        from . import accounts as account_discovery

        self._discover = discover or account_discovery.discover
        self._factory = factory or (lambda account: AccountLimits(account, ttl=ttl))
        self._ttl = ttl
        self._sources: dict[str, AccountLimits] = {}
        self._order: list[str] = []
        self.extra_config_dirs: list[str] = []
        self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        found = self._discover(extra=self.extra_config_dirs)
        self._order = [account.id for account in found]
        known = {account.id: account for account in found}
        for account_id, account in known.items():
            if account_id not in self._sources:
                self._sources[account_id] = self._factory(account)
        # A folder that has gone (a logout, a renamed directory) takes its
        # cache with it rather than lingering as a tab nobody can refresh.
        for account_id in list(self._sources):
            if account_id not in known:
                del self._sources[account_id]

    @property
    def _default(self) -> AccountLimits | None:
        return self._sources.get(self._order[0]) if self._order else None

    def get(self):
        self._refresh_accounts()
        for account_id in self._order:
            source = self._sources.get(account_id)
            if source is not None:
                source.get()
        default = self._default
        return default.get() if default is not None else None

    def invalidate(self) -> None:
        for source in self._sources.values():
            source.source.invalidate()

    @property
    def stale(self) -> bool:
        default = self._default
        return bool(default is not None and default.source.stale)

    @property
    def updated_at(self):
        default = self._default
        return default.source.updated_at if default is not None else None

    @property
    def offline(self) -> bool:
        default = self._default
        return bool(default is not None and default.source.offline)

    @property
    def last_error(self) -> str:
        default = self._default
        return default.source.last_error if default is not None else ""

    def accounts(self) -> list[tuple[str, object, AccountLimits]]:
        """(id, status, source) per account, the default one first."""
        out = []
        for account_id in self._order:
            source = self._sources.get(account_id)
            if source is None:
                continue
            out.append((account_id, source.source._cached, source))
        return out

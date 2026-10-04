"""Cached, backoff-aware access to official limits endpoints.

Separated from limits.py so the daemon can be handed a fake in tests: the poll
loop must not reach the network on every unit test run.

Three behaviours matter here:
  - Limits refresh on their own TTL, not once per log poll.
  - A failure keeps serving the last good value, so a network blip does not
    blank the panel.
  - 429 and 401 back off. Retrying a rate limit every poll makes it worse, and
    an expired login will not fix itself.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import limits

# Backoff when the server gives no Retry-After.
DEFAULT_RATE_LIMIT_BACKOFF = 300.0
# An expired or missing login needs human action; probing it is pure waste.
AUTH_BACKOFF = 900.0


class LimitsSource:
    def __init__(
        self,
        fetch: Callable[[], limits.LimitStatus] | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = 300.0,
    ) -> None:
        self._fetch = fetch or limits.fetch_status
        self._clock = clock
        self._ttl = ttl
        self._cached: limits.LimitStatus | None = None
        self._fetched_at: float | None = None
        self._blocked_until: float = 0.0
        self.last_error: str = ""

    def invalidate(self, clear_cache: bool = False) -> None:
        """Force the next get() to refetch — used by a manual refresh.

        Clears the backoff too: a person pressing refresh is an explicit
        request, not the poll loop hammering a rate limit.
        """
        self._fetched_at = None
        self._blocked_until = 0.0
        if clear_cache:
            self._cached = None

    def get(self) -> limits.LimitStatus | None:
        now = self._clock()

        if now < self._blocked_until:
            return self._cached
        if self._fetched_at is not None and (now - self._fetched_at) < self._ttl:
            return self._cached

        try:
            self._cached = self._fetch()
            self._fetched_at = now
            self.last_error = ""
        except limits.RateLimitedError as exc:
            wait = exc.retry_after or DEFAULT_RATE_LIMIT_BACKOFF
            self._blocked_until = now + wait
            self.last_error = f"rate limited, retrying in {int(wait)}s"
        except (limits.AuthExpiredError, limits.NeedsLoginError) as exc:
            self._blocked_until = now + AUTH_BACKOFF
            self.last_error = str(exc)
        except limits.LimitsError as exc:
            # Keep the stale value; a blip should not blank the section.
            self._fetched_at = now
            self.last_error = str(exc)

        return self._cached

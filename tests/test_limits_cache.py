import pytest

from poketokenbar import limits
from poketokenbar.limits_source import LimitsSource


class FakeClock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _status(session=50.0):
    return limits.parse({"limits": [{"kind": "session", "percent": session}]})


def test_first_call_fetches():
    calls = []

    def fetch():
        calls.append(1)
        return _status()

    src = LimitsSource(fetch=fetch, clock=FakeClock(), ttl=60)
    assert src.get().session.utilization == 50.0
    assert len(calls) == 1


def test_within_ttl_serves_cache_without_refetching():
    calls = []
    clock = FakeClock()

    def fetch():
        calls.append(1)
        return _status()

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    clock.advance(30)
    src.get()
    assert len(calls) == 1


def test_after_ttl_refetches():
    calls = []
    clock = FakeClock()

    def fetch():
        calls.append(1)
        return _status()

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    clock.advance(61)
    src.get()
    assert len(calls) == 2


def test_failure_keeps_serving_the_last_good_value():
    # A transient network blip must not blank the limits section.
    clock = FakeClock()
    state = {"fail": False}

    def fetch():
        if state["fail"]:
            raise limits.LimitsError("network down")
        return _status(42.0)

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    assert src.get().session.utilization == 42.0
    state["fail"] = True
    clock.advance(61)
    assert src.get().session.utilization == 42.0
    assert "network down" in src.last_error


def test_failure_with_no_cached_value_returns_none():
    def fetch():
        raise limits.LimitsError("boom")

    src = LimitsSource(fetch=fetch, clock=FakeClock(), ttl=60)
    assert src.get() is None
    assert "boom" in src.last_error


def test_rate_limit_backoff_honours_retry_after():
    calls = []
    clock = FakeClock()

    def fetch():
        calls.append(1)
        raise limits.RateLimitedError(retry_after=300)

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    assert len(calls) == 1
    clock.advance(61)  # past the TTL but inside the backoff
    src.get()
    assert len(calls) == 1, "must not hammer the endpoint during backoff"
    clock.advance(300)
    src.get()
    assert len(calls) == 2


def test_auth_expired_backs_off_and_is_reported():
    calls = []
    clock = FakeClock()

    def fetch():
        calls.append(1)
        raise limits.AuthExpiredError("HTTP 401")

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    clock.advance(61)
    src.get()
    assert len(calls) == 1, "re-login will not fix itself; do not retry every poll"
    assert "401" in src.last_error


def test_success_clears_a_previous_error():
    clock = FakeClock()
    state = {"fail": True}

    def fetch():
        if state["fail"]:
            raise limits.LimitsError("blip")
        return _status()

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    assert src.last_error
    state["fail"] = False
    clock.advance(61)
    src.get()
    assert src.last_error == ""


# MARK: no network


def test_no_network_retries_soon_rather_than_after_the_ttl():
    """The daemon comes up before the connection does after login, and the
    section stayed blank for the full TTL after the network was back."""
    from poketokenbar.limits_source import NETWORK_RETRY

    calls = []
    clock = FakeClock()
    state = {"down": True}

    def fetch():
        calls.append(1)
        if state["down"]:
            raise limits.NetworkError("<urlopen error [Errno -2] Name or service not known>")
        return _status(42.0)

    src = LimitsSource(fetch=fetch, clock=clock, ttl=300)
    assert src.get() is None
    assert src.offline is True
    assert "Name or service" in src.last_error

    clock.advance(NETWORK_RETRY - 1)
    src.get()
    assert len(calls) == 1, "not every poll either; DNS failure is not free"

    state["down"] = False
    clock.advance(2)
    assert src.get().session.utilization == 42.0
    assert src.offline is False
    assert src.last_error == ""


def test_no_network_keeps_the_last_good_value():
    clock = FakeClock()
    state = {"down": False}

    def fetch():
        if state["down"]:
            raise limits.NetworkError("no route")
        return _status(42.0)

    src = LimitsSource(fetch=fetch, clock=clock, ttl=60)
    src.get()
    state["down"] = True
    clock.advance(61)
    assert src.get().session.utilization == 42.0
    assert src.offline is True


# MARK: stale values (upstream ce65fde)


def test_limits_are_stale_only_while_serving_a_value_that_failed_to_refresh():
    clock = FakeClock()
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            return _status()
        raise limits.LimitsError("HTTP 500")

    source = LimitsSource(fetch=fetch, clock=clock, ttl=10, wall_clock=lambda: 1_789_000_000.0)
    assert not source.stale, "nothing fetched yet is not stale, just absent"
    source.get()
    assert not source.stale and source.updated_at == 1_789_000_000.0

    clock.now += 11
    assert source.get() is not None
    assert source.stale
    assert source.updated_at == 1_789_000_000.0, "the time of the last good fetch stays"


def test_nothing_is_stale_when_there_was_never_a_value():
    def fetch():
        raise limits.LimitsError("HTTP 500")

    source = LimitsSource(fetch=fetch, clock=FakeClock())
    source.get()
    assert source.get() is None and not source.stale


def test_the_payload_says_when_limits_are_stale():
    from poketokenbar import state

    payload = state.build({}, {}, [], limit_status=_status(),
                          limits_freshness={"stale": True, "updated_at": 5.0})
    assert payload["limits"]["stale"] is True
    assert payload["limits"]["updated_at"] == 5.0


# MARK: a login changed in place (upstream 3214f83)


def test_a_new_login_refetches_inside_the_ttl_and_the_backoff():
    clock = FakeClock()
    login = {"marker": "alice"}
    calls = []

    def fetch():
        calls.append(login["marker"])
        if login["marker"] == "expired":
            raise limits.AuthExpiredError("HTTP 401")
        return _status()

    src = LimitsSource(fetch=fetch, clock=clock, ttl=300, login_marker=lambda: login["marker"])
    src.get()
    clock.advance(10)
    src.get()
    assert calls == ["alice"], "the same login is served from cache"

    login["marker"] = "expired"
    src.get()
    assert calls == ["alice", "expired"]

    login["marker"] = "bob"
    clock.advance(1)
    assert src.get() is not None
    assert calls == ["alice", "expired", "bob"], "a fresh login skips the auth backoff"


def test_the_real_source_watches_the_credentials_file(tmp_path, monkeypatch):
    from poketokenbar import limits_source

    credentials = tmp_path / ".credentials.json"
    monkeypatch.setattr(limits, "default_credentials_path", lambda env=None: credentials)
    assert limits_source._credentials_marker() is None
    credentials.write_text("{}")
    assert limits_source._credentials_marker() is not None

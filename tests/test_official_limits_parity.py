"""Fixture coverage for upstream v2.5.5 official quota providers."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from poketokenbar import limits


def test_legacy_scoped_limits_survive():
    status = limits.parse({"five_hour": {"utilization": 20},
                          "seven_day_opus": {"utilization": 80}})
    assert [(row.model, row.window.utilization) for row in status.scoped] == [("Opus", 80)]


def test_pace_boundaries_and_invalid_windows():
    from poketokenbar.pace import gauge_tier, rounded_delta, window_pace
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert window_pace((now + timedelta(hours=2.5)).isoformat(), 18000, now) == .5
    assert window_pace((now - timedelta(seconds=1)).isoformat(), 18000, now) is None
    assert window_pace((now + timedelta(hours=6)).isoformat(), 18000, now) is None
    assert [gauge_tier(n, .5) for n in (24, 25, 40, 55, 65, 80)] == [
        "way_under", "under", "on_pace", "slightly_over", "over", "way_over"]
    assert gauge_tier(95, .99) == "way_over"
    assert gauge_tier(80, .01) == "over"
    assert rounded_delta(38.5, .5) == -12


def test_session_key_store_isolates_accounts(tmp_path):
    from poketokenbar.session_key import SessionKeyStore
    key = "sk-ant-sid02-" + "x" * 50
    first = SessionKeyStore(tmp_path, config_root=tmp_path / "one")
    second = SessionKeyStore(tmp_path, config_root=tmp_path / "two")
    first.save(" \n" + key + "\n", "org")
    assert first.load().key == key
    assert first.load().organization_id == "org"
    assert second.load() is None
    with pytest.raises(ValueError):
        first.save(key + ";other=value")
    first.clear()
    assert first.load() is None


def test_session_key_selects_active_chat_org_and_caches_it(tmp_path):
    from poketokenbar.session_key import SessionKeyProvider, SessionKeyStore
    store = SessionKeyStore(tmp_path)
    store.save("sk-ant-sid02-" + "x" * 50)
    calls = []
    def http(request):
        calls.append(request.full_url)
        assert request.get_header("Cookie").startswith("sessionKey=sk-ant-")
        if request.full_url.endswith("organizations"):
            return [{"uuid": "api", "capabilities": ["api"]},
                    {"uuid": "empty", "capabilities": ["chat"]},
                    {"uuid": "active", "capabilities": ["chat"]}]
        return {"five_hour": {"utilization": 45 if "/active/" in request.full_url else 0}}
    source = SessionKeyProvider(store, http=http)
    assert source.fetch().session.utilization == 45
    assert store.load().organization_id == "active"
    assert not any("/api/usage" in url for url in calls)
    calls.clear()
    assert source.fetch().session.utilization == 45
    assert len(calls) == 1


def test_session_key_forbidden_cached_org_rediscovers(tmp_path):
    from poketokenbar.session_key import SessionKeyProvider, SessionKeyStore
    store = SessionKeyStore(tmp_path)
    store.save("sk-ant-sid02-" + "x" * 50, "old")
    def http(request):
        if "/old/" in request.full_url:
            raise limits.HTTPStatusError(403)
        if request.full_url.endswith("organizations"):
            return [{"uuid": "new"}]
        return {"seven_day": {"utilization": 9}}
    assert SessionKeyProvider(store, http=http).fetch().weekly.utilization == 9
    assert store.load().organization_id == "new"


def test_account_discovery_keeps_identity_and_excludes_default(tmp_path):
    from poketokenbar.claude_accounts import discover_roots
    root = tmp_path / ".claude-work"
    root.mkdir()
    (root / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "work@example.test"}}))
    other = tmp_path / "custom"
    other.mkdir()
    assert discover_roots(tmp_path, {}, f"{tmp_path}/.claude,{other},{root}") == [other, root]


def test_cursor_dashboard_percent_and_billing_dates():
    from poketokenbar.cursor_limits import parse_status
    status = parse_status({"billingCycleStart": "1770000000000", "billingCycleEnd": "1771077734000",
                           "planUsage": {"remaining": 16778, "limit": 40000, "totalPercentUsed": 58.055}})
    assert status["utilization"] == 58.055
    assert status["remaining_dollars"] == 167.78
    assert status["limit_dollars"] == 400
    assert status["resets_at"].startswith("2026-")
    assert parse_status({"planUsage": {"includedSpend": 10000, "limit": 40000}})["utilization"] == 25


def test_antigravity_groups_and_remaining_fraction():
    from poketokenbar.antigravity_limits import parse_status
    status = parse_status({"groups": [{"displayName": "Gemini", "buckets": [
        {"bucketId": "gemini-5h", "displayName": "Session", "remainingFraction": .3}]}]})
    bucket = status["groups"][0]["buckets"][0]
    assert bucket["utilization"] == 70
    assert bucket["duration_seconds"] == 18000


def test_antigravity_refresh_cache_does_not_cross_accounts(tmp_path):
    from poketokenbar.antigravity_limits import TokenCache
    path = tmp_path / "token.json"
    def write(refresh):
        path.write_text(json.dumps({"token": {"access_token": "expired", "refresh_token": refresh,
                                            "expiry": "2020-01-01T00:00:00Z"}}))
    calls = []
    def http(request):
        calls.append(request.data)
        return {"access_token": f"fresh-{len(calls)}", "expires_in": 3600}
    write("one")
    cache = TokenCache([path], http=http)
    assert cache.access_token() == "fresh-1"
    assert cache.access_token() == "fresh-1"
    write("two")
    assert cache.access_token() == "fresh-2"
    assert len(calls) == 2


def _login(root, email, token, org="org-team"):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": token, "subscriptionType": "max", "rateLimitTier": "default_claude_max_5x"}}))
    (root / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "emailAddress": email, "accountUuid": email, "organizationUuid": org}}))


def test_accounts_keep_separate_limits_and_clear_previous_login(tmp_path):
    from poketokenbar.claude_accounts import ClaudeAccountsSource, account_id
    home = tmp_path / "home"
    extra = home / ".claude-team"
    _login(extra, "one@example.test", "one")
    def http(request):
        token = request.get_header("Authorization")
        if token == "Bearer two":
            raise limits.AuthExpiredError("expired")
        return {"five_hour": {"utilization": 20 if token == "Bearer one" else 90}}
    source = ClaudeAccountsSource(tmp_path / "state", home, {}, http)
    source.get()
    identity = account_id(extra)
    assert source.account_statuses[identity].session.utilization == 20
    assert source.account_statuses[identity].account["email"] == "one@example.test"
    _login(extra, "second@example.test", "two")
    source.get()
    assert source.account_statuses[identity] is None
    assert source.account_metadata[identity]["account"]["email"] == "second@example.test"


def test_account_session_key_prefers_folder_organization(tmp_path):
    from poketokenbar.claude_accounts import ClaudeAccountsSource, account_id
    home = tmp_path / "home"
    extra = home / ".claude-team"
    _login(extra, "team@example.test", "unused")
    calls = []
    def http(request):
        calls.append(request.full_url)
        if request.full_url.endswith("organizations"):
            return [{"uuid": "org-personal"}, {"uuid": "org-team"}]
        return {"five_hour": {"utilization": 0 if "/org-team/" in request.full_url else 60}}
    source = ClaudeAccountsSource(tmp_path / "state", home, {}, http)
    identity = account_id(extra)
    source.session_key_store(identity).save("sk-ant-sid02-" + "x" * 50)
    source.get()
    assert source.account_statuses[identity].session.utilization == 0
    assert source.account_metadata[identity]["has_session_key"] is True
    assert source.account_metadata[identity]["stale"] is False
    assert source.session_key_store(identity).load().organization_id == "org-team"


def test_session_key_failure_falls_back_to_oauth_and_retains_stale_on_blip(tmp_path):
    from poketokenbar.claude_accounts import ClaudeAccountsSource, account_id
    home = tmp_path / "home"
    extra = home / ".claude-team"
    _login(extra, "team@example.test", "oauth")
    fail = []
    def http(request):
        if "claude.ai" in request.full_url:
            raise limits.HTTPStatusError(401)
        if fail:
            raise limits.LimitsError("offline")
        return {"five_hour": {"utilization": 55}}
    source = ClaudeAccountsSource(tmp_path / "state", home, {}, http)
    identity = account_id(extra)
    source.session_key_store(identity).save("sk-ant-sid02-" + "x" * 50)
    source.get()
    assert source.account_statuses[identity].session.utilization == 55
    fail.append(True)
    source.invalidate()
    source.get()
    assert source.account_statuses[identity].session.utilization == 55
    assert source.account_metadata[identity]["stale"] is True
    assert "session key" in source.account_errors[identity]


@pytest.mark.parametrize("code", [401, 403])
def test_session_key_invalid_reports_key_remediation(tmp_path, code):
    from poketokenbar.session_key import SessionKeyError, SessionKeyProvider, SessionKeyStore
    store = SessionKeyStore(tmp_path)
    store.save("sk-ant-sid02-" + "x" * 50)
    def http(request):
        raise limits.HTTPStatusError(code)
    with pytest.raises(SessionKeyError, match="Settings"):
        SessionKeyProvider(store, http=http).fetch()


def test_session_key_rate_limit_backs_off_and_keeps_cached_status(tmp_path):
    from poketokenbar.limits_source import LimitsSource
    from poketokenbar.session_key import SessionKeyProvider, SessionKeyStore
    store = SessionKeyStore(tmp_path)
    store.save("sk-ant-sid02-" + "x" * 50, "org")
    clock, calls = [0], []
    def http(request):
        calls.append(request.full_url)
        if len(calls) > 1:
            raise limits.RateLimitedError(100)
        return {"five_hour": {"utilization": 30}}
    source = LimitsSource(SessionKeyProvider(store, http).fetch, clock=lambda: clock[0], ttl=10)
    assert source.get().session.utilization == 30
    clock[0] = 11
    assert source.get().session.utilization == 30
    clock[0] = 100
    source.get()
    assert len(calls) == 2


def test_cursor_reads_windows_login_and_refreshes_after_rejection(tmp_path):
    import sqlite3
    from poketokenbar.cursor_limits import CursorProvider, TOKEN_URL, USAGE_URL
    root = tmp_path / "Cursor" / "User" / "globalStorage"
    root.mkdir(parents=True)
    with sqlite3.connect(root / "state.vscdb") as connection:
        connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO ItemTable VALUES (?, ?)", [
            ("cursorAuth/accessToken", "old"), ("cursorAuth/refreshToken", "refresh")])
    calls = []
    def http(request):
        calls.append(request.full_url)
        if request.full_url == TOKEN_URL:
            assert json.loads(request.data)["refresh_token"] == "refresh"
            return {"access_token": "new"}
        assert request.full_url == USAGE_URL
        assert request.get_header("Connect-protocol-version") == "1"
        if request.get_header("Authorization") == "Bearer old":
            raise limits.HTTPStatusError(401)
        assert request.get_header("Authorization") == "Bearer new"
        return {"planUsage": {"limit": 100, "includedSpend": 30}}
    provider = CursorProvider(tmp_path, {"CURSOR_DATA_DIR": str(root)}, http)
    assert provider.fetch()["utilization"] == 30
    assert provider.fetch()["utilization"] == 30
    assert calls.count(TOKEN_URL) == 1
    with sqlite3.connect(root / "state.vscdb") as connection:
        assert connection.execute("SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'").fetchone()[0] == "old"


def test_cursor_override_never_refreshes_with_different_local_login(tmp_path):
    from poketokenbar.cursor_limits import CursorProvider
    calls = []
    def http(request):
        calls.append(request.full_url)
        raise limits.HTTPStatusError(401)
    provider = CursorProvider(tmp_path, {"CURSOR_SESSION_TOKEN": "override"}, http)
    with pytest.raises(limits.AuthExpiredError):
        provider.fetch()
    assert len(calls) == 1


def test_antigravity_wrapped_token_and_endpoint_auth_refresh(tmp_path):
    import base64
    from poketokenbar.antigravity_limits import AntigravityProvider, DAILY_URL, TOKEN_URL
    path = tmp_path / "token"
    raw = json.dumps({"token": {"access_token": "old", "refresh_token": "r&+="}})
    path.write_text("go-keyring-base64:" + base64.b64encode(raw.encode()).decode())
    calls = []
    def http(request):
        calls.append(request.full_url)
        if request.full_url == TOKEN_URL:
            from urllib.parse import parse_qs
            assert parse_qs(request.data.decode())["refresh_token"] == ["r&+="]
            return {"access_token": "new", "expires_in": 3600}
        assert request.full_url == DAILY_URL
        if request.get_header("Authorization") == "Bearer old":
            raise limits.HTTPStatusError(401)
        assert request.get_header("Authorization") == "Bearer new"
        return {"groups": []}
    provider = AntigravityProvider(tmp_path / "state", tmp_path, {"ANTIGRAVITY_TOKEN_FILE": str(path)}, http)
    assert provider.fetch() == {"groups": [], "description": None}
    assert calls == [DAILY_URL, TOKEN_URL, DAILY_URL]


def test_antigravity_falls_back_endpoint_without_refreshing_for_server_failure(tmp_path):
    from poketokenbar.antigravity_limits import AntigravityProvider, DAILY_URL, PRIMARY_URL
    path = tmp_path / "token"
    path.write_text('{"token":"valid"}')
    calls = []
    def http(request):
        calls.append(request.full_url)
        if request.full_url == DAILY_URL:
            raise limits.HTTPStatusError(503)
        return {"groups": []}
    provider = AntigravityProvider(tmp_path / "state", tmp_path, {"ANTIGRAVITY_TOKEN_FILE": str(path)}, http)
    provider.fetch()
    assert calls == [DAILY_URL, PRIMARY_URL]


def test_missing_credentials_make_no_network_calls(tmp_path):
    from poketokenbar.antigravity_limits import AntigravityProvider
    from poketokenbar.cursor_limits import CursorProvider
    def http(request):
        pytest.fail("network request without credentials")
    assert CursorProvider(tmp_path, {}, http).fetch() is None
    assert AntigravityProvider(tmp_path / "state", tmp_path, {}, http).fetch() is None


@pytest.mark.parametrize("payload", [{"five_hour": {"utilization": "NaN"}},
                                     {"five_hour": {"utilization": float("inf")}}])
def test_unknown_quota_stays_unknown(payload):
    assert limits.parse(payload).session is None


def test_partial_account_json_does_not_break_other_accounts(tmp_path):
    path = tmp_path / ".claude.json"
    path.write_text("[]")
    assert limits.read_account(path) == {}


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_invalid_retry_after_uses_default_backoff(value):
    assert limits.retry_after_seconds({"Retry-After": value}) is None


def test_antigravity_rejected_refresh_explains_login_and_does_not_try_quota(tmp_path):
    from poketokenbar.antigravity_limits import TokenCache, TOKEN_URL
    path = tmp_path / "token"
    path.write_text(json.dumps({"access_token": "old", "refresh_token": "dead", "expiry": "2020-01-01T00:00:00Z"}))
    def http(request):
        assert request.full_url == TOKEN_URL
        raise limits.HTTPStatusError(400)
    with pytest.raises(limits.AuthExpiredError, match="sign in"):
        TokenCache([path], http).access_token()


def test_cursor_rejected_refresh_reports_login(tmp_path):
    import sqlite3
    from poketokenbar.cursor_limits import CursorProvider, TOKEN_URL
    root = tmp_path / "cursor"
    root.mkdir()
    with sqlite3.connect(root / "state.vscdb") as connection:
        connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO ItemTable VALUES (?, ?)", [
            ("cursorAuth/accessToken", "old"), ("cursorAuth/refreshToken", "dead")])
    def http(request):
        raise limits.HTTPStatusError(400 if request.full_url == TOKEN_URL else 401)
    with pytest.raises(limits.AuthExpiredError, match="sign in"):
        CursorProvider(tmp_path, {"CURSOR_DATA_DIR": str(root)}, http).fetch()


def test_http_errors_hide_response_body_and_honor_retry_after(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from poketokenbar.limits_http import request_json
    response = [429]
    def open_request(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", response[0], "secret-response-text",
                                     {"Retry-After": "120"}, io.BytesIO(b"secret-body"))
    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    request = urllib.request.Request("https://example.test")
    with pytest.raises(limits.RateLimitedError) as caught:
        request_json(request)
    assert caught.value.retry_after == 120
    response[0] = 500
    with pytest.raises(limits.HTTPStatusError) as caught:
        request_json(request)
    assert str(caught.value) == "HTTP 500"


@pytest.mark.parametrize("pace_value, mode, expected", [(None, "remaining", None), (.25, "used", .25), (.25, "remaining", .75)])
def test_pace_marker_mirrors_display_mode(pace_value, mode, expected):
    from poketokenbar.pace import marker_fraction
    assert marker_fraction(pace_value, mode) == expected


def test_discovered_organization_does_not_invalidate_fresh_account_cache(tmp_path):
    from poketokenbar.claude_accounts import ClaudeAccountsSource, account_id
    home = tmp_path / "home"
    extra = home / ".claude-team"
    _login(extra, "team@example.test", "unused")
    calls = []
    def http(request):
        calls.append(request.full_url)
        if request.full_url.endswith("organizations"):
            return [{"uuid": "org-team"}]
        return {"five_hour": {"utilization": 20}}
    source = ClaudeAccountsSource(tmp_path / "state", home, {}, http)
    source.session_key_store(account_id(extra)).save("sk-ant-sid02-" + "x" * 50)
    source.get()
    source.get()
    assert len(calls) == 2

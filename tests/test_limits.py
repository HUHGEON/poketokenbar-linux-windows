import json

import pytest

from poketokenbar import limits


def _usage_payload():
    """Shape observed live from api.anthropic.com/api/oauth/usage."""
    return {
        "five_hour": {"utilization": 91.0, "resets_at": "2026-08-19T01:49:59.547035+00:00"},
        "seven_day": {"utilization": 17.0, "resets_at": "2026-08-25T12:59:59.547051+00:00"},
        "seven_day_opus": None,
        "limits": [
            {
                "kind": "session",
                "group": "session",
                "percent": 91,
                "severity": "critical",
                "resets_at": "2026-08-19T01:49:59.547035+00:00",
                "is_active": True,
            },
            {
                "kind": "weekly_all",
                "group": "weekly",
                "percent": 17,
                "severity": "normal",
                "resets_at": "2026-08-25T12:59:59.547051+00:00",
                "is_active": False,
            },
        ],
    }


# --- credentials -----------------------------------------------------------


def test_reads_access_token_from_credentials(tmp_path):
    p = tmp_path / ".credentials.json"
    p.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "tok",
                    "expiresAt": 9_999_999_999_999,
                    "subscriptionType": "pro",
                    "rateLimitTier": "default_claude_ai",
                }
            }
        ),
        encoding="utf-8",
    )
    cred = limits.read_credentials(p)
    assert cred.access_token == "tok"
    assert cred.subscription_type == "pro"


def test_missing_file_raises_credential_error(tmp_path):
    with pytest.raises(limits.CredentialError):
        limits.read_credentials(tmp_path / "nope.json")


def test_mcp_only_credentials_signal_relogin(tmp_path):
    # Claude Code 2.1.x has been seen writing only MCP OAuth state. That is a
    # re-login condition, not a malformed file.
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"mcpOAuth": {"some-server": {}}}), encoding="utf-8")
    with pytest.raises(limits.NeedsLoginError):
        limits.read_credentials(p)


def test_corrupt_credentials_raise_credential_error(tmp_path):
    p = tmp_path / ".credentials.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(limits.CredentialError):
        limits.read_credentials(p)


# --- parsing ---------------------------------------------------------------


def test_parses_session_and_weekly_from_limits_array():
    status = limits.parse(_usage_payload())
    assert status.session.utilization == 91.0
    assert status.weekly.utilization == 17.0
    assert status.session.severity == "critical"


def test_falls_back_to_legacy_fields_when_limits_absent():
    payload = _usage_payload()
    del payload["limits"]
    status = limits.parse(payload)
    assert status.session.utilization == 91.0
    assert status.weekly.utilization == 17.0


def test_prefers_limits_array_over_legacy_when_they_disagree():
    payload = _usage_payload()
    payload["five_hour"]["utilization"] = 1.0
    assert limits.parse(payload).session.utilization == 91.0


def test_missing_windows_are_none_not_zero():
    # 0% and "unknown" must stay distinguishable — showing 0% for an unknown
    # window would read as "plenty of headroom left".
    status = limits.parse({})
    assert status.session is None
    assert status.weekly is None


def test_reset_countdown_is_exposed():
    status = limits.parse(_usage_payload())
    assert status.session.resets_at.startswith("2026-08-19T01:49:59")


# --- panel text ------------------------------------------------------------


def test_panel_text_shows_both_windows():
    status = limits.parse(_usage_payload())
    assert limits.panel_text(status, "both") == "5h 91% · 7d 17%"


def test_panel_text_session_only():
    status = limits.parse(_usage_payload())
    assert limits.panel_text(status, "session") == "5h 91%"


def test_panel_text_weekly_only():
    status = limits.parse(_usage_payload())
    assert limits.panel_text(status, "weekly") == "7d 17%"


def test_panel_text_is_empty_without_data():
    assert limits.panel_text(None, "both") == ""
    assert limits.panel_text(limits.parse({}), "both") == ""


def test_panel_text_omits_a_missing_window():
    payload = _usage_payload()
    payload["limits"] = [payload["limits"][0]]
    del payload["seven_day"]
    status = limits.parse(payload)
    assert limits.panel_text(status, "both") == "5h 91%"


# --- fetch errors ----------------------------------------------------------


def test_rate_limit_retry_after_is_capped_at_one_hour():
    assert limits.retry_after_seconds({"Retry-After": "999999"}) == 3600


def test_rate_limit_retry_after_ignores_http_date():
    assert limits.retry_after_seconds({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None


def test_rate_limit_retry_after_parses_seconds():
    assert limits.retry_after_seconds({"Retry-After": "30"}) == 30


def test_an_unreachable_endpoint_is_a_network_error(monkeypatch):
    """DNS down, no route, a timeout: the failures that fix themselves, and
    that the cache treats differently from a bad answer."""
    import urllib.error
    import urllib.request

    def unreachable(request, timeout=0):
        raise urllib.error.URLError(OSError(-2, "Name or service not known"))

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(limits.NetworkError):
        limits.fetch(limits.Credential(access_token="t"))


def test_claude_config_dir_moves_the_credentials_and_the_account(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "work-claude")}
    assert limits.default_credentials_path(env) == tmp_path / "work-claude" / ".credentials.json"
    assert limits.default_account_path(env) == tmp_path / "work-claude" / ".claude.json"


def test_without_claude_config_dir_the_home_locations_are_used(tmp_path):
    from pathlib import Path

    assert limits.default_credentials_path({}) == Path.home() / ".claude" / ".credentials.json"
    assert limits.default_account_path({"CLAUDE_CONFIG_DIR": "  "}) == Path.home() / ".claude.json"


# --- several Claude logins (upstream e5b4800) -------------------------------


def test_the_default_folder_is_always_the_first_account(tmp_path):
    from poketokenbar import accounts

    found = accounts.discover(home=tmp_path, env={})
    assert [a.id for a in found] == ["default"]
    assert found[0].config_dir == tmp_path / ".claude"
    assert found[0].is_default


def test_a_second_logged_in_folder_is_found(tmp_path):
    from poketokenbar import accounts

    for name in (".claude", ".claude-work", ".claude_side"):
        (tmp_path / name).mkdir()
        (tmp_path / name / ".credentials.json").write_text("{}", encoding="utf-8")
    # A folder nobody logged in to has nothing to ask the endpoint with.
    (tmp_path / ".claude-empty").mkdir()

    found = accounts.discover(home=tmp_path, env={})
    assert [a.id for a in found] == ["default", ".claude-work", ".claude_side"]


def test_a_folder_listed_by_hand_is_included(tmp_path):
    from poketokenbar import accounts

    (tmp_path / ".claude").mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / ".credentials.json").write_text("{}", encoding="utf-8")
    found = accounts.discover(home=tmp_path, env={}, extra=[str(other)])
    assert [a.id for a in found] == ["default", "elsewhere"]


def test_the_configured_folder_is_the_default_account(tmp_path):
    from poketokenbar import accounts

    configured = tmp_path / "custom"
    found = accounts.discover(home=tmp_path, env={"CLAUDE_CONFIG_DIR": str(configured)})
    assert found[0].config_dir == configured
    assert found[0].credentials == configured / ".credentials.json"


def test_one_account_behaves_exactly_as_before(tmp_path):
    from poketokenbar.limits_source import MultiAccountLimits

    status = limits.LimitStatus(session=limits.LimitWindow(42.0))
    source = MultiAccountLimits(
        discover=lambda extra=(): [_FakeAccount("default", True)],
        factory=lambda account: _FakeAccountLimits(account, status))
    assert source.get() is status
    assert len(source.accounts()) == 1
    assert source.stale is False and source.last_error == ""


def test_each_account_keeps_its_own_numbers_and_its_own_failure():
    from poketokenbar.limits_source import MultiAccountLimits

    default = limits.LimitStatus(session=limits.LimitWindow(10.0))
    other = limits.LimitStatus(session=limits.LimitWindow(90.0))
    sources = {
        "default": _FakeAccountLimits(_FakeAccount("default", True), default),
        "work": _FakeAccountLimits(_FakeAccount("work", False), other, error="login expired"),
    }
    source = MultiAccountLimits(
        discover=lambda extra=(): [one.account for one in sources.values()],
        factory=lambda account: sources[account.id])

    # The default account is what the panel and the mood still follow.
    assert source.get() is default
    assert source.last_error == ""
    rows = source.accounts()
    assert [row[0] for row in rows] == ["default", "work"]
    assert rows[1][1].session.utilization == 90.0
    assert rows[1][2].source.last_error == "login expired"


def test_a_folder_that_disappears_takes_its_cache_with_it():
    from poketokenbar.limits_source import MultiAccountLimits

    listed = [_FakeAccount("default", True), _FakeAccount("work", False)]
    source = MultiAccountLimits(
        discover=lambda extra=(): list(listed),
        factory=lambda account: _FakeAccountLimits(account, limits.LimitStatus()))
    source.get()
    assert len(source.accounts()) == 2
    listed.pop()
    source.get()
    assert [row[0] for row in source.accounts()] == ["default"]


class _FakeAccount:
    def __init__(self, name, is_default):
        from pathlib import Path

        self.id = name
        self.config_dir = Path(f"/tmp/{name}")
        self.is_default = is_default

    @property
    def credentials(self):
        return self.config_dir / ".credentials.json"

    @property
    def account_file(self):
        return self.config_dir / ".claude.json"


class _FakeSource:
    def __init__(self, status, error=""):
        self._cached = status
        self.last_error = error
        self.offline = False
        self.updated_at = 1.0
        self.stale = bool(error) and status is not None

    def get(self):
        return self._cached

    def invalidate(self):
        self._cached = self._cached


class _FakeAccountLimits:
    def __init__(self, account, status, error=""):
        self.account = account
        self.source = _FakeSource(status, error)

    def get(self):
        return self.source.get()

    @property
    def label(self):
        return self.account.id

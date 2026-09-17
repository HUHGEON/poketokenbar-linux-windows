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

from poketokenbar import config, state
from poketokenbar.daemon import Daemon


def test_session_keys_are_never_published_in_state():
    payload = state.build({}, {**config.DEFAULTS, "claude_session_key": "secret"}, [])
    assert "secret" not in str(payload)


def test_extra_limits_sources_are_visible_and_refreshable(tmp_path):
    class Source:
        last_error = None
        invalidated = False
        def get(self):
            return {"utilization": 25, "remaining_dollars": 15}
        def invalidate(self):
            self.invalidated = True
    source = Source()
    daemon = Daemon(tmp_path / "state.json", tmp_path / "config.json", None, [],
                    cursor_limits_source=source)
    result = daemon.poll_once()
    assert result["cursor_limits"]["utilization"] == 25
    daemon._handle_reconnect()
    assert source.invalidated


def test_remaining_limit_fill_and_pace_are_consistent():
    from poketokenbar.limits import LimitStatus, LimitWindow
    from datetime import datetime, timezone, timedelta
    reset = (datetime.now(timezone.utc) + timedelta(hours=2.5)).isoformat()
    payload = state.build({}, {**config.DEFAULTS, "limit_percent_mode": "remaining"}, [],
                          limit_status=LimitStatus(session=LimitWindow(25, reset)))
    window = payload["limits"]["session"]
    assert window["display_fraction"] == .75
    assert .49 < window["pace"] < .51
    assert window["pace_tier"] == "under"


def test_manual_refresh_waits_instead_of_busy_looping(tmp_path, monkeypatch):
    import pytest
    from poketokenbar import daemon as module
    subject = Daemon(tmp_path / "state.json", tmp_path / "config.json", None, [])
    subject.config_values["refresh_interval"] = 0
    polls = []
    def poll():
        polls.append(1)
        assert len(polls) == 1, "manual refresh must not poll in a tight loop"
    class Slept(Exception):
        pass
    def sleep(seconds):
        assert seconds > 0
        raise Slept()
    monkeypatch.setattr(subject, "poll_once", poll)
    monkeypatch.setattr(module.time, "sleep", sleep)
    with pytest.raises(Slept):
        subject.run()

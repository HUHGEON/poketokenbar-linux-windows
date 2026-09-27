"""One poll, from real log files on disk to a written state.json.

Every layer below this has its own tests, and all of them can pass while the
daemon still produces nothing: a provider missing from the registry, an XDG
path resolved somewhere unexpected, a payload key the writer drops. This walks
the whole path once with several providers present at the same time, which is
also the shape most people actually run.
"""

import datetime
import json

import pytest

from poketokenbar import config, providers, state
from poketokenbar.daemon import Daemon


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    for variable in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
    ):
        monkeypatch.delenv(variable, raising=False)
    return home


def seed_logs(home):
    """One of everything: JSONL, a token mapping with cache, and a nested layout."""
    now = datetime.datetime.now(datetime.timezone.utc)
    iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    claude = home / ".claude" / "projects" / "p"
    claude.mkdir(parents=True)
    (claude / "s.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "requestId": "r1",
                "timestamp": iso,
                "message": {
                    "id": "m1",
                    "model": "claude-opus-5",
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 50,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    gemini = home / ".gemini" / "tmp" / "h" / "chats"
    gemini.mkdir(parents=True)
    (gemini / "session-a.jsonl").write_text(
        json.dumps(
            {
                "id": "g1",
                "timestamp": iso,
                "model": "gemini-2.5-pro",
                "tokens": {"input": 500, "cached": 100, "output": 80, "thoughts": 20},
            }
        ),
        encoding="utf-8",
    )

    pi = home / ".pi" / "agent" / "sessions"
    pi.mkdir(parents=True)
    (pi / "s.jsonl").write_text(
        json.dumps(
            {
                "type": "message",
                "id": "p1",
                "timestamp": iso,
                "message": {
                    "role": "assistant",
                    "model": "gpt-5.5",
                    "usage": {"input": 300, "output": 40, "cacheWrite": 0, "cacheRead": 0},
                },
            }
        ),
        encoding="utf-8",
    )

    grok = home / ".grok" / "sessions" / "g" / "s1"
    grok.mkdir(parents=True)
    (grok / "summary.json").write_text(json.dumps({"session_summary": "x"}), encoding="utf-8")
    (grok / "updates.jsonl").write_text(
        json.dumps(
            {
                "timestamp": int(now.timestamp()),
                "method": "_x.ai/session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "prompt_id": "pg1",
                        "usage": {
                            "inputTokens": 900,
                            "outputTokens": 60,
                            "totalTokens": 960,
                            "cachedReadTokens": 400,
                            "modelUsage": {"grok-4": {"totalTokens": 960}},
                        },
                    },
                    "_meta": {"agentTimestampMs": int(now.timestamp() * 1000)},
                },
            }
        ),
        encoding="utf-8",
    )


def run_one_poll(home, language: str = "en"):
    """One poll, with the language pinned.

    The default is derived from the machine's locale, so a test that reads a
    catalogue string without saying which language it wants asserts whatever
    the developer's desktop happens to be set to — passing on an English CI
    runner and failing on a Korean laptop.
    """
    config.set_value(config.default_path(), "language", language)
    daemon = Daemon(
        state_path=state.default_path(),
        config_path=config.default_path(),
        cache=None,
        providers=[],
    )
    daemon.providers = providers.build(custom_roots=daemon.custom_scan_roots)
    payload = daemon.poll_once()
    state.write(daemon.state_path, payload)
    return daemon, json.loads(daemon.state_path.read_text(encoding="utf-8"))


def test_a_poll_reads_four_providers_at_once_and_writes_state(fake_home):
    seed_logs(fake_home)
    daemon, payload = run_one_poll(fake_home)

    assert payload["errors"] == []
    assert {k: v["total_tokens"] for k, v in payload["providers"].items()} == {
        "claude_code": 1250,  # 1000 + 200 + 50 cache read
        "gemini": 600,  # (500-100) + (80+20) + 100 cached
        "pi": 340,  # 300 + 40
        "grok": 960,  # (900-400) + 60 + 400 cached
    }
    assert payload["today"]["total_tokens"] == 3150


def test_the_state_file_lands_where_the_platform_puts_state(fake_home):
    """Compared against platform_paths rather than a literal: the XDG layout is
    Linux's answer, and the same daemon runs on three platforms."""
    from poketokenbar import platform_paths

    seed_logs(fake_home)
    daemon, _ = run_one_poll(fake_home)
    assert daemon.state_path == (
        platform_paths.state_base() / "poketokenbar" / "state.json"
    )
    assert daemon.state_path.is_file()


def test_the_day_is_broken_down_across_providers(fake_home):
    seed_logs(fake_home)
    _, payload = run_one_poll(fake_home)
    assert [row["model"] for row in payload["today"]["models"]] == [
        "claude-opus-5",
        "grok-4",
        "gemini-2.5-pro",
        "gpt-5.5",
    ]


def test_every_registered_provider_gets_a_settings_row(fake_home):
    """The settings page lists sources whether or not they are installed."""
    _, payload = run_one_poll(fake_home)
    rows = payload["settings"]["providers"]
    assert [row["id"] for row in rows] == providers.registered_ids()
    assert all(row["display_name"] for row in rows)


def test_an_empty_home_polls_cleanly(fake_home):
    """Someone who has installed none of the twelve must still get a valid file."""
    _, payload = run_one_poll(fake_home)
    assert payload["errors"] == []
    assert payload["today"]["total_tokens"] == 0
    assert payload["providers"] == {}


def test_the_written_file_is_valid_json_with_a_schema_version(fake_home):
    """The UI polls this file; a torn or unversioned write is what breaks it."""
    seed_logs(fake_home)
    _, payload = run_one_poll(fake_home)
    assert payload["schema_version"] == state.SCHEMA_VERSION
    assert payload["updated_at"] > 0
    assert "strings" in payload and payload["strings"]["home"] == "Home"
    assert payload["config"]["language"] == "en"

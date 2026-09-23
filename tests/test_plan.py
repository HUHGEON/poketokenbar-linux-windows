import io
import json
import random

import pytest

from poketokenbar import balance, plan, processes, save, shop
from poketokenbar.companion import CompanionState, EvoLine, apply_usage
from poketokenbar.balance import Rarity
from poketokenbar.companion_store import CompanionStore


@pytest.mark.parametrize("name,scale", [("go", 1), ("plus", 1), ("pro", 5), ("pro_5x", 5), ("pro_20x", 5)])
def test_equal_relative_growth_and_item_value(name, scale):
    assert plan.MULTIPLIERS[name] == scale
    state = CompanionState(balance_multiplier=scale)
    line = EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON)
    apply_usage(state, 1_000_000 * scale, line_for_egg=line, rng=random.Random(1))
    apply_usage(state, 10_000_000 * scale)
    assert state.active.used_at_stage / balance.phase_threshold(Rarity.COMMON, 3, 0, scale) == 0.4
    state.used_since_install = 100_000_000 * scale
    state.spent_tokens = 0
    shop.buy(state, "rareCandy")
    assert state.spendable_tokens == 0
    shop.use_item(state, "rareCandy")
    assert state.active.stage_index == 2
    assert state.active.used_at_stage == 35_000_000 * scale
    assert state.spendable_tokens == 0


def test_all_shop_prices_scale_together():
    plus = shop.entries(CompanionState())
    pro = shop.entries(CompanionState(balance_multiplier=5))
    assert {e.key: e.price for e in pro} == {e.key: e.price * 5 for e in plus}


def test_scale_survives_save_and_legacy_save_defaults_to_plus():
    state = CompanionState(balance_multiplier=5, detected_plan="pro", egg_usage=2_000_000)
    loaded = save.decode(save.encode(state))
    assert (loaded.balance_multiplier, loaded.detected_plan, loaded.egg_usage) == (5, "pro", 2_000_000)
    assert save.decode({}).balance_multiplier == 1
    for value in (True, 0, -5, 20, "5", {}, None):
        assert save.decode({"balance_multiplier": value}).balance_multiplier == 1


@pytest.mark.parametrize("account,expected", [
    ({"type": "chatgpt", "planType": "plus", "email": "private@example.com"}, "plus"),
    ({"type": "chatgpt", "planType": "pro"}, "pro"),
    ({"type": "chatgpt", "planType": "future-plan"}, None),
    ({"type": "apiKey"}, None), (None, None),
])
def test_account_protocol_is_read_only_and_discards_private_details(monkeypatch, account, expected):
    class Capture(io.StringIO):
        def close(self):
            pass

    class Process:
        stdin = Capture()
        stdout = io.StringIO('\n'.join(json.dumps(m) for m in (
            {"id": 1, "result": {}}, {"method": "unrelated"},
            {"id": 2, "result": {"account": account}},
        )))
        stopped = False

        def poll(self):
            return None if not self.stopped else 0

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    process = Process()
    monkeypatch.setattr(plan.subprocess, "Popen", lambda *a, **kw: process)
    assert plan.read_plan("codex") == expected
    sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [m["method"] for m in sent] == ["initialize", "initialized", "account/read"]
    assert sent[-1]["params"] == {"refreshToken": False}
    assert process.stopped


def test_codex_rate_limit_protocol_and_normalisation(monkeypatch):
    class Capture(io.StringIO):
        def close(self):
            pass

    payload = {
        "rateLimits": {
            "limitId": "codex", "limitName": "Codex", "planType": "plus",
            "primary": {"usedPercent": 31, "windowDurationMins": 300,
                        "resetsAt": 2_000_000_000},
            "secondary": {"usedPercent": 12, "windowDurationMins": 10080,
                          "resetsAt": 2_000_100_000},
        },
        "rateLimitsByLimitId": {
            "codex": {"limitId": "codex"},
            "codex_other": {"limitId": "codex_other", "limitName": "Codex other",
                            "primary": {"usedPercent": 7, "windowDurationMins": 300}},
        },
    }

    class Process:
        stdin = Capture()
        stdout = io.StringIO('\n'.join(json.dumps(m) for m in (
            {"id": 1, "result": {}}, {"id": 2, "result": payload},
        )))
        stopped = False

        def poll(self):
            return None if not self.stopped else 0

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    process = Process()
    monkeypatch.setattr(plan.subprocess, "Popen", lambda *a, **kw: process)
    normalized = plan.parse_rate_limits(plan.read_rate_limits("codex"))

    sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [message["method"] for message in sent] == [
        "initialize", "initialized", "account/rateLimits/read"
    ]
    assert len(normalized["buckets"]) == 2
    assert normalized["buckets"][0]["windows"][0]["utilization"] == 31
    assert normalized["buckets"][0]["windows"][0]["resets_at"]


def test_background_helpers_disable_windows_console(monkeypatch):
    monkeypatch.setattr(processes.sys, "platform", "win32")
    monkeypatch.setattr(processes.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert processes.background_options() == {"creationflags": 0x08000000}
    monkeypatch.setattr(processes.sys, "platform", "linux")
    assert processes.background_options() == {}


def grown_store(tmp_path):
    store = CompanionStore(save_path=tmp_path / "companion.json")
    apply_usage(store.state, 11_000_000,
                line_for_egg=EvoLine(1, [1, 2, 3], Rarity.COMMON), rng=random.Random(1))
    store.state.claimed_today_tokens_by_provider = {"codex": 11_000_000}
    store.state.last_date = "2026-09-21"
    store.state.spent_tokens = 1_000_000
    return store


def test_plan_change_preserves_progress_without_rewriting_token_ledger(tmp_path):
    store = grown_store(tmp_path)
    assert store.payload()["stage_progress"] == 0.4
    assert store.apply_plan("pro")
    assert store.state.active.used_at_stage == 50_000_000
    assert store.payload()["stage_threshold"] == 125_000_000
    assert store.payload()["stage_progress"] == 0.4
    assert store.state.used_since_install == 11_000_000
    assert store.state.spent_tokens == 1_000_000
    assert store.state.claimed_today_tokens_by_provider == {"codex": 11_000_000}
    # Already counted usage cannot be credited again after a scale change.
    store.update({"codex": 11_000_000}, today="2026-09-21")
    assert store.state.active.used_at_stage == 50_000_000
    # New tokens keep their real value; multiplying these would cancel the
    # entire purpose of a larger experience bar for Pro.
    store.update({"codex": 11_000_100}, today="2026-09-21")
    assert store.state.active.used_at_stage == 50_000_100
    assert store.state.used_since_install == 11_000_100


def test_restart_unavailable_and_pro20_do_not_rescale_twice(tmp_path):
    store = grown_store(tmp_path)
    store.apply_plan("pro")
    restored = CompanionStore(save_path=store.save_path)
    for plan_name in (None, "unsupported", "pro", "pro_20x", "pro_5x"):
        restored.apply_plan(plan_name)
        assert restored.state.active.used_at_stage == 50_000_000
        assert restored.state.balance_multiplier == 5
    restored.apply_plan("go")
    assert restored.state.active.used_at_stage == 10_000_000
    assert restored.payload()["stage_progress"] == 0.4
    restored.apply_plan("plus")
    assert restored.state.active.used_at_stage == 10_000_000


def test_egg_progress_and_overflow_are_rescaled_without_hatching(tmp_path):
    store = CompanionStore(save_path=tmp_path / "c.json")
    store.state.egg_usage = 400_000
    store.state.pending_hatch_id = 25
    store.apply_plan("pro")
    assert store.state.egg_usage == 2_000_000
    assert store.payload()["egg_progress"] == 0.4
    assert store.state.pending_hatch_id == 25
    store.state.egg_usage = 6_000_000  # pending offline hatch overflow
    store.apply_plan("plus")
    assert store.state.egg_usage == 1_200_000
    assert store.state.active is None


def test_failed_plan_save_does_not_change_live_units(tmp_path, monkeypatch):
    store = grown_store(tmp_path)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(save, "save", fail)
    with pytest.raises(OSError):
        store.apply_plan("pro")
    assert store.state.balance_multiplier == 1
    assert store.state.active.used_at_stage == 10_000_000


def test_detection_happens_before_purchase_and_usage(tmp_path):
    from datetime import date
    from poketokenbar import commands
    from poketokenbar.daemon import Daemon

    class Source:
        current = "pro"
        status = "detected"

        def get(self):
            return self.current

    store = grown_store(tmp_path)
    store.state.used_since_install = 500_000_000
    store.state.spent_tokens = 0
    store.state.last_date = date.today().isoformat()
    daemon = Daemon(tmp_path / "state.json", tmp_path / "config.json", None, [],
                    companion_store=store, plan_source=Source())
    daemon.spool = tmp_path / "spool"
    commands.enqueue("buy", {"key": "rareCandy"}, spool=daemon.spool)
    payload = daemon.poll_once()
    assert store.state.spent_tokens == 500_000_000
    assert store.state.inventory["rareCandy"] == 1
    assert store.state.active.used_at_stage == 50_000_000
    assert payload["settings"]["plan"] == {"detected": "pro", "status": "detected", "multiplier": 5}
    assert payload["errors"] == []


def test_detection_failure_is_reported_without_a_stale_plan(monkeypatch):
    monkeypatch.setattr(plan, "executable", lambda: "codex")
    monkeypatch.setattr(plan, "read_plan", lambda command: "pro")
    source = plan.PlanSource()
    source.get()
    source._worker.join(timeout=1)
    assert source.get() == "pro"
    source._next_check = 0
    monkeypatch.setattr(plan, "read_plan", lambda command: None)
    source.get()
    source._worker.join(timeout=1)
    assert source.get() is None
    assert source.status == "unavailable"


def test_imported_units_are_converted_before_next_purchase(tmp_path):
    from poketokenbar import commands, transfer
    from poketokenbar.daemon import Daemon

    class Source:
        current = "pro"
        status = "detected"

        def get(self):
            return self.current

    incoming = grown_store(tmp_path)
    incoming.state.used_since_install = 500_000_000
    incoming.state.spent_tokens = 0
    exported = transfer.export_to(tmp_path / "export.json", incoming.state)
    store = CompanionStore(save_path=tmp_path / "destination.json")
    daemon = Daemon(tmp_path / "state.json", tmp_path / "config.json", None, [],
                    companion_store=store, plan_source=Source())
    daemon.spool = tmp_path / "spool"
    commands.enqueue("import", {"path": str(exported)}, spool=daemon.spool)
    commands.enqueue("buy", {"key": "rareCandy"}, spool=daemon.spool)
    payload = daemon.poll_once()
    assert not payload["errors"]
    assert store.state.active.used_at_stage == 50_000_000
    assert store.state.spendable_tokens == 0
    assert save.load(store.save_path).balance_multiplier == 5

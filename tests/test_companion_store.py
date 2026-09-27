import random

from poketokenbar import balance
from poketokenbar.balance import Rarity
from poketokenbar.companion import EvoLine
from poketokenbar.companion_store import CompanionStore


class FakeAPI:
    def __init__(self, forms=3, rarity=Rarity.COMMON, broken=False):
        self.forms, self.rarity, self.broken = forms, rarity, broken
        self.rolls = 0

    def roll_base_species(self, rng, tier=None):
        if self.broken:
            from poketokenbar.pokeapi import PokeAPIError

            raise PokeAPIError("offline")
        self.rolls += 1
        return 1

    def line(self, base_id):
        if self.broken:
            from poketokenbar.pokeapi import PokeAPIError

            raise PokeAPIError("offline")
        return EvoLine(base_id=1, path_ids=list(range(1, self.forms + 1)), rarity=self.rarity)


def _store(tmp_path, api=None, seeded=True):
    s = CompanionStore(
        save_path=tmp_path / "companion.json", api=api or FakeAPI(), rng=random.Random(3)
    )
    if seeded:
        # First update only seeds the baseline; start from a known point.
        s.update({}, today="2026-08-18")
    return s


def test_first_update_seeds_the_baseline_without_granting(tmp_path):
    # Installing must not retroactively credit a day's existing usage.
    s = CompanionStore(save_path=tmp_path / "c.json", api=FakeAPI())
    s.update({"claude_code": 50_000_000}, today="2026-08-18")
    assert s.state.used_since_install == 0
    assert s.state.active is None


def test_second_update_credits_only_the_delta(tmp_path):
    s = CompanionStore(save_path=tmp_path / "c.json", api=FakeAPI())
    s.update({"claude_code": 1_000}, today="2026-08-18")
    s.update({"claude_code": 1_500}, today="2026-08-18")
    assert s.state.used_since_install == 500


def test_a_provider_total_going_backwards_does_not_credit_negative(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": 1_000}, today="2026-08-18")
    s.update({"claude_code": 400}, today="2026-08-18")
    assert s.state.used_since_install == 1_000


def test_new_day_counts_the_new_days_usage_not_the_old_total(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": 900}, today="2026-08-18")
    before = s.state.used_since_install
    # Next day the provider reports today's total from zero again. That 100 is
    # genuinely new usage, so it counts; what must NOT happen is re-crediting
    # yesterday's 900.
    s.update({"claude_code": 100}, today="2026-08-19")
    assert s.state.used_since_install == before + 100


def test_providers_are_tracked_independently(tmp_path):
    s = _store(tmp_path)
    s.update({"a": 100, "b": 100}, today="2026-08-18")
    s.update({"a": 150, "b": 100}, today="2026-08-18")
    assert s.state.used_since_install == 250


def test_enough_usage_hatches_a_companion(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-18")
    assert s.state.active is not None
    assert s.payload()["stage"] == "mon"


def test_offline_holds_progress_in_the_egg(tmp_path):
    s = _store(tmp_path, api=FakeAPI(broken=True))
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD * 2}, today="2026-08-18")
    assert s.state.active is None
    assert s.state.egg_usage == balance.EGG_HATCH_THRESHOLD * 2
    assert s.payload()["stage"] == "egg"


def test_state_survives_a_restart(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-18")
    species = s.state.active.current_id

    reopened = CompanionStore(save_path=tmp_path / "companion.json", api=FakeAPI())
    assert reopened.state.active is not None
    assert reopened.state.active.current_id == species


def test_egg_payload_reports_progress(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD // 2}, today="2026-08-18")
    payload = s.payload()
    assert payload["stage"] == "egg"
    assert 0.4 < payload["egg_progress"] < 0.6


def test_mon_payload_reports_stage_progress(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-18")
    payload = s.payload()
    assert payload["stage_index"] == 0
    assert payload["stage_threshold"] > 0
    assert payload["species_id"] >= 1


# MARK: using an item


def _hatched(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-18")
    return s


def test_candy_that_evolves_announces_it(tmp_path):
    """The events from an item use were dropped, so a candy that pushed a
    Pokemon over the line evolved it with no toast, no banner and no
    level-up mood."""
    s = _hatched(tmp_path)
    mon = s.state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    mon.used_at_stage = threshold - balance.RARE_CANDY_XP
    s.state.inventory["rareCandy"] = 1

    s.use_item("rareCandy")

    assert s.state.active.stage_index == 1
    assert s.last_events is not None and s.last_events.evolved_to is not None
    assert s.celebration["kind"] == "evolved"
    assert s.payload()["display_state"] == "levelUp"


def test_candy_that_only_adds_progress_still_says_so(tmp_path):
    """"The count went down and nothing happened" is indistinguishable from a
    bug, so the use gets a banner even when nothing crossed a threshold."""
    s = _hatched(tmp_path)
    s.state.inventory["rareCandy"] = 1
    before = s.state.active.used_at_stage

    s.use_item("rareCandy")

    assert s.state.active.used_at_stage == before + balance.RARE_CANDY_XP
    assert s.celebration["kind"] == "item"
    assert s.celebration["detail"]


def test_a_candys_evolution_survives_usage_in_the_same_poll(tmp_path):
    """Commands drain before the poll credits usage, so the candy's events
    were assigned and then immediately overwritten — silently, and only when
    the user happened to be working, which is most of the time."""
    s = _hatched(tmp_path)
    mon = s.state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    mon.used_at_stage = threshold - balance.RARE_CANDY_XP
    s.state.inventory["rareCandy"] = 1

    s.use_item("rareCandy")
    evolved_to = s.last_events.evolved_to
    assert evolved_to is not None

    # Ordinary usage lands in the same poll, well short of the next threshold.
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD + 1}, today="2026-08-18")
    assert s.last_events.evolved_to == evolved_to


def test_an_item_use_is_saved_immediately(tmp_path):
    """The daemon writes state.json from a store it keeps in memory, so a use
    that only lived there would survive right up until a restart."""
    from poketokenbar.companion_store import CompanionStore

    s = _hatched(tmp_path)
    s.state.inventory["rareCandy"] = 1
    s.use_item("rareCandy")
    grown = s.state.active.used_at_stage

    reopened = CompanionStore(save_path=tmp_path / "companion.json", api=FakeAPI())
    assert reopened.state.inventory["rareCandy"] == 0
    assert reopened.state.active.used_at_stage == grown


def test_a_batch_says_how_many_it_bought_or_used(tmp_path):
    """"Bought Rare Candy" for three of them reads as a bug, and the count is
    the one part of a bulk purchase the toast has to carry."""
    s = _hatched(tmp_path)
    s.state.used_since_install = 10 ** 12
    s.state.spent_tokens = 0
    assert "×4" in s.buy("rareCandy", 4)
    assert "×4" not in s.buy("rareCandy", 1)
    assert s.state.inventory["rareCandy"] == 5
    assert "×2" in s.use_item("rareCandy", 2)
    assert s.state.inventory["rareCandy"] == 3


def test_only_an_egg_with_something_to_release_carries_the_release_note(tmp_path):
    """The description says a Pokémon is sent off, which reads as losing it from
    the Pokédex; it is not, and this is the line that says so (upstream
    c951492)."""
    s = _hatched(tmp_path)
    rows = {row["key"]: row for row in s.shop_payload()}
    assert rows["egg"]["release_note"] != ""
    assert rows["rareCandy"]["release_note"] == ""

    # During the egg stage there is nothing to release, and nothing to reassure
    # anyone about.
    s.state.active = None
    rows = {row["key"]: row for row in s.shop_payload()}
    assert rows["egg"]["release_note"] == ""


def test_an_egg_that_could_not_hatch_tries_again_on_the_next_poll(tmp_path):
    """A ready egg whose species could not be fetched — offline, or the API
    failed — used to wait for the next token delta to try again. On a machine
    that has stopped for the day that delta never arrives, and the egg sits
    ready for ever (upstream 2ecf7d2)."""
    api = FakeAPI(broken=True)
    s = _store(tmp_path, api=api)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD + 7}, today="2026-08-18")
    assert s.state.active is None, "the species could not be fetched"
    assert s.state.egg_usage >= s.state.egg_hatch_threshold

    api.broken = False
    # No new tokens at all: the same totals as the poll before.
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD + 7}, today="2026-08-18")
    assert s.state.active is not None
    # The tokens banked past the threshold are credited once, to the stage.
    assert s.state.active.used_at_stage == 7
    assert s.state.egg_usage == 0


def test_a_quiet_poll_with_no_egg_waiting_still_does_nothing(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": 5}, today="2026-08-18")
    before = s.state.used_since_install
    s.update({"claude_code": 5}, today="2026-08-18")
    assert s.state.used_since_install == before
    assert s.state.active is None

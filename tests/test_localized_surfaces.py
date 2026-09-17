"""The surfaces the daemon renders words on, in the language the user picked.

These were English literals in the source: notifications, the celebration
banner, the shop and the bag. A Korean user got a Korean panel, an English
toast, and a shop that read "Rare Candy — Raises your Pokemon's EXP by 100M."
The tests are per surface rather than one sweep, because each one had its own
reason for being missed.
"""

import pytest

from poketokenbar import balance, companion, l10n
from poketokenbar.companion import CompanionState, DexEntry, GrowthEvents, MonState
from poketokenbar.companion_store import CompanionStore
from poketokenbar.notify import Notifier


class Spy:
    def __init__(self):
        self.sent = []

    def __call__(self, title, body="", urgency="normal"):
        self.sent.append((title, body, urgency))
        return True

    @property
    def text(self):
        return " ".join(f"{title} {body}" for title, body, _ in self.sent)


def store(language="ko", **state):
    subject = CompanionStore(api=None, sprite_store=None)
    subject.state = CompanionState(language=language, **state)
    return subject


def raising(path=(4, 5, 6), stage=1, **kwargs):
    return MonState(
        base_id=path[0],
        path_ids=list(path),
        planned_path_ids=list(path),
        stage_index=stage,
        rarity=balance.Rarity.COMMON,
        total_forms=len(path),
        **kwargs,
    )


# MARK: notifications


@pytest.mark.parametrize("language", [code for code in l10n.LANGUAGES if code != "en"])
def test_a_hatch_is_announced_in_the_chosen_language(language):
    spy = Spy()
    Notifier(spy).companion(GrowthEvents(hatched=25), "피카츄", language)
    assert spy.text != ""
    assert spy.text == f"{l10n.t('notif_hatch_title', language)} " + \
        l10n.t("notif_hatch_body", language).replace("%1", "피카츄")


def test_the_companion_name_lands_in_the_notification():
    spy = Spy()
    Notifier(spy).companion(GrowthEvents(hatched=25), "로토스", "ko")
    assert "로토스" in spy.text
    assert "%1" not in spy.text


def test_a_shiny_hatch_says_so():
    plain, shiny = Spy(), Spy()
    Notifier(plain).companion(GrowthEvents(hatched=25), "로토스", "ko")
    Notifier(shiny).companion(GrowthEvents(hatched=25), "로토스", "ko", shiny=True)
    assert plain.text != shiny.text
    assert "✨" in shiny.sent[0][0]


def test_a_ditto_reveal_replaces_the_evolution_that_triggered_it():
    """The reveal happens on the first evolution, and announcing both would say
    it became the next form and then that it never was one."""
    spy = Spy()
    Notifier(spy).companion(
        GrowthEvents(evolved_to=271, ditto_revealed=True), "메타몽", "ko",
        disguise="로토스")
    assert len(spy.sent) == 1
    assert "로토스" in spy.sent[0][1]
    assert l10n.t("notif_evolve_title", "ko") not in spy.text


def test_a_limit_warning_names_the_window_and_the_number():
    spy = Spy()
    Notifier(spy).limits({"session": 96.0}, warn=80, crit=95, language="ko")
    title, body, urgency = spy.sent[0]
    assert title == l10n.t("notif_limit_critical", "ko")
    assert l10n.t("five_hour_session", "ko") in body
    assert "96%" in body
    assert urgency == "critical"


def test_no_notification_leaves_a_placeholder_behind():
    """A row whose translation dropped %1 would ship the placeholder to the
    desktop. Cheaper to catch here than in a screenshot."""
    for language in l10n.LANGUAGES:
        spy = Spy()
        notifier = Notifier(spy)
        notifier.companion(GrowthEvents(hatched=1), "X", language)
        notifier.companion(GrowthEvents(evolved_to=2), "X", language)
        notifier.companion(
            GrowthEvents(graduated=DexEntry(1, 3, [1, 2, 3], balance.Rarity.COMMON)),
            "X", language)
        notifier.limits({"weekly": 99.0}, warn=80, crit=95, language=language)
        assert "%1" not in spy.text and "%2" not in spy.text, language


# MARK: the status line


def test_a_companion_that_just_evolved_does_not_report_a_catalogue_key():
    """display_state returns "levelUp", whose key would be `status_levelup` —
    which does not exist, so the panel showed that string verbatim."""
    subject = store(active=raising())
    subject.last_events = GrowthEvents(evolved_to=5)

    payload = subject.payload(today_tokens=1_000)

    assert payload["display_state"] == "levelUp"
    assert not payload["status_message"].startswith("status_")


@pytest.mark.parametrize("kind", ["egg", "idle", "working", "focus", "tired", "sleep"])
def test_every_other_display_state_resolves_too(kind):
    subject = store()
    assert not subject._status_message(kind).startswith("status_")


def test_the_level_up_status_falls_back_when_the_species_has_no_name():
    """Without species data there is no name to put in "Evolved into %1", and a
    sentence with a hole in it is worse than the shorter one."""
    subject = store(active=raising())
    assert subject._status_message("levelUp") == l10n.t("status_grew", "ko")


# MARK: shop and bag


def test_the_shop_is_written_in_the_chosen_language():
    korean = store("ko").shop_payload()
    english = store("en").shop_payload()
    assert [row["key"] for row in korean] == [row["key"] for row in english]
    assert all(row["label"] and row["description"] for row in korean)
    assert korean != english


def test_the_rare_candy_description_carries_its_own_number():
    """Read off the balance constant, so raising RARE_CANDY_XP cannot leave the
    shop advertising the old figure."""
    row = next(r for r in store("en").shop_payload() if r["key"] == "rareCandy")
    assert "100M" in row["description"]
    assert "%1" not in row["description"]


def test_a_guaranteed_egg_says_which_rarity_it_guarantees():
    row = next(r for r in store("ko").shop_payload() if r["key"] == "egg:uncommon")
    assert l10n.t("uncommon", "ko") in row["badge"]
    assert l10n.t("uncommon", "ko") in row["description"]


def test_the_bag_is_written_in_the_chosen_language():
    subject = store("ko")
    subject.state.inventory = {"rareCandy": 3}
    row = subject.bag_payload()[0]
    assert row["label"] == l10n.t("item_rare_candy", "ko")
    assert "%1" not in row["description"] and "%1" not in row["effect"]


# MARK: the celebration banner


@pytest.mark.parametrize("events,expected", [
    (GrowthEvents(hatched=4), "notif_hatch_title"),
    (GrowthEvents(evolved_to=5), "notif_evolve_title"),
    (GrowthEvents(graduated=DexEntry(1, 3, [1, 2, 3], balance.Rarity.COMMON)),
     "notif_graduate_title"),
])
def test_the_banner_and_the_toast_say_the_same_thing(events, expected):
    """One catalogue for both. Two wordings for one event is how they drift."""
    subject = store("ko", active=raising())
    subject._note_celebration(events)
    assert subject.celebration["title"] == l10n.t(expected, "ko")
    assert "%1" not in subject.celebration["detail"]


def test_a_ditto_banner_names_what_it_was_pretending_to_be():
    subject = store("ko", active=raising(ditto_disguise=4, ditto_revealed=True))
    subject._note_celebration(GrowthEvents(ditto_revealed=True))
    assert subject.celebration["kind"] == "ditto"
    assert "%1" not in subject.celebration["detail"]


def test_no_events_leaves_the_banner_alone():
    subject = store("ko", active=raising())
    subject._note_celebration(None)
    assert subject.celebration is None


# MARK: the whole catalogue


def test_every_placeholder_survives_translation():
    """A row that uses %1 in English has to use it in all seven, or that
    language silently loses the name, the number or the folder count."""
    for key, row in l10n.STRINGS.items():
        for placeholder in ("%1", "%2"):
            if placeholder not in row[0]:
                continue
            missing = [
                l10n.LANGUAGES[i]
                for i, value in enumerate(row)
                if placeholder not in value
            ]
            assert not missing, f"{key} drops {placeholder} in {missing}"


def test_the_companion_display_states_all_have_a_line():
    """`companion.display_state` is the only producer of these, so the set it
    can return is the set that has to resolve."""
    subject = store()
    for kind in companion.STATUS_MESSAGE:
        assert not subject._status_message(kind).startswith("status_"), kind


# MARK: the toast a shop action answers with


def _with_candy(language="ko"):
    subject = store(language=language, active=raising())
    subject.state.inventory["rareCandy"] = 1
    subject.state.used_since_install = balance.RARE_CANDY_PRICE
    return subject


def test_using_an_item_answers_in_the_chosen_language():
    """shop.py built "used Rare Candy" as an English literal, which made it the
    one toast a fully-localized UI could still answer a click with in English."""
    subject = _with_candy()
    assert subject.use_item("rareCandy") == l10n.t("shop_used", "ko").replace(
        "%1", l10n.t("item_rare_candy", "ko"))


def test_buying_answers_in_the_chosen_language():
    subject = _with_candy()
    assert subject.buy("rareCandy") == l10n.t("shop_bought", "ko").replace(
        "%1", l10n.t("item_rare_candy", "ko"))


def test_buying_an_egg_names_the_tier_it_guarantees():
    subject = store(language="ko", active=raising())
    subject.state.used_since_install = balance.egg_price(balance.Rarity.RARE)
    assert l10n.t("egg_rare", "ko") in subject.buy(f"egg:{balance.Rarity.RARE}")


def test_a_mint_reports_the_nature_it_rolled():
    subject = store(language="ko", active=raising())
    subject.state.inventory["mint"] = 1
    message = subject.use_item("mint")
    assert message == l10n.t("shop_nature_now", "ko").replace(
        "%1", l10n.nature_name(subject.state.active.nature, "ko"))


def test_an_item_that_crosses_no_threshold_still_gets_a_banner():
    """"The count went down and nothing happened" is indistinguishable from a
    bug, so the use announces itself even when nothing grew past a stage."""
    subject = _with_candy()
    subject.use_item("rareCandy")
    assert subject.celebration["kind"] == "item"
    assert l10n.t("item_rare_candy", "ko") in subject.celebration["title"]
    assert subject.celebration["detail"]

"""The suite must not be able to reach anything it did not create.

This is a guard on the conftest fixture rather than on any one module. Without
it the default paths resolve under the real home: `save.default_path()` becomes
the developer's own `~/.local/share/poketokenbar/companion.json`, a test that
builds a CompanionStore without a path loads it, and a test that persists writes
over it. That is not hypothetical — running the suite on the machine this was
developed on replaced the companion someone was raising with a test fixture, and
nothing failed.

Every default the project has is checked, because the next one added will
default the same way.
"""

from pathlib import Path

import pytest

from poketokenbar import commands, config, platform_paths, save, state
from poketokenbar.companion import CompanionState, DexEntry
from poketokenbar.companion_store import CompanionStore

DEFAULTS = {
    "save": save.default_path,
    "state": state.default_path,
    "config": config.default_path,
    "commands spool": commands.spool_dir,
}


@pytest.mark.parametrize("name", sorted(DEFAULTS))
def test_every_default_path_lands_inside_the_test_home(name, isolated_locations):
    resolved = Path(DEFAULTS[name]())
    assert resolved.is_relative_to(isolated_locations), (
        f"{name} resolves to {resolved}, which is outside the test home — "
        "a test writing there would be editing the real machine"
    )


def test_the_platform_bases_land_inside_the_test_home(isolated_locations):
    for base in (platform_paths.config_base, platform_paths.data_base,
                 platform_paths.state_base, platform_paths.cache_base):
        assert Path(base()).is_relative_to(isolated_locations), base.__name__


def test_a_store_with_no_path_persists_inside_the_test_home(isolated_locations):
    """The exact shape that did the damage: no save_path, then a write.

    `set_representative` persists, and it is called by a test that passes no
    path — so this ran against the real save file on every single run of the
    suite.
    """
    subject = CompanionStore(api=None, sprite_store=None)
    subject.state = CompanionState(
        dex=[DexEntry(1, 3, [1, 2, 3], "common")], language="en")

    subject.set_representative(2)

    written = save.default_path()
    assert written.is_file()
    assert written.is_relative_to(isolated_locations)


def test_a_store_with_no_path_reads_nothing_from_the_real_machine():
    """A fresh home has no save, so the state has to come up empty.

    If this ever loads a companion, the suite is reading someone's real one.
    """
    subject = CompanionStore(api=None, sprite_store=None)
    assert subject.state.active is None
    assert subject.state.dex == []



def test_the_suite_cannot_reach_the_network():
    """The guard itself, so a future rewrite of conftest cannot quietly drop it:
    upstream's tests called the limits endpoint with the developer's own login
    (671c1ec) and rewrote their real usage cache (d6d24a0)."""
    import urllib.request

    with pytest.raises(AssertionError, match="inject a fake"):
        urllib.request.urlopen("https://example.invalid/")

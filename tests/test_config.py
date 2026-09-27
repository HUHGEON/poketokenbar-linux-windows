import pytest

from poketokenbar import config


def test_load_returns_defaults_when_file_absent(tmp_path):
    values = config.load(tmp_path / "config.json")
    assert values["refresh_interval"] == 120
    assert values["show_tokens_in_menu"] is False
    assert values["show_limit_in_menu"] is True


def test_load_merges_partial_file_over_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"refresh_interval": 30}', encoding="utf-8")
    values = config.load(p)
    assert values["refresh_interval"] == 30
    assert values["warn_threshold"] == 80


def test_load_falls_back_to_defaults_on_corrupt_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    assert config.load(p) == config.DEFAULTS


def test_unknown_keys_are_dropped(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"nonsense": 1}', encoding="utf-8")
    assert "nonsense" not in config.load(p)


def test_set_value_coerces_to_the_default_type(tmp_path):
    p = tmp_path / "config.json"
    config.set_value(p, "refresh_interval", "30")
    config.set_value(p, "show_cost_in_menu", "true")
    values = config.load(p)
    assert values["refresh_interval"] == 30
    assert values["show_cost_in_menu"] is True


def test_set_value_rejects_unknown_key(tmp_path):
    with pytest.raises(KeyError):
        config.set_value(tmp_path / "config.json", "nonsense", "1")


def test_set_value_rejects_uncoercible_value(tmp_path):
    with pytest.raises(ValueError):
        config.set_value(tmp_path / "config.json", "refresh_interval", "soon")


def test_pet_position_survives_the_round_trip(tmp_path):
    """config.load drops any key with no default, so a coordinate written by the
    UI would vanish on the next read and the pet would jump home."""
    path = tmp_path / "config.json"
    config.set_value(path, "floating_pet_x", "640")
    config.set_value(path, "floating_pet_y", "300")
    values = config.load(path)
    assert values["floating_pet_x"] == 640
    assert values["floating_pet_y"] == 300


def test_every_key_the_extension_writes_has_a_default():
    """A key absent from DEFAULTS is accepted by the writer and dropped by the
    reader, which is the quietest possible way for a setting to not work."""
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "gnome-extension" / "poketokenbar@huhgeon.github.io"
    )
    written = set()
    for path in source.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        written.update(re.findall(r"""Config\.set\(\s*['"](\w+)['"]""", text))
    unknown = written - set(config.DEFAULTS)
    assert not unknown, f"extension writes settings with no default: {sorted(unknown)}"


def test_the_default_language_comes_from_the_desktop(monkeypatch):
    """It is read at import, from the machine's locale — which means any test
    that asserts a catalogue string has to say which language it wants, or it
    asserts whatever the developer's desktop is set to."""
    from poketokenbar import config, l10n

    assert config.DEFAULTS["language"] in l10n.LANGUAGES
    assert l10n.system_default("ko_KR.UTF-8") == "ko"
    assert l10n.system_default("pt_BR") == "pt"
    assert l10n.system_default("zz_ZZ") == "en", "an unknown locale falls back"

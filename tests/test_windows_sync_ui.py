import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QGridLayout, QLineEdit

from poketokenbar import l10n
from poketokenbar.ui.panels import CollectionPanel, DEX_COLUMNS, DEX_PER_PAGE
from poketokenbar.ui.reader import StateReader


def test_collection_filters_names_numbers_shiny_and_sorts(qt_app, tmp_path):
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en"), "dex": [
        {"species_id": 25, "name": "Pikachu", "rarity": "common", "is_shiny": False},
        {"species_id": 201, "name": "Unown [A]", "rarity": "uncommon", "is_shiny": True},
    ]}
    panel = CollectionPanel(reader)
    panel.update(reader.state)
    field = panel.findChild(QLineEdit, "collection_search")
    assert field is not None
    field.setText("#201")
    assert [e["species_id"] for e in panel._keep(reader.state["dex"])] == [201]
    field.setText("pikA")
    assert [e["species_id"] for e in panel._keep(reader.state["dex"])] == [25]
    field.setText("")
    panel._shiny_only = True
    assert [e["species_id"] for e in panel._keep(reader.state["dex"])] == [201]
    panel._shiny_only = False
    panel._sort = "name"
    assert [e["species_id"] for e in panel._keep(reader.state["dex"])] == [25, 201]
    panel.close()


def test_first_authentication_error_is_visible_without_cached_quotas(qt_app, tmp_path):
    from PySide6.QtWidgets import QLabel
    from poketokenbar.ui.panels import HomePanel
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en"),
                    "cursor_limits": {"error": "Cursor sign-in expired"},
                    "antigravity_limits": {"error": "Antigravity sign-in expired"},
                    "claude_accounts": [{"id": "additional", "root": "Work",
                                         "error": "Claude sign-in expired", "limits": {}}]}
    panel = HomePanel(reader)
    panel.update(reader.state)
    text = " ".join(w.text() for w in panel.findChildren(QLabel))
    for provider in ("Cursor", "Antigravity", "Claude"):
        assert f"{provider} sign-in expired" in text


def test_collection_sort_choices_match_available_data(qt_app, tmp_path):
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en")}
    panel = CollectionPanel(reader)
    panel.update(reader.state)
    assert panel.sort_picker.findData("newest") == -1
    assert panel.sort_picker.findData("number_desc") >= 0
    panel._show(True)
    assert panel.sort_picker.findData("newest") >= 0
    assert panel.sort_picker.findData("oldest") >= 0


def test_recap_is_reachable_and_shows_persisted_history(qt_app, tmp_path):
    from datetime import date
    from PySide6.QtWidgets import QLabel, QPushButton
    from poketokenbar.ui.app import Window
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en"), "usage_history": {
        "tokens": {date.today().isoformat(): 1200},
        "covered_since": date.today().isoformat()}, "catch_log": []}
    window = Window(reader)
    opener = window.findChild(QPushButton, "open_recap")
    assert opener is not None
    opener.click()
    assert window.stack.currentWidget() is window.recap
    assert any("1.2K" in w.text() for w in window.recap.findChildren(QLabel))
    window.close()


def test_collection_grid_is_four_by_four_without_horizontal_overflow(qt_app, tmp_path):
    assert (DEX_COLUMNS, DEX_PER_PAGE) == (4, 16)
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("ko"), "dex": [
        {"species_id": n, "name": "이상해꽃", "rarity": "legendary"}
        for n in range(1, 20)]}
    panel = CollectionPanel(reader)
    panel.resize(400, 560)
    panel.update(reader.state)
    panel.show()
    qt_app.processEvents()
    grids = [g for g in panel.findChildren(QGridLayout) if g.count() == 16]
    assert grids
    assert panel.body.minimumSizeHint().width() <= panel.scroll.viewport().width()
    panel.close()


def test_precious_egg_purchase_needs_confirmation(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QPushButton
    from poketokenbar.ui import panels
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en"), "shop": [{
        "key": "egg", "affordable": True, "requires_confirmation": True,
        "label": "Egg", "price_text": "1M"}]}
    sent = []
    monkeypatch.setattr(panels.commands, "enqueue", lambda *args: sent.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    panel = panels.ShopPanel(reader)
    panel.update(reader.state)
    buy = next(w for w in panel.findChildren(QPushButton) if w.text() == "Buy")
    buy.click()
    assert not sent
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    buy.click()
    assert sent == [("buy", {"key": "egg", "confirmed": True})]


def test_bulk_candy_control_enqueues_selected_count(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QSpinBox
    from poketokenbar.ui import panels
    reader = StateReader(tmp_path / "state.json")
    reader.state = {"strings": l10n.catalogue("en"), "bag": [{
        "key": "rareCandy", "label": "Rare Candy", "count": 12, "usable": True,
        "max_use_count": 8, "per_candy_xp": 100000000}]}
    sent = []
    monkeypatch.setattr(panels.commands, "enqueue", lambda *args: sent.append(args))
    panel = panels.BagPanel(reader)
    panel.update(reader.state)
    quantity = panel.findChild(QSpinBox, "candy_quantity")
    assert quantity is not None
    assert quantity.maximum() == 8
    quantity.setValue(5)
    next(w for w in panel.findChildren(QPushButton) if w.text() == "Use").click()
    assert sent == [("use", {"key": "rareCandy", "count": 5})]

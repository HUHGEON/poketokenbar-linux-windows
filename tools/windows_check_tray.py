"""The tray application constructs on Windows.

Offscreen, so nothing is displayed; what this shows is that the Qt classes the
tray uses exist and behave the same way on the platform it was written for as
they do in the container the tests run in.
"""

import sys
from pathlib import Path

# Run as `python tools/x.py` from the repo root, which puts tools/ on the path
# and not the package beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from poketokenbar.ui.app import TrayApp
from poketokenbar.ui.reader import StateReader


def main() -> int:
    app = QApplication([])
    tray = TrayApp(app, StateReader())
    tray.poll()
    window = tray.window
    window.refresh(tray.reader.state)

    print(f"  tooltip : {tray.tray.toolTip()}")
    print(f"  menu    : {[action.text() for action in tray.tray.contextMenu().actions()]}")
    print(f"  tabs    : {[item.text() for item in window.tabs._buttons.values()]}")

    # Every page has to build, not just the one that happens to be shown: a
    # panel that raises on this platform would otherwise be found by whoever
    # clicked the tab.
    for name in window.panels:
        window.show_tab(name)
    window.show_settings()
    window.show_tab("home")
    print(f"  pages   : {list(window.panels)} + settings")

    # A tray entry with no icon is invisible, and then there is no way to open
    # the window at all.
    assert not tray.tray.icon().isNull(), "the tray icon is empty"

    check_pet(tray)
    return 0


def check_pet(tray) -> None:
    """The pet survives being clicked.

    Clicking it opens the popup, and on Windows a tool window is owned by
    whichever window of the application was last active — so a pet that took
    activation became owned by the popup and disappeared with it. Nothing here
    can see that happen, but the flags that prevent it and the reassert that
    recovers from it are checked, and the click path runs on the platform it
    goes wrong on.
    """
    from PySide6.QtCore import Qt

    state = {"panel": {"sprite_path": ""},
             "config": {"floating_pet_enabled": True, "floating_pet_size": 96,
                        "floating_pet_x": 40, "floating_pet_y": 40}}
    tray._sync_pet(state)
    pet = tray.pet
    assert pet is not None, "the pet was not created"
    flags = pet.windowFlags()
    assert flags & Qt.WindowDoesNotAcceptFocus, "the pet can take activation"
    assert pet.testAttribute(Qt.WA_ShowWithoutActivating), "showing it activates it"

    tray.toggle_window()
    tray.toggle_window()
    tray._sync_pet(state)
    assert tray.pet is not None and tray.pet.isVisible(), "the pet went away"
    # Described, not printed: the Windows console is cp1252 and an emoji in a
    # print() takes the whole check down with a UnicodeEncodeError.
    print(f"  pet     : survives a click, fallback glyph {bool(pet.sprite.text())}")


if __name__ == "__main__":
    raise SystemExit(main())

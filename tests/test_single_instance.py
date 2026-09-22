"""A second daemon or tray must leave without touching shared state."""

import sys
import uuid

from poketokenbar.single_instance import SingleInstance


def test_only_one_process_can_hold_a_component_lock(tmp_path):
    name = f"test-{uuid.uuid4()}"
    first = SingleInstance(name, system=sys.platform, directory=tmp_path)
    second = SingleInstance(name, system=sys.platform, directory=tmp_path)

    try:
        assert first.acquire()
        assert not second.acquire()
        first.release()
        assert second.acquire()
    finally:
        first.release()
        second.release()


def test_daemon_and_ui_use_independent_locks(tmp_path):
    suffix = str(uuid.uuid4())
    daemon = SingleInstance(f"daemon-{suffix}", system=sys.platform, directory=tmp_path)
    ui = SingleInstance(f"ui-{suffix}", system=sys.platform, directory=tmp_path)

    try:
        assert daemon.acquire()
        assert ui.acquire()
    finally:
        daemon.release()
        ui.release()

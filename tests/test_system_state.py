from poketokenbar import system_state


def test_connectivity_monitor_only_fires_on_reconnection():
    readings = iter([True, False, False, True, True])
    now = [0.0]
    monitor = system_state.ConnectivityMonitor(
        probe=lambda: next(readings), clock=lambda: now[0], interval=1,
    )
    results = []
    for _ in range(5):
        results.append(monitor.reconnected())
        now[0] += 1
    assert results == [False, False, False, True, False]


def test_connectivity_monitor_throttles_probes():
    calls = []
    now = [0.0]
    monitor = system_state.ConnectivityMonitor(
        probe=lambda: calls.append(True) or True,
        clock=lambda: now[0], interval=10,
    )
    monitor.reconnected()
    now[0] = 5
    monitor.reconnected()
    assert len(calls) == 1


def test_power_state_is_cached(monkeypatch):
    times = iter([20.0, 21.0, 40.0])
    readings = iter([True, False])
    monkeypatch.setattr(system_state.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(system_state, "_read_power_saver", lambda: next(readings))
    monkeypatch.setattr(system_state, "_power_checked_at", 0.0)

    assert system_state.power_saver() is True
    assert system_state.power_saver() is True
    assert system_state.power_saver() is False

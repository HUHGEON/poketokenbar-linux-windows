from poketokenbar import notify
from poketokenbar.companion import DexEntry, GrowthEvents
from poketokenbar.notify import Notifier


class Spy:
    def __init__(self):
        self.sent = []

    def __call__(self, title, body="", urgency="normal"):
        self.sent.append((title, urgency))
        return True


def test_hatch_notifies():
    spy = Spy()
    Notifier(spy).companion(GrowthEvents(hatched=25))
    assert "hatched" in spy.sent[0][0].lower()


def test_evolution_and_graduation_notify():
    spy = Spy()
    Notifier(spy).companion(
        GrowthEvents(evolved_to=26, graduated=DexEntry(1, 3, [1, 2, 3], "common"))
    )
    assert len(spy.sent) == 2


def test_no_events_sends_nothing():
    spy = Spy()
    Notifier(spy).companion(GrowthEvents())
    Notifier(spy).companion(None)
    assert spy.sent == []


def test_limit_warning_fires_once_per_crossing():
    spy = Spy()
    n = Notifier(spy)
    n.limits({"session": 85.0}, warn=80, crit=95)
    n.limits({"session": 86.0}, warn=80, crit=95)
    n.limits({"session": 90.0}, warn=80, crit=95)
    assert len(spy.sent) == 1


def test_escalating_to_critical_fires_again():
    spy = Spy()
    n = Notifier(spy)
    n.limits({"session": 85.0}, warn=80, crit=95)
    n.limits({"session": 96.0}, warn=80, crit=95)
    assert len(spy.sent) == 2
    assert spy.sent[1][1] == "critical"


def test_dropping_below_warn_rearms():
    spy = Spy()
    n = Notifier(spy)
    n.limits({"session": 85.0}, warn=80, crit=95)
    n.limits({"session": 5.0}, warn=80, crit=95)  # window reset
    n.limits({"session": 85.0}, warn=80, crit=95)
    assert len(spy.sent) == 2


def test_below_warn_never_notifies():
    spy = Spy()
    Notifier(spy).limits({"session": 20.0, "weekly": 5.0}, warn=80, crit=95)
    assert spy.sent == []


def test_windows_are_tracked_independently():
    spy = Spy()
    n = Notifier(spy)
    n.limits({"session": 85.0, "weekly": 10.0}, warn=80, crit=95)
    n.limits({"session": 85.0, "weekly": 85.0}, warn=80, crit=95)
    assert len(spy.sent) == 2


# MARK: per-platform delivery


def test_notification_process_hides_console(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "background_options", lambda: {"creationflags": 0x08000000})
    monkeypatch.setattr(notify.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs))
    assert notify._run(["powershell", "-NonInteractive"])
    assert calls[0]["creationflags"] == 0x08000000


def test_each_platform_uses_its_own_route(monkeypatch):
    """A tracker must not stop counting because it could not post a toast, so
    the backend is chosen rather than assumed."""
    calls = []
    monkeypatch.setattr(notify, "_run", lambda command: calls.append(command) or True)
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"/usr/bin/{name}")

    notify.send("t", "b", system="linux")
    assert calls[-1][0] == "notify-send"

    notify.send("t", "b", system="darwin")
    assert calls[-1][0].endswith("osascript")

    notify.send("t", "b", system="win32")
    assert "powershell" in calls[-1][0]


def test_a_missing_backend_is_not_an_error(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda _name: None)
    for system in ("linux", "darwin", "win32"):
        assert notify.send("t", "b", system=system) is False
        assert notify.available(system) is False


def test_windows_falls_back_to_pwsh(monkeypatch):
    """PowerShell 7 installs as pwsh and may be the only one present."""
    calls = []
    monkeypatch.setattr(notify, "_run", lambda command: calls.append(command) or True)
    monkeypatch.setattr(
        notify.shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None
    )
    assert notify.send("t", "b", system="win32") is True
    assert "pwsh" in calls[-1][0]


def test_windows_script_escapes_quotes_and_markup():
    """A PowerShell string ends at a quote and the toast is XML, so a name
    carrying either would produce a notification that never arrives."""
    script = notify.windows_script("Farfetch'd & <b>", "it's 100% done")
    assert "Farfetch''d" in script, "single quotes are doubled for PowerShell"
    assert "&amp;" in script and "&lt;b&gt;" in script, "markup is escaped for the XML"
    assert "it''s" in script


def test_windows_script_names_the_app():
    assert notify.APP_NAME in notify.windows_script("t", "b")


def test_a_wedged_backend_cannot_hold_up_a_poll():
    """Notifications are cosmetic; waiting on one is not."""
    assert notify.TIMEOUT_SECONDS <= 10


def test_a_backend_that_raises_is_swallowed(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("no such process")

    monkeypatch.setattr(notify.subprocess, "run", explode)
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"/usr/bin/{name}")
    for system in ("linux", "darwin", "win32"):
        assert notify.send("t", "b", system=system) is False

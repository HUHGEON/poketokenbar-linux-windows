"""Updating in place.

Reinstalling meant finding the repo again and running a script, which is
enough friction that a fix nobody installs may as well not exist. The risk is
the other way round: an update that goes wrong replaces a working install with
nothing. Every check that stands between those two is here, and none of these
tests touch the network.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from poketokenbar import updater as updater_module
from poketokenbar.updater import UpdateError, Updater


def make_install(tmp_path: Path, revision: str = "a" * 40) -> Path:
    """The shape install.sh and install.ps1 leave behind."""
    root = tmp_path / "poketokenbar"
    app = root / "app"
    (app / "poketokenbar" / "ui").mkdir(parents=True)
    (root / "venv").mkdir()
    for name in ("__init__.py", "daemon.py", "state.py"):
        (app / "poketokenbar" / name).write_text("x = 1\n", encoding="utf-8")
    (app / "poketokenbar" / "ui" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (app / "REVISION").write_text(revision, encoding="utf-8")
    return root


def make_zip(files: dict[str, str], top: str = "repo-abc") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{top}/{name}", body)
    return buffer.getvalue()


def good_tree() -> dict[str, str]:
    return {
        "poketokenbar/__init__.py": "__version__ = '9'\n",
        "poketokenbar/daemon.py": "def main(): return 0\n",
        "poketokenbar/state.py": "SCHEMA_VERSION = 1\n",
        "poketokenbar/ui/__init__.py": "",
        "poketokenbar/ui/app.py": "def main(): return 0\n",
        "README.md": "not part of the package\n",
    }


@pytest.fixture
def offline(monkeypatch):
    """Answers both endpoints the updater uses, with no network."""
    calls = {"commits": 0, "zip": 0}
    state = {"sha": "b" * 40, "zip": make_zip(good_tree())}

    def fake_get(url, timeout=15.0):
        if "commits" in url:
            calls["commits"] += 1
            return json.dumps({"sha": state["sha"]}).encode()
        calls["zip"] += 1
        return state["zip"]

    monkeypatch.setattr(updater_module, "_get", fake_get)
    return state, calls


# MARK: which installs can be updated


def test_a_real_install_is_recognised(tmp_path):
    root = make_install(tmp_path)
    module = root / "app" / "poketokenbar" / "updater.py"
    assert updater_module.install_root(str(module)) == root.resolve()


def test_a_git_checkout_is_not_an_install(tmp_path):
    """Overwriting one would throw away whatever is being worked on."""
    checkout = tmp_path / "repo" / "poketokenbar"
    checkout.mkdir(parents=True)
    assert updater_module.install_root(str(checkout / "updater.py")) is None


def test_a_copy_without_a_venv_is_not_an_install(tmp_path):
    root = make_install(tmp_path)
    (root / "venv").rmdir()
    module = root / "app" / "poketokenbar" / "updater.py"
    assert updater_module.install_root(str(module)) is None


def test_an_unsupported_install_offers_nothing(tmp_path):
    subject = Updater(root=None)
    assert subject.check() == ""
    assert subject.payload()["supported"] is False
    with pytest.raises(UpdateError):
        subject.apply()


# MARK: checking


def test_a_newer_commit_is_offered(tmp_path, offline):
    subject = Updater(root=make_install(tmp_path))
    assert subject.check() == "b" * 40
    assert subject.payload()["available_short"] == "bbbbbbb"


def test_the_same_commit_is_not(tmp_path, offline):
    subject = Updater(root=make_install(tmp_path, revision="b" * 40))
    assert subject.check() == ""


def test_an_install_that_cannot_say_what_it_is_is_left_alone(tmp_path, offline):
    """Empty REVISION means "unknown", not "out of date", and offering an
    update that cannot be verified as newer would be a guess."""
    subject = Updater(root=make_install(tmp_path, revision=""))
    assert subject.check() == ""


def test_checking_is_rate_limited(tmp_path, offline):
    """Unauthenticated GitHub allows sixty requests an hour for everything on
    the machine, not just this."""
    _state, calls = offline
    now = [1000.0]
    subject = Updater(root=make_install(tmp_path), clock=lambda: now[0])
    subject.check()
    subject.check()
    assert calls["commits"] == 1

    now[0] += updater_module.MIN_CHECK_INTERVAL + 1
    subject.check()
    assert calls["commits"] == 2


def test_a_forced_check_ignores_the_interval(tmp_path, offline):
    _state, calls = offline
    subject = Updater(root=make_install(tmp_path), clock=lambda: 1000.0)
    subject.check()
    subject.check(force=True)
    assert calls["commits"] == 2


def test_no_network_is_not_an_error_in_the_panel(tmp_path, monkeypatch):
    """A machine offline has to behave like one that is up to date."""
    def explode(url, timeout=15.0):
        raise OSError("no route to host")

    monkeypatch.setattr(updater_module, "_get", explode)
    subject = Updater(root=make_install(tmp_path))
    assert subject.check() == ""
    assert subject.last_error
    assert subject.payload()["available"] == ""


# MARK: applying


def test_applying_replaces_the_source_and_records_the_revision(tmp_path, offline):
    root = make_install(tmp_path)
    subject = Updater(root=root)
    stale = root / "app" / "poketokenbar" / "gone_in_the_new_version.py"
    stale.write_text("x = 1\n", encoding="utf-8")

    assert subject.apply() == "b" * 40
    assert (root / "app" / "REVISION").read_text(encoding="utf-8") == "b" * 40
    assert not stale.exists(), "a file the new version deleted survived"
    assert (root / "app" / "poketokenbar" / "ui" / "app.py").is_file()
    assert "__version__" in (
        root / "app" / "poketokenbar" / "__init__.py").read_text(encoding="utf-8")


def test_nothing_outside_the_package_is_installed(tmp_path, offline):
    """The archive carries the whole repository; only the package is wanted."""
    root = make_install(tmp_path)
    Updater(root=root).apply()
    assert not (root / "app" / "README.md").exists()


def test_the_staging_directories_are_cleaned_up(tmp_path, offline):
    root = make_install(tmp_path)
    Updater(root=root).apply()
    leftovers = list((root / "app").glob("poketokenbar.*"))
    assert not leftovers, f"left behind: {leftovers}"


@pytest.mark.parametrize("missing", [
    "poketokenbar/daemon.py", "poketokenbar/ui/app.py", "poketokenbar/__init__.py",
])
def test_an_incomplete_download_is_refused(tmp_path, offline, missing):
    """It would replace a working install with something that cannot start."""
    state, _calls = offline
    files = good_tree()
    del files[missing]
    state["zip"] = make_zip(files)

    root = make_install(tmp_path)
    with pytest.raises(UpdateError, match="missing"):
        Updater(root=root).apply()
    assert (root / "app" / "poketokenbar" / "daemon.py").is_file(), "the install was damaged"


def test_a_download_that_does_not_compile_is_refused(tmp_path, offline):
    state, _calls = offline
    files = good_tree()
    files["poketokenbar/daemon.py"] = "def main( :\n"
    state["zip"] = make_zip(files)

    root = make_install(tmp_path)
    with pytest.raises(UpdateError, match="compile"):
        Updater(root=root).apply()
    assert (root / "app" / "REVISION").read_text(encoding="utf-8") == "a" * 40


def test_a_download_that_is_not_a_zip_is_refused(tmp_path, offline):
    state, _calls = offline
    state["zip"] = b"404: Not Found"
    with pytest.raises(UpdateError, match="zip"):
        Updater(root=make_install(tmp_path)).apply()


def test_an_archive_without_the_package_is_refused(tmp_path, offline):
    state, _calls = offline
    state["zip"] = make_zip({"docs/readme.md": "hello"})
    with pytest.raises(UpdateError, match="no poketokenbar"):
        Updater(root=make_install(tmp_path)).apply()


def test_an_archive_that_writes_outside_its_directory_is_refused(tmp_path, offline):
    """A zip entry may name any path it likes, and extracting one that climbs
    out writes wherever it points, as whoever is running the daemon."""
    state, _calls = offline
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in good_tree().items():
            archive.writestr(f"repo/{name}", body)
        archive.writestr("repo/../../escaped.txt", "owned")
    state["zip"] = buffer.getvalue()

    with pytest.raises(UpdateError, match="escapes"):
        Updater(root=make_install(tmp_path)).apply()
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_a_bad_commits_response_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(updater_module, "_get", lambda url, timeout=15.0: b"{}")
    with pytest.raises(UpdateError):
        updater_module.latest_revision()


# MARK: what the rest of the app sees


def test_the_payload_says_enough_to_render_a_row(tmp_path, offline):
    subject = Updater(root=make_install(tmp_path))
    subject.check()
    payload = subject.payload()
    assert payload["supported"] is True
    assert payload["installed_short"] == "aaaaaaa"
    assert payload["available_short"] == "bbbbbbb"
    assert payload["error"] == ""


def test_the_daemon_ships_the_update_section():
    from poketokenbar import state
    from poketokenbar.models import DailyUsage

    payload = state.build({"claude_code": DailyUsage(date="2026-09-03")}, {}, [])
    assert payload["update"] == {"supported": False}


def test_the_installers_record_the_revision_they_installed():
    """Without it an install cannot say what it is, and the updater refuses to
    offer anything rather than guess."""
    root = Path(__file__).resolve().parent.parent
    assert "REVISION" in (root / "install.sh").read_text(encoding="utf-8")
    assert "rev-parse HEAD" in (root / "install.sh").read_text(encoding="utf-8")
    windows = (root / "packaging" / "windows" / "install.ps1").read_text(encoding="utf-8")
    assert "REVISION" in windows and "rev-parse HEAD" in windows

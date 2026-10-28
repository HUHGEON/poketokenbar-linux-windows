import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    """Register the one custom marker.

    Declared here as well as in pyproject: the ini registration is not picked
    up when pytest is invoked with a different rootdir, and an unregistered
    mark is a warning on every run.
    """
    config.addinivalue_line(
        "markers",
        "network: reaches the internet; skips itself when there is none")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Every variable that can move a path this project reads or writes.
_LOCATION_VARIABLES = (
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "GROK_HOME",
    "KIMI_CODE_HOME",
    "COPILOT_HOME",
    "CURSOR_DATA_DIR",
    "CURSOR_SESSION_TOKEN",
    "CURSOR_USAGE_API",
    "ANTIGRAVITY_TOKEN_FILE",
    "CLOUD_CODE_URL",
    "KIRO_HOME",
    "KIRO_CLI_HOME",
    "HERMES_HOME",
    "OPENCODE_DATA_DIR",
    "ANTIGRAVITY_HOME",
    "PI_CODING_AGENT_DIR",
    "PI_CODING_AGENT_SESSION_DIR",
    "OMP_CODING_AGENT_DIR",
    # Windows' equivalents of the XDG bases. Cleared for the same reason, and so
    # that with HOME redirected below they fall back inside it.
    "APPDATA",
    "LOCALAPPDATA",
)

# What `Path.home()` reads: HOME on POSIX, USERPROFILE on Windows.
_HOME_VARIABLES = ("HOME", "USERPROFILE")

# Cleared, the command spool falls back to the shared temporary directory, which
# every user of the machine and every concurrent run of the suite would share.
# It gets a directory inside the test home instead.
# Where the command spool goes, per platform: XDG_RUNTIME_DIR on Linux, TMPDIR
# on macOS, TEMP or TMP on Windows.
_RUNTIME_VARIABLES = ("XDG_RUNTIME_DIR", "TMPDIR", "TEMP", "TMP")


@pytest.fixture(autouse=True)
def isolated_locations(monkeypatch, tmp_path_factory):
    """Give each test a home of its own, and clear every path override.

    Clearing the overrides came first: a provider given an explicit `home=`
    still reads the ambient environment for its XDG base, so on a machine with
    XDG_CONFIG_HOME set the Cursor tests looked in that directory instead of the
    temporary home and found nothing. That passed locally and failed on CI,
    which is the worst version of it.

    Redirecting HOME is the other half, and the half that had teeth. Clearing
    XDG_DATA_HOME makes `save.default_path()` fall back to `~/.local/share` —
    the *real* one — so a test that constructed a CompanionStore without a path
    read the developer's own save, and one that persisted overwrote it. Running
    the suite on this machine deleted the Pokemon someone was raising and
    replaced it with a test fixture. A test must not be able to reach anything
    it did not create.
    """
    home = tmp_path_factory.mktemp("home")
    for variable in _LOCATION_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    for variable in _HOME_VARIABLES:
        monkeypatch.setenv(variable, str(home))
    runtime = home / "run"
    runtime.mkdir(exist_ok=True)
    # Every variable the command spool can land in, on every platform, not just
    # the one the suite happens to be running on. XDG_RUNTIME_DIR alone left
    # Windows resolving the spool into the shared %TEMP%, which is outside the
    # test home — caught by the guard in test_path_isolation, on the Windows
    # job, where it is the only place it can be caught.
    for variable in _RUNTIME_VARIABLES:
        monkeypatch.setenv(variable, str(runtime))
    return home


@pytest.fixture(scope="session")
def qt_app():
    """The one QApplication; Qt allows exactly one per process.

    Here rather than in a single test module because more than one file needs
    it, and a second QApplication is not something a fixture can hand out.
    Skips the test when PySide6 is absent, which is how the Qt front end stays
    optional.
    """
    pytest.importorskip("PySide6", reason="the Qt front end is optional")

    import os
    import sys

    # Must be set before a QApplication exists, and it is process-wide.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    existing = getattr(sys, "_poketokenbar_qt", None)
    if existing is not None:
        return existing[0]
    # Parked on `sys`, not in a module global: Qt segfaults if the application
    # is destroyed while widgets and their timers are still alive, and at
    # interpreter shutdown module globals are cleared in an order nothing here
    # controls. The crash that avoids happens after every test has passed,
    # which makes it invisible in the report and fatal to the exit code.
    application = QApplication.instance() or QApplication([])
    sys._poketokenbar_qt = (application, [])
    return application

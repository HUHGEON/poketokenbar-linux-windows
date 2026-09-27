import sys
from pathlib import Path

import pytest

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
    "COPILOT_HOME",
    "CURSOR_DATA_DIR",
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
_RUNTIME_VARIABLE = "XDG_RUNTIME_DIR"


@pytest.fixture(scope="session", autouse=True)
def no_live_network():
    """Nothing in the suite may open a socket.

    Ports the intent of upstream 671c1ec and d6d24a0: their tests reached the
    real limits endpoint with the developer's own login, and rewrote the real
    usage cache. Here the paths are already redirected; this closes the other
    half — a new test that forgets to inject a fake fails loudly instead of
    calling PokéAPI, GitHub or api.anthropic.com from CI.
    """
    import urllib.request

    real = urllib.request.urlopen

    def refuse(request, *args, **kwargs):
        url = getattr(request, "full_url", request)
        raise AssertionError(
            f"a test tried to open {url}; inject a fake instead of calling the network")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(urllib.request, "urlopen", refuse)
        yield
    urllib.request.urlopen = real


@pytest.fixture(scope="session", autouse=True)
def isolated_session_locations(tmp_path_factory):
    """The same isolation for fixtures wider than one test.

    A module- or session-scoped fixture is set up before any function-scoped
    one, so `isolated_locations` below did not cover it. The contract tests
    build their CompanionStore in module-scoped fixtures, and with HOME still
    the developer's own those stores loaded the real save; once loading a save
    could migrate and persist it, running the suite rewrote the real file.
    """
    home = tmp_path_factory.mktemp("session-home")
    with pytest.MonkeyPatch.context() as patch:
        for variable in _LOCATION_VARIABLES:
            patch.delenv(variable, raising=False)
        for variable in _HOME_VARIABLES:
            patch.setenv(variable, str(home))
        runtime = home / "run"
        runtime.mkdir(exist_ok=True)
        patch.setenv(_RUNTIME_VARIABLE, str(runtime))
        yield home


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
    monkeypatch.setenv(_RUNTIME_VARIABLE, str(runtime))
    return home

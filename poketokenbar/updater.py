"""Updating in place, without reinstalling.

The macOS app checks GitHub releases and then hands the job to Homebrew, or
opens the release page. Neither exists here — an install is a copied source
tree beside a venv — which makes the update simpler rather than harder: fetch
the tree, check it, swap the directory, restart.

Nothing here touches the save, the config or the sprite cache. They live
outside the install root precisely so that replacing the code cannot lose a
Pokedex, and this is the moment that promise has to hold.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "HUHGEON/poketokenbar-linux-windows"
BRANCH = "gnome"
API = f"https://api.github.com/repos/{REPO}"
USER_AGENT = "poketokenbar-updater"

# The file the installer writes so an install knows which commit it is. Kept
# beside the copied source rather than inside the package: it describes the
# install, not the code.
REVISION_FILE = "REVISION"

# Unauthenticated GitHub allows 60 requests an hour per address. One check an
# hour leaves that entirely to everything else on the machine.
MIN_CHECK_INTERVAL = 3600

# What a tree has to contain before it is allowed to replace a working install.
REQUIRED = (
    "poketokenbar/__init__.py",
    "poketokenbar/daemon.py",
    "poketokenbar/state.py",
    "poketokenbar/ui/app.py",
)


class UpdateError(Exception):
    """The update could not be applied. The install is untouched."""


def install_root(module_file: str | None = None) -> Path | None:
    """The directory an installed copy lives in, or None when not installed.

    An install is `<root>/app/poketokenbar` beside `<root>/venv`. Running from
    a git checkout looks nothing like that, and updating one by overwriting it
    would throw away whatever was being worked on — so it is refused instead.
    """
    package = Path(module_file or __file__).resolve().parent
    app = package.parent
    if app.name != "app":
        return None
    root = app.parent
    return root.resolve() if (root / "venv").is_dir() else None


def installed_revision(root: Path | None = None) -> str:
    root = root or install_root()
    if root is None:
        return ""
    try:
        return (root / "app" / REVISION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _get(url: str, timeout: float = 15.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise UpdateError(f"{url} returned {response.status}")
        return response.read()


def latest_revision(timeout: float = 15.0) -> str:
    """The head commit of the branch this is installed from."""
    raw = _get(f"{API}/commits/{BRANCH}", timeout)
    try:
        return str(json.loads(raw)["sha"])
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateError(f"unexpected response from GitHub: {exc}") from exc


class Updater:
    """Checks for a newer commit, and applies one when asked.

    The check is rate-limited and never raises: a machine with no network must
    behave exactly like one that is up to date, because an update banner is not
    worth an error in the panel.
    """

    def __init__(self, root: Path | None = None, clock=time.time) -> None:
        self.root = root if root is not None else install_root()
        self._clock = clock
        self._checked_at: float | None = None
        self.available: str = ""
        self.last_error: str = ""

    @property
    def installed(self) -> str:
        return installed_revision(self.root)

    def check(self, force: bool = False) -> str:
        """The newer revision if there is one, else "". Never raises."""
        if self.root is None:
            return ""
        now = self._clock()
        if not force and self._checked_at is not None:
            if now - self._checked_at < MIN_CHECK_INTERVAL:
                return self.available
        self._checked_at = now
        try:
            latest = latest_revision()
        except (UpdateError, urllib.error.URLError, OSError, TimeoutError) as exc:
            self.last_error = str(exc)
            return self.available
        self.last_error = ""
        installed = self.installed
        # No recorded revision means an install from before this existed. It is
        # not "out of date", it is "unknown", and offering an update that
        # cannot be verified as newer would be a guess.
        self.available = latest if installed and latest != installed else ""
        return self.available

    def payload(self) -> dict:
        return {
            "supported": self.root is not None,
            "installed": self.installed,
            "installed_short": self.installed[:7],
            "available": self.available,
            "available_short": self.available[:7],
            "error": self.last_error,
        }

    # --- applying ----------------------------------------------------------

    def apply(self) -> str:
        """Replace the installed source with the branch head.

        Returns the revision now installed. Raises UpdateError with the install
        untouched if anything about the downloaded tree is wrong.
        """
        if self.root is None:
            raise UpdateError("not an installed copy; update the checkout instead")
        revision = latest_revision()
        source = self._download(revision)
        self._swap(source)
        (self.root / "app" / REVISION_FILE).write_text(revision, encoding="utf-8")
        self.available = ""
        return revision

    def _download(self, revision: str) -> Path:
        """Fetch the tree and return the directory holding `poketokenbar/`."""
        raw = _get(f"https://codeload.github.com/{REPO}/zip/{revision}", timeout=120)
        # Resolved, because the containment check below compares against it:
        # /var is a symlink to /private/var on macOS, so an unresolved staging
        # directory makes every entry look like it escapes.
        staging = Path(tempfile.mkdtemp(prefix="poketokenbar-update-")).resolve()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                # A zip entry may name any path it likes. Extracting one that
                # climbs out of the staging directory would write wherever it
                # pointed, as whoever is running the daemon.
                for name in archive.namelist():
                    target = (staging / name).resolve()
                    if not target.is_relative_to(staging):
                        raise UpdateError(f"archive escapes its directory: {name}")
                archive.extractall(staging)
        except zipfile.BadZipFile as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateError(f"the download is not a zip file: {exc}") from exc

        roots = [p for p in staging.iterdir() if (p / "poketokenbar").is_dir()]
        if not roots:
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateError("the download has no poketokenbar directory")
        tree = roots[0]
        self._verify(tree)
        return tree

    def _verify(self, tree: Path) -> None:
        """Refuse a tree that is missing pieces or does not compile.

        A half-downloaded or renamed tree that replaced a working install would
        leave nothing to run and no way to get the old one back.
        """
        missing = [name for name in REQUIRED if not (tree / name).is_file()]
        if missing:
            raise UpdateError(f"the download is missing {', '.join(missing)}")
        result = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(tree / "poketokenbar")],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise UpdateError(f"the download does not compile: {result.stdout.strip()}")

    def _swap(self, tree: Path) -> None:
        """Put the new source in place, keeping the old one until it is in.

        A copy over the top would leave a file the new version deleted, and a
        delete-then-copy leaves nothing at all if the copy fails halfway.
        """
        app = self.root / "app"
        current = app / "poketokenbar"
        incoming = app / "poketokenbar.incoming"
        previous = app / "poketokenbar.previous"
        for path in (incoming, previous):
            shutil.rmtree(path, ignore_errors=True)

        shutil.copytree(tree / "poketokenbar", incoming)
        if current.exists():
            current.rename(previous)
        try:
            incoming.rename(current)
        except OSError:
            if previous.exists() and not current.exists():
                previous.rename(current)
            raise
        shutil.rmtree(previous, ignore_errors=True)
        shutil.rmtree(tree.parent, ignore_errors=True)


def restart_self() -> None:
    """Re-exec this process so the new code is what is running.

    execv rather than spawning: the daemon is started by a login entry or a
    unit, and a second copy would double every count.
    """
    os.execv(sys.executable, [sys.executable, "-m", _module_name()] + sys.argv[1:])


def _module_name() -> str:
    main = sys.modules.get("__main__")
    package = getattr(main, "__package__", "") or ""
    spec = getattr(main, "__spec__", None)
    if spec is not None and spec.name:
        return spec.name.removesuffix(".__main__")
    return package or "poketokenbar.daemon"

#!/usr/bin/env bash
# Installs the daemon, poketokenctl, and whichever desktop front end fits.
#
# Everything lands under $HOME. Nothing here needs root, and nothing is written
# outside the user's own directories.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app="$HOME/.local/share/poketokenbar/app"
venv="$HOME/.local/share/poketokenbar/venv"
extension_uuid="poketokenbar@huhgeon.github.io"

# Which front end to install. Default is "auto": whichever desktop is running.
#   gnome   the Shell extension
#   plasma  the Plasma widgets
#   qt      the tray application, which needs no particular desktop
#   none    daemon only
ui="${POKETOKENBAR_UI:-auto}"
# Set to skip the systemd bits, which is what the container test does.
no_service="${POKETOKENBAR_NO_SERVICE:-}"

copy_tree() {
  # rsync is not installed everywhere; cp is, and the delete is explicit.
  local src="$1" dest="$2"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -R "$src/." "$dest/"
}

echo "==> installing python package to $app"
copy_tree "$here/poketokenbar" "$app/poketokenbar"

# Which commit this install came from, so the app can tell whether GitHub has
# a newer one without carrying a git checkout around. Unknown is written as
# empty rather than guessed: an install that cannot say what it is must not be
# offered an update it cannot verify is newer.
revision="$(git -C "$here" rev-parse HEAD 2>/dev/null || true)"
printf '%s' "$revision" > "$app/REVISION"

echo "    revision ${revision:-unknown}"

echo "==> creating venv at $venv"
[ -d "$venv" ] || python3 -m venv "$venv"
"$venv/bin/pip" install -q --upgrade pip
# Optional: roughly twice as fast on a large log corpus, and the code falls
# back to the standard library when it is missing.
"$venv/bin/pip" install -q orjson || echo "    orjson unavailable; falling back to json"

echo "==> installing poketokenctl"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/poketokenctl" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$app" exec "$venv/bin/python" -m poketokenbar.ctl "\$@"
EOF
chmod +x "$HOME/.local/bin/poketokenctl"

install_gnome() {
  local dest="$HOME/.local/share/gnome-shell/extensions/$extension_uuid"
  echo "==> installing GNOME Shell extension to $dest"
  copy_tree "$here/gnome-extension/$extension_uuid" "$dest"

  # The UI goes in a directory of its own for this release, named in `current`.
  # extension.js imports main.js from there on every enable, and a directory
  # the session has never loaded is new code to it — which is what lets an
  # update show without logging out. copy_tree already removed older ones.
  local ui_dir="lib-$(date +%Y%m%d%H%M%S)"
  mv "$dest/lib" "$dest/$ui_dir"
  printf '%s\n' "$ui_dir" > "$dest/current"

  # The commonest way this "installs fine" and then does not appear: an
  # extension whose shell-version omits the running Shell is hidden outright —
  # no error and no entry in the list. Say so here rather than let someone hunt.
  local running declared
  running="$(gnome-shell --version 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)"
  declared="$(grep -o '"[0-9]\+"' "$dest/metadata.json" | tr -d '"' | tr '\n' ' ')"
  if [ -n "$running" ] && ! echo " $declared " | grep -q " $running "; then
    echo
    echo "    !! this GNOME Shell is $running, and the extension declares: $declared"
    echo "       it will not appear in the list until that version is added to"
    echo "       $dest/metadata.json — please open an issue with your version."
    echo
  fi

  # Already running in this session: turn it off and on, so it loads the
  # release just installed. Nothing to do in a session without GNOME Shell.
  if command -v gnome-extensions >/dev/null 2>&1 \
      && gnome-extensions list --enabled 2>/dev/null | grep -qx "$extension_uuid"; then
    gnome-extensions disable "$extension_uuid" && gnome-extensions enable "$extension_uuid"
    echo "    reloaded the running extension: the popup now shows this release."
    echo "    (the first install with live reload still needs one log out; after that it does not)"
  else
    echo "    enable it in the Extensions app, or:"
    echo "      gnome-extensions enable $extension_uuid"
    echo "    on Xorg press Alt+F2 then r to reload the shell; on Wayland log out and back in."
  fi
  echo "    if it does not appear:  journalctl --user -b -o cat /usr/bin/gnome-shell | tail -40"
}

install_plasma() {
  echo "==> installing Plasma widgets"
  for pkg in org.kde.plasma.poketokenbar org.kde.plasma.poketokenpet; do
    copy_tree "$here/plasmoid/$pkg" "$HOME/.local/share/plasma/plasmoids/$pkg"
  done
}

install_qt() {
  # The same tray application Windows uses. It is plain Qt and needs no
  # particular desktop, which is the only option someone on XFCE, Cinnamon or a
  # tiling compositor has — there is no panel to extend and no plasmoid to load.
  echo "==> installing the Qt tray application"
  if ! "$venv/bin/pip" install -q PySide6-Essentials; then
    echo "    !! PySide6 could not be installed; the tray application needs it." >&2
    echo "       The daemon still works, and poketokenctl can drive it." >&2
    return 0
  fi
  cat > "$HOME/.local/bin/poketokenbar" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$app" exec "$venv/bin/python" -m poketokenbar.ui.app "\$@"
EOF
  chmod +x "$HOME/.local/bin/poketokenbar"

  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/poketokenbar.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PokeTokenBar
Exec=$HOME/.local/bin/poketokenbar
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
  echo "    run it now with: poketokenbar"
}

case "$ui" in
  gnome) install_gnome ;;
  plasma) install_plasma ;;
  qt) install_qt ;;
  none) echo "==> skipping the desktop front end" ;;
  auto)
    desktop="${XDG_CURRENT_DESKTOP:-}"
    case "$desktop" in
      *GNOME*) install_gnome ;;
      *KDE*) install_plasma ;;
      *)
        # Anything else — XFCE, Cinnamon, a tiling compositor, or a session with
        # no desktop set at all. There is no panel to extend and no plasmoid to
        # load, so the tray application is the one that will actually work.
        echo "==> XDG_CURRENT_DESKTOP is '${desktop:-unset}'; installing the tray application"
        echo "    (force another with POKETOKENBAR_UI=gnome or =plasma)"
        install_qt
        ;;
    esac
    ;;
  *)
    echo "unknown POKETOKENBAR_UI=$ui (expected gnome, plasma, qt or none)" >&2
    exit 2
    ;;
esac

if [ -n "$no_service" ]; then
  echo "==> skipping the systemd unit (POKETOKENBAR_NO_SERVICE set)"
  echo "==> done"
  exit 0
fi

echo "==> installing systemd unit"
mkdir -p "$HOME/.config/systemd/user"
install -m644 "$here/systemd/poketokend.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now poketokend.service
# enable --now leaves a daemon that is already running on the old code.
systemctl --user restart poketokend.service

echo "==> done. check: systemctl --user status poketokend"

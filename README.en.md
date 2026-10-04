<div align="center">

# PokeTokenBar for GNOME

**Your AI coding tokens, hatched into Pokémon — in the GNOME panel and the Windows tray.**

[![GNOME Shell](https://img.shields.io/badge/GNOME%20Shell-45%2B-4a86cf?logo=gnome&logoColor=white)](https://gnome.org)
[![Windows](https://img.shields.io/badge/Windows-10%2B-0078d4?logo=windows&logoColor=white)](#windows)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)

[한국어](README.md) · **English**

**An unofficial GNOME port of [PokeTokenBar](https://github.com/chattymin/PokeTokenBar) by [chattymin](https://github.com/chattymin),**
**built on the Linux daemon from [poketokenbar-plasma](https://github.com/rubensanchezrivero/poketokenbar-plasma) by [rubensanchezrivero](https://github.com/rubensanchezrivero).**

</div>

The AI coding tokens you are already burning become a growing Pokémon companion
in your GNOME panel — or, on Windows and desktops with no panel to extend, in
the notification area. Spend tokens, hatch an egg, evolve it along its real
evolution line, graduate it into your Pokédex, and start again. Underneath the
companion is a precise usage tracker — today's spend and cost, and the official
5-hour and weekly limits, read straight from your local logs.

Growth and shop-price difficulty can be tuned independently from 10% to 200%
of the default balance. On Windows, clicking the notification-area icon opens
the full panel as an anchored popover instead of a separate taskbar window.

> Usage is read directly from local files (`totalTokens` = input + output +
> cache, local date). No external usage CLI, no account, no network needed for
> the numbers. Unofficial, non-commercial Pokémon fan project — see
> [License & disclaimer](#license--disclaimer).

## Status

| | |
|---|---|
| Usage daemon (12 providers) | ✅ done |
| GNOME Shell extension | ✅ **run on a real desktop** |
| Qt tray application (Windows, other Linux) | ✅ written |
| Test suite | ✅ 1,015 Python + 19 JavaScript, green on CI |
| Install verified from a clean checkout | ✅ in CI |
| Daemon verified on real Windows | ✅ on CI's windows-latest runner |
| **Verified on a real Windows desktop** | ❌ **not yet** ([#7](../../issues/7)) |

The extension has been run by [@UHeeJoon](https://github.com/UHeeJoon) on Rocky
Linux 10 with GNOME Shell 47–48, and the defects that turned up there were
fixed in [#1](../../issues/1) and [#3](../../pull/3): rendering stopping because
a destroyed actor was reused, a closed popup re-decoding every sprite every two
seconds, and a sprite decoded as two copies of its first frame. None of those
were visible from a container.

The blank left is the **Windows tray UI**. The daemon reads real logs and writes
a real `state.json` on a windows-latest runner on every push, and the tray
application is constructed and clicked through on the same runner — but nobody
has *looked* at the pet or the tray icon on a Windows screen. If you run
Windows, [#7](../../issues/7) is exactly that.

## Supported tools

All thirteen of the upstream sources are read:

| Tool | Read from |
|---|---|
| **Claude Code** | `~/.claude/projects/**.jsonl` |
| **Codex** | `~/.codex/sessions/**.jsonl` |
| **Gemini CLI** | `~/.gemini/tmp/**` |
| **Antigravity** | `~/.gemini/antigravity*/conversations/*.db` |
| **OpenCode** | `~/.local/share/opencode` |
| **Hermes Agent** | `~/.hermes/state.db` |
| **Cursor** | `~/.config/Cursor/User/globalStorage/state.vscdb` |
| **Grok CLI** | `~/.grok/sessions/**/updates.jsonl` |
| **Copilot CLI** | `~/.copilot/session-store.db` |
| **Kiro CLI** | `~/.local/share/kiro-cli`, `~/.kiro`, `~/.kiro/sessions` |
| **Pi Agent** | `~/.pi/agent/sessions` |
| **omp** (oh-my-pi) | `~/.omp/agent/sessions` |
| **Aside** | `~/.aside/u/*/state.db` |

Official limits are read for Claude accounts, Codex, Antigravity and Cursor.
The Windows branch follows upstream **v2.5.5** while retaining its existing
Windows tray, installer and plan balance. It includes collection search and
appearance selection, bulk candy previews, local save snapshots and calendar
usage recaps. See [the sync record](docs/UPSTREAM_SYNC.md) for coverage and validation.

The Windows/Qt interface also includes persistent individual Pokémon profiles
(level, gender, nature, ability, IVs, calculated stats and moves), a 2× repeat-line
growth bonus, per-provider tabs, a daily chart for the current month, automatic
power-saving animation, refresh after network recovery, version skipping, and
confirmed save imports with five rotating backups and undo.

Most read a dotfile path identical to the one macOS uses. Where a location
genuinely differs, each now has a source behind it rather than a convention.

- **Cursor** was never convention: Electron documents `app.getPath('userData')`
  as the `appData` directory plus the app's name, and `appData` is `%APPDATA%`
  on Windows, `$XDG_CONFIG_HOME` or `~/.config` on Linux, and
  `~/Library/Application Support` on macOS.
- **OpenCode** uses `~/.local/share/opencode` on **all three** platforms
  (`%USERPROFILE%\.local\share\opencode` on Windows). It does not move to the
  platform's data directory — which is where this used to look, so it found
  nothing on two of them.
- **Kiro CLI** is the one still unsettled. Its docs say only `~/.kiro/` while
  another source puts the macOS database under Application Support, so both are
  searched ([#8](../../issues/8)).

A wrong path is indistinguishable from not having used the tool. `(0)` beside a
provider you do use is the symptom; `CURSOR_DATA_DIR`, `KIRO_CLI_HOME`,
`KIRO_HOME` and `OPENCODE_DATA_DIR` override the defaults, and a report of where
your files actually live is welcome.

## How it fits together

```
                         ┌──→  state.json      ──→  GNOME Shell extension
poketokend (Python)  ────┤                          Qt tray app (Windows, other Linux)
                         └←──  command spool    ←──  Plasma widget
```

Plain files, not D-Bus. The daemon knows nothing about the UI, which is what
made a second front end possible at all — and what makes a third one easy.

## Install

### Linux (GNOME)

Requirements: GNOME Shell 45+, Python 3.12+, `libnotify` for notifications
(optional), `python-orjson` for faster parsing (optional).

```bash
git clone https://github.com/HUHGEON/poketokenbar-linux-windows.git
cd poketokenbar-linux-windows
./install.sh
systemctl --user enable --now poketokend
```

Then enable the extension:

```bash
gnome-extensions enable poketokenbar@huhgeon.github.io
```

**The shell has to be restarted before it appears in the list** — `Alt`+`F2`
then `r` on Xorg, log out and back in on Wayland. Enabling it *is* running it;
nothing else needs starting, though the numbers come from the daemon, so
`poketokend` has to be up.

### Linux (other desktops)

On XFCE, Cinnamon or a tiling compositor there is no panel to extend and no
plasmoid, so the same Qt tray application Windows uses is the only thing that
works. `install.sh` picks it when it cannot recognise the desktop.

```bash
POKETOKENBAR_UI=qt ./install.sh
```

### Windows

Requirements: Windows 10+, Python 3.12+.

```powershell
git clone https://github.com/HUHGEON/poketokenbar-linux-windows.git
cd poketokenbar-linux-windows
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
```

With no panel, the Pokemon lives in the notification area. Clicking it opens the
same tabs, and both the daemon and the tray start at login. **Start Menu and
desktop shortcuts** are created too, so starting it by hand does not mean
opening PowerShell. Everything lands inside the user profile and nothing needs
an administrator.

| | Location |
|---|---|
| Config, state, save | `%APPDATA%\poketokenbar\` |
| Cache | `%LOCALAPPDATA%\poketokenbar\` |
| Program | `%LOCALAPPDATA%\PokeTokenBar\` |

`packaging\windows\uninstall.ps1` removes it — deliberately leaving the save.

## Differences from the Plasma port

This started as a fork of the Plasma port and diverged in three ways.

**Ten more providers.** The Plasma port reads Claude Code and Codex; its author
had no data for the rest. The upstream Swift test suite turns out to carry the
schemas and sample records for most of them, so the parsers were ported
alongside their test cases and are verified without owning the tools.

**Three defects fixed in the shared core.** Codex reported zero for the week and
month, because it reimplemented the daily aggregation and never grew the period
one. Token parsing accepted `int` only, so a corrupt `1e30` became 0 and erased
a day rather than clamping. The provider registry built cacheless instances that
nothing used, while the daemon named its two providers by hand.

More came out of the shared core the same way, by reading it against upstream
line by line.

- Flattening an evolution chain took **the first branch every time**. Every
  Eevee was a Vaporeon, and the Pokedex could not be completed.
- A disguised Ditto **graduated as the species it was faking**, leaving a catch
  in the Pokedex that never happened.
- There was no egg sprite. PokeAPI's egg is a 28x30 egg on a 96x96 canvas, so
  uncropped it draws a third the size of everything beside it.
- Natures, item names and hatch notifications lived outside the catalogue, so
  those alone stayed English however the language was set.

**Features the Plasma port left out:** per-provider extra scan folders, the
per-model breakdown of a day, French, Portuguese and German, pinning a caught
species to the panel, animation quality, in-app updates, launch at login, and
the model-scoped weekly limit and rolling 5-hour block.

## Development

```bash
python -m pytest -q       # no network, and none of the thirteen tools installed
node --test tests/js/*.test.mjs   # the tests that execute extension code
```

The tests are the specification. Where a parser rule looks arbitrary, its test
says which upstream case pinned it and what went wrong without it.

[docs/TESTING.md](docs/TESTING.md) records exactly what is checked and what is
not — including the defects the checks have caught, so the claim that they earn
their keep is checkable rather than asserted.

The Qt front-end tests skip themselves when PySide6 is absent. CI's Windows job
installs PySide6 and runs more than 1,000 Python tests, including real widget
construction paths.

## Credits

- [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar) — the
  original macOS app, and the source of every parsing rule here.
- [rubensanchezrivero/poketokenbar-plasma](https://github.com/rubensanchezrivero/poketokenbar-plasma)
  — the Python daemon and the UI-agnostic file protocol this builds on.

## License & disclaimer

**MIT** — see [LICENSE](LICENSE). MIT applies to this project's own source code
only, and grants no rights over third-party trademarks, artwork, or data reached
through the app.

PokeTokenBar for GNOME is an **unofficial, non-commercial fan project**. It is
**not affiliated with, endorsed, sponsored, or approved by Nintendo, Game Freak,
Creatures Inc., or The Pokémon Company.** "Pokémon" and the related names,
characters and images are trademarks and copyrighted works of their respective
owners, and this project claims no ownership of or rights in any Pokémon
intellectual property.

- **No Pokémon assets are included in this repository or in any release.**
  Species data and sprites are fetched at **runtime** from the public
  [PokéAPI](https://pokeapi.co) and cached locally on your own machine; rights in
  the sprite images served through PokéAPI belong to their respective owners.
- This app is provided free of charge for **personal, non-commercial use only**.
- If you hold rights and have concerns about this project, please open an issue
  or contact the maintainer and it will be addressed promptly.

*Provided "as is", without warranty of any kind. This notice is not legal advice.*

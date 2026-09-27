# What is verified, and what is not

The rule this port was built under: nothing gets moved across without being
compared against the source it came from, and without a test that fails when it
is wrong. This is the record of where that holds and where it does not.

## Verified mechanically

**Parsers.** All twelve providers were ported against the upstream Swift suite,
which carries the schemas and sample records. Their tests name the upstream case
they came from, so a rule that looks arbitrary can be traced to what it is for.

**Payload contract.** The extension reads `state.json`. A test enumerates the
keys the daemon actually emits and the keys the extension actually reads, and
fails on the difference — top-level blocks, per-block fields, list rows through
their own loop variable, catalogue keys, settings keys, and command names.

What it has caught so far:

- an invented `companion.celebration_kind`;
- shop rows carrying `label`, not `name`;
- the panel and the popup using different limit-row shapes under one name;
- `floating_pet_x/y` having no daemon default, so `config.load` dropped them and
  the pet would have jumped home on every restart;
- the panel sprite reading the companion's path rather than the pinned one,
  which left pinning with nowhere to take effect at all;
- `burn.forecast_text`, which the daemon never emits — the burn forecast simply
  never appeared. It was in a blind spot: coverage was a hand-written list, so
  a test now fails on any payload-shaped read that is not declared;
- `providerStatus.level`, invented; the rows carry `label` and `severity`, and
  the daemon already drops healthy providers, so the filter written around it
  was wrong as well as unnecessary.

It also had a hole, found by injecting a typo rather than by reading it: string
literals were stripped before scanning, and template literals went with them, so
every `${row.field}` was invisible. Only the literal halves are dropped now.

**JavaScript syntax.** Node parses the same ESM grammar GJS does, so a stray
character fails a push rather than a desktop. Teardown of every timer, signal
and actor is asserted from the source, because a leak here is a leak inside the
compositor.

**The frame-rate cap.** The one piece of sprite handling that is an algorithm
rather than an API call lives in its own gi-free module, so node executes it.
Thirteen tests pin the rule a plausible implementation gets wrong — thin the
frames, never stretch them — because raising each frame to the floor keeps all
55 and turns a 2.75s loop into 22s.

**GObject construction.** A test forbids spreading a caller's option bag into
`super._init`. That is what actually broke the first real install: `new Sprite({
size: 18 })` looked like a local option, but `Clutter.Actor` already has a
`size` property whose type is the boxed `graphene_size_t`, so every sprite threw
at construction and the extension never started. Nothing here can ask GObject
which names are real, so the rule is structural — destructure your own keys out
first.

**GNOME API assumptions.** Checked against the documentation rather than
memory, which found four that were wrong: `PopupSwitchMenuItem` does not lay
out inside an St container, so the settings tab would have been blank;
`Clutter.Content.get_preferred_size` returns `[ok, width, height]` in GJS, so
destructuring two names bound the boolean to the width and every sprite was
sized from it; `St.BoxLayout`'s `vertical` is deprecated from 48 while its
replacement is undocumented in 45, so the property the running Shell has is
used; and the pet sat in `_backgroundGroup`, which is private, renders nothing
on a secondary monitor, and is below windows where upstream's floats above
them.

**Install.** CI installs from a clean checkout, starts the daemon, and fails
unless a state file lands.

**Windows, on Windows.** A CI job on windows-latest runs the whole suite, checks
every file the daemon owns lands under the user profile, seeds real log files
and asserts the totals off a real `state.json`, and constructs the Qt tray app.
`platform_paths` injects the system so all three mappings can be checked from
anywhere — but the one thing an injected mapping cannot tell you is whether the
environment actually looks the way it was assumed to, and that job found two
bugs no amount of injection would have:

- `expand` tested for an absolute path with `startswith("/")` and split segments
  on the same character, so every `C:\` path was read as relative and dropped.
  Extra scan folders silently did nothing on Windows.
- `fold` and the eviction guard are string prefix checks written against "/",
  and a Windows path resolves with backslashes — so nested roots would have
  doubled the scan, and the guard that stops an extra folder swallowing a
  curated default would never have fired at all.

Confirmed on the runner:

```
config   C:\Users\runneradmin\AppData\Roaming\poketokenbar\config.json
cache    C:\Users\runneradmin\AppData\Local\poketokenbar
spool    C:\Users\RUNNER~1\AppData\Local\Temp\poketokenbar\commands  (writable)
providers: {'claude_code': 1250, 'gemini': 600}
tabs     : ['Home', 'Shop', 'Bag', 'Collection', 'Settings']
```

**Settings coverage.** A test fails if any of the daemon's settings has no
control in the UI. It found thirteen of seventeen unreachable.

**Environment independence.** Every path override is cleared before each test.
CI found this: the Cursor tests passed locally and failed on a runner, because a
provider given an explicit `home=` still reads the ambient XDG base. The suite
had been quietly reporting on whoever's machine it ran on.

**Front-end parity.** The two front ends are audited against each other — which
state.json blocks each reads, which commands each sends, which settings each
exposes. That found the Qt one offering three settings for a desktop pet it did
not have, which is worse than a missing feature: the switch flipped and nothing
happened. They are level now, and both agree with the daemon on what the three
animation presets mean.

## Verified by hand

Nothing above proves an actor appears, that a GNOME API exists, or that a popup
is laid out sensibly. That needs a desktop and a person, and both front ends
have now had one.

**The GNOME extension**, on Rocky Linux 10 with GNOME Shell 47–48. What that
found — rendering stopping on a reused destroyed actor, a closed popup
re-decoding every sprite every two seconds, a sprite decoded as two copies of
its first frame — is the measure of what the mechanical checks cannot see.

**The Windows tray UI**, on Windows 10: the pet survives a click, the tray icon
animates, and all four popup tabs render. This one mattered because two of the
fixes behind it — the pet's window flags and the animated tray icon — were made
by removing their cause rather than by reproducing the symptom. macOS was tried
as a stand-in for the first and does not reproduce it; the unfixed version
survives there too. So the CI run said the fix broke nothing, and nothing about
whether it worked. That gap is closed by someone having looked, not by a test.

## Not verified

**Another desktop, another shell version.** The two runs above are two machines.
A GNOME 45 session, a tiling compositor falling back to the tray app, and
Windows 11 are all still unseen.

**One provider path.** Kiro's SQLite store is the only location left without a
source: its documentation says `~/.kiro/` while another source puts the macOS
database under Application Support, so both are searched. Cursor's follows
Electron's documented `app.getPath('userData')`, and OpenCode's is stated
per-platform by its own troubleshooting page. `KIRO_CLI_HOME`, `KIRO_HOME`,
`CURSOR_DATA_DIR` and `OPENCODE_DATA_DIR` override all of them.

**Cursor's dashboard API.** Not ported. The local store is the fallback that
path already uses, so usage reads offline; usage that never touched this machine
will be missing.

**The claude.ai session key.** Deliberately skipped. It exists to avoid macOS
Keychain prompts, and Linux reads `~/.claude/.credentials.json` directly, so the
problem it solves is absent here. Upstream also records that the endpoint
rejects anything that does not look like a browser, which would have meant
shipping a network path that could not be verified from this machine.

## Running them

```bash
python -m pytest -q               # node must be on PATH, or the JS checks skip
node --test tests/js/*.test.mjs   # the checks that execute extension code
```

The Qt front-end tests skip themselves when PySide6 is absent, so the count
depends on the environment: CI's ubuntu job runs 932 and the Windows job, which
installs PySide6, runs all 990.

CI fails if those checks skip: a skip and a pass look identical in the summary,
and they are the only thing covering the extension.

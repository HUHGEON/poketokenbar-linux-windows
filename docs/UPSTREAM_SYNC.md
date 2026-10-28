# macOS upstream synchronization — 2026-10-24

Compared the current port (`81ac9fb`) with
[PokeTokenBar v2.5.6 + d82867b](https://github.com/chattymin/PokeTokenBar/tree/d82867bb0659604c3737a74b36bc9dcac7db1ac5).
The previous synchronization baseline was v2.5.5 (`42df4e6`). Source comparison
covers the intervening commits, including the two fixes after the v2.5.6 tag.

## Incorporated in the shared Python core

- Kimi Code as the 14th usage provider: `wire.jsonl` only, main/subagent requests,
  turn/session scopes, fork deduplication, token clamping, additive
  `KIMI_CODE_HOME` and custom scan folders. Costs remain unavailable. The
  macOS desktop runtime path is recognized on macOS; unknown Linux/Windows
  desktop runtime locations can be supplied as custom folders.
- All 23 form-bearing species in upstream's Gen I–V catalogue, including
  Unown: weighted form rolls, evolution inheritance, appearance-specific
  collection/pinning, static variety IDs, localized alternate form names with
  offline fallback, and save/export/snapshot retention. Default-form battle
  data remains authoritative. Existing `unown_form` fields are compatibility
  aliases; saves also emit the generalized `form` fields.
- GPT-6 Sol/Luna, Claude Sonnet 5.5, and the >272K input tier for the new GPT
  rows (including GPT-6.1 Sol). These are API-equivalent estimates.
- Kiro tool-use, tool-result, thinking and JSON payload estimates; excluded
  image/redacted/signature metadata stays excluded. Parser cache is invalidated.
- Candy reset epochs tolerate fractional-second and backward jitter: session
  epochs must advance 30 minutes, weekly epochs 24 hours. The anchor is not
  moved by jitter; a genuine below-full crossing still rearms the grant.
- Bulk consumable purchases (1–99) debit atomically; eggs and charms stay
  single purchases. CLI accepts `buy/use <key> [count]`.
- Rounding-boundary unit promotion, rounded cost/percent precision, Shedinja
  HP=1, Ditto repeat-boost selection, duplicate saved evolution-chain repair,
  ordered warning/critical thresholds, recent provider tabs on idle days, and
  failed update checks that do not consume the success cooldown.
- Eight UI languages including Russian, with placeholder checks across the
  complete port catalogue. Pokémon metadata falls back to English when a
  localized name is unavailable.

## Frontend coverage

GNOME collection now supports search, rarity/shiny filters, sorting, 4×4 pages,
wheel paging, appearance details and representative selection, and paginated
catch logs with detail links. Search actors survive periodic rebuilds. Shop and
bag controls support quantity selection; candy previews and valuable-companion
release confirmation are connected to the existing daemon commands.

The Qt frontend uses its existing collection and recap screens, with alternate
forms, bulk purchase quantities, exact growth/chart tooltips, full-calendar
monthly charts stacked by provider, a current-period recap shortcut, and
collapsed local backup history.

The frontend implementations are not identical: GNOME still has no dedicated
recap/chart or local-snapshot management screen, and its detail view is simpler
than Qt/macOS. Qt now supports sprite-click navigation from Home, reached evolution stages,
and catch-log surfaces (see the 2026-10-27 follow-up).
These pre-existing frontend gaps are not described as completed parity.

AppKit/SwiftUI settings-window lifecycle, universal macOS binaries, Keychain
interaction and macOS menu-bar sizing are platform-specific and are not copied
into this port. Existing sprite downloads already retry failures rather than
caching a failed decode permanently. Existing Cursor pagination already falls
back to page length when total counts are absent; Antigravity already skips
buckets with no `remainingFraction` and refreshes file-based OAuth credentials.

## Validation

Regression tests cover Kimi fork/subagent/compaction usage, form evolution and
save/pin round trips, localized form-name caching, reset jitter, bulk purchase
atomicity, pricing tiers, rounded display boundaries, Kiro payloads, Shedinja,
malformed chains, idle provider history, update retries and Russian placeholders.

The local environment has no GNOME Shell session or PySide6. JavaScript parsing
and the 19 Node behavior tests run using the installed Windows Node executable;
Python GUI tests are skipped when PySide6 is absent. No live credentials or
personal usage logs are used. Native desktop behavior remains a manual check.
Final verification on 2026-10-24:

- **1,211 Python tests passed, 12 skipped** (complete suite, 291.63 seconds).
- **19 JavaScript behavior tests passed**, plus all extension JavaScript parse
  checks in the Python suite.
- `python3 -m compileall -q poketokenbar tools` and `git diff --check` passed.

The complete Python run used `QT_QPA_PLATFORM=offscreen`, a project-local
`TMPDIR`/`--basetemp`, and `-s` to work around the full system `/tmp` and mounted
filesystem capture behavior. The two unchanged-file cache tests normalize their
initial file timestamps before caching, then restore nanosecond timestamps;
this preserves the intended cache-hit assertion on mounted filesystems.


## Pokémon type badges

The Home companion card and Pokédex details now render type badges through a
shared type catalogue. All 18 standard type colors match upstream's
`UI/Badge.swift`; dual types preserve PokéAPI slot order. Type-name translation
is **Korean only** for this update, with canonical English fallback for the
other existing UI languages. Cached species data supplies reference entries
without an individual profile; displaying badges adds no network calls.
The GNOME Home/detail views consume the same localized badge metadata.

Native Windows Qt checks rendered the current Sawk's **격투** badge in
`#BB5544`, checked the **풀 / 독** dual-type reference view, and verified
compatibility with older profile-only state files. Source and save backups
were taken before restarting the locally installed tray and daemon.

## Local Windows deployment follow-up

The installed Windows Python 3.13.7 / Qt 6.11.2 environment passed a native
preflight that constructed every tab, settings and recap, and rendered the
stacked monthly chart. This checks native Qt construction without claiming
visual inspection of the desktop.

During local restart verification, stack samples identified repeated Windows
`realpath` calls while scanning Codex rollouts through an added WSL/UNC root.
Codex now uses filesystem device/inode identity to avoid those calls and to
collapse file symlink/hardlink aliases; filesystems without an inode use a
normalized lexical path. Parser cache paths and usage ownership rules remain
unchanged. Targeted regressions: **72 passed, 6 skipped on Linux** and **all
3 new file-identity regressions passed on native Windows**.

The installed package is copied from the local working tree, with SHA-256
verification of all 70 Python files and separate code/progress backups under
`%LOCALAPPDATA%\PokeTokenBar\backups`. Settings and progress remain in their
existing Roaming application-data directory.

---

# Previous Windows synchronization

This work starts from `origin/Windows` commit
`ade3ce08a7c778cc5f00ef26de90866d9816cedd` and follows
[PokeTokenBar v2.5.5, main at 42df4e6](https://github.com/chattymin/PokeTokenBar/tree/42df4e61590fd049b299ec21c349f6d84f93a96a),
the upstream head checked on 2026-10-04. The local GNOME working copy is not an input.

## Preserved Windows behavior

The Python daemon, PySide6 tray/popover, Windows storage paths, PowerShell
installer, automatic startup, single-instance locks, background helper windows,
and Windows update branch remain in place. The existing detected Codex plan
balance, independent growth/shop difficulty, shiny odds, and saved progress
units remain authoritative. GPT-6.1 Sol pricing already present on Windows is
retained. Swift/AppKit and macOS Keychain code are replaced by the existing
Windows application mechanisms, not copied into the port.

## Upstream behavior incorporated

| Area | Windows implementation |
| --- | --- |
| Usage sources | Aside; OpenCode v2 messages; canonical Codex fork/subagent and total-only fixtures; Claude reported cost and original-account ownership; Cursor dashboard fallback; Kiro history retention; Pi/omp model attribution; malformed token clamping |
| Costs | Current explicit model rows and request-level tiers; reported, estimated, partially known and unavailable coverage; plain dollar values with explanations |
| Official limits | Independent Claude accounts and session keys, organization selection and OAuth fallback; existing Codex app-server limits; Cursor allowance; Antigravity CLI/IDE token discovery and refresh |
| Quota presentation | Six pace tiers, elapsed-time markers, used/remaining fills, local reset times; stable per-account/provider candy windows rearmed by reset epochs |
| Collection | Search by name/number, rarity/shiny filters, sorting, sixteen-cell 4×4 pages; paginated catch log; separate normal/shiny and all 28 Unown appearances; selected-appearance profiles |
| Growth/shop | Bulk candy quantities and exact growth/evolution/graduation/carryover previews; protection for shiny/legendary release; released reached forms remain collected; retryable delayed hatches |
| Saves | Ten local snapshots at most, automatic snapshots every twelve hours, manual backup/restore, corruption recovery and quarantine; pre-restore backup and existing import undo retained |
| Recap | Local high-water usage ledger; calendar weeks/months/years; equal-elapsed-period comparisons; unknown days separated from zero; active days, streaks and graduates |
| Windows UI | New features connected to the existing 400×640 popover; persistent search input for IME composition; recap and pet footer controls; manual or 1–15 minute refresh; dynamic shiny-odds copy and Korean particles |

Session keys are stored separately from configuration and never appear in
`state.json`. Tests redirect all storage and credential-related environment
overrides to scratch data. Official API tests use synthetic credentials and
fixture responses.

## Validation

Run the complete Python suite, including Qt construction/layout checks:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q
node --test tests/js/*.test.mjs
python -m compileall -q poketokenbar tools
git diff --check
```

Final local verification on 2026-10-04: **1,245 Python tests passed, ten skipped;
two JavaScript tests passed**. Python compilation and `git diff --check` passed.
The collection, recap and settings pages were rendered offscreen at 400×640.

The initial Windows branch baseline was 1,120 passing tests, ten skips and one
stale settings-reachability assertion for `skipped_update_revision`. That
assertion has been corrected to account for the existing Skip/Show controls.

The workflow now triggers on `Windows` pushes as well as the existing branches.
Its native Windows job covers PowerShell install/uninstall, generated launchers,
Windows paths and tray construction. Local verification here uses Linux Qt in
offscreen mode; it does not establish real Windows tray, toast, taskbar, DPI,
installer execution, or live account API behavior. No personal logs or accounts
are used for validation.


## Pokémon detail follow-up — 2026-10-27

The Qt Pokédex now includes the complete Black 2 / White 2 learnset with learn
methods, possible abilities, height, weight, base-stat total, computed-stat
bars, and reference-stage base stats. A per-species daemon command fetches and
localizes details on entry; failures remain retryable. Legacy Black / White
caches are refreshed without deleting offline fallback data. Failed metadata
requests back off for five minutes; explicit detail retries reset that delay.
Existing individual identity, IVs, level and growth credits are retained.

Home, evolution-line, catch-log and grid sprites open collected entries. Grid
wheel paging is debounced, detail scrolling remains ordinary scrolling, and
Back restores the list position. Alternate-form default-data notes are visible.
The GNOME detail view also consumes the new species metadata and displays both
known and complete moves. New labels are Korean with English fallback.

Native Windows UI regressions cover the new sections, reference-only stages,
request/retry routing, Home links, wheel paging, and the existing 400px layout.
Production Qt before/after renders with synthetic sample data are retained in
`.test-deps/feature-audit/`. This does not claim GNOME desktop rendering parity
or implementation of macOS-specific pet context menus/speech balloons.

Validation for this follow-up: **1,230 passed, 13 skipped** in the complete
Python suite; **87 passed** in native Windows Qt UI tests; **66 passed** in
focused detail/profile/extension-contract regressions after the final retry
change. Live PokéAPI validation returned all **61 Rattata moves in Korean**,
including level-up, machine, egg and tutor methods. Compilation, native UI
preflight and `git diff --check` passed.

Local deployment completed with SHA-256 verification of all 71 Python files.
Code and progress backups are under
`%LOCALAPPDATA%\PokeTokenBar\backups\local-update-20261027-051624`.
Both tray and daemon locks were live, a fresh state was published, and the new
logs contained no traceback. An actual queued detail request produced Rattata's
61 Korean moves with `black-2-white-2` metadata; the installed Qt detail UI
rendered the complete-list heading and possible-abilities section successfully.


## Final Windows parity review — 2026-10-28

Rechecked upstream main `32ebe4c` and v2.5.6; the upstream head is unchanged.
Added the remaining Windows equivalents: pet Open/Hide context menu, transient
limit-event speech bubbles, tray summary and Pokédex/Settings/pet shortcuts,
and a labeled Home recap button. Limit bubbles use the notifier's actual edge
notifications, expire, honor the notification preference, and keep the pet's
persisted coordinates/size independent of the bubble.

Ported the additional shared-core fixes after `d82867b`: Claude's growing logs
use a persisted byte offset and raw-entry/cumulative-ledger separation, with
partial-line retries and full rereads after truncation or rewrite. Cursor usage
and quota requests share refreshed credentials in memory, preserve rotated
refresh tokens, reject changed logins/roots, and never write Cursor's SQLite
login. Explicit environment tokens cannot borrow a local refresh token.

Corrected deferred scroll restoration so Back restores the actual list offset,
and detail metadata is re-requested after a UI language change. New labels are
Korean with English fallback, following the requested localization scope.
The Korean feature audit now describes the final implementation instead of
leaving the pre-update missing-feature table as the apparent current state.

Final checks: **1,242 Python tests passed, 14 skipped**, **92 native Windows Qt
tests passed**, and **19 JavaScript behavior tests passed**. After the final
transient-file-lock cache fix, **102 focused core regressions passed**.
Compilation and `git diff --check` also passed.

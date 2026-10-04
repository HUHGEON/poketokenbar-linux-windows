# Windows upstream synchronization

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

# Windows upstream 2.5.5 synchronization

> **For agentic workers:** Apply superpowers:dispatching-parallel-agents for independent core domains; integrate and verify in the Windows worktree.

**Goal:** Update origin/Windows (ade3ce0) to the applicable behavior of chattymin/PokeTokenBar main (42df4e61590fd049b299ec21c349f6d84f93a96a, v2.5.5).
**Architecture:** Preserve Windows PySide6 UI, paths, installers, updater, single-instance protection, plan-scaled growth/shop balance, and difficulty. Port upstream behavior into the existing Python core and Qt front end. No files or preferences from the dirty GNOME checkout are inputs.
**Tech stack:** Python 3.12, PySide6, pytest, PowerShell installer.
**Spec:** User request plus the pinned upstream source/tests and existing Windows implementation.

## Constraints and review focus
- Keep current saves, profile data, detected-plan scaling and progress valid.
- Preserve Windows process and path conventions; no macOS Keychain dependencies.
- Tests use scratch data and mocked network/credentials, never personal accounts.
- Handle malformed provider records, model-price gaps, duplicate sessions and cache migration.
- All new features need a usable Windows entry point, not just an unused backend.

## Tasks
- [x] Baseline: clean origin/Windows worktree, full pytest run; pin upstream revision.
- [x] Usage providers: add Aside; port parser/account ownership/cost and pricing fixes; test fixtures first. Owned files: providers/, models.py, pricing.py, cache.py and their tests.
- [x] Official limits: Claude account/session-key support, Antigravity and Cursor sources, pace tiers and reset behavior; fixture tests first. Owned files: limits.py, limits_source.py, new limits/accounts/pace modules and their tests.
- [x] Collection/save/gameplay: Unown appearances, bulk candy preview, precious-companion protection, delayed hatches, snapshots/recovery; preserve Windows balance. Owned files: companion.py, companion_store.py, save.py, transfer.py, shop.py, sprites.py, pokeapi.py, profile.py, new related modules and tests.
- [x] Integration/Qt: connect sources/settings/commands/state; collection search/filter/sort and 4x4 grid; snapshots, bulk candy, official limits; recap ledger and calendar-period recap; localization and notifications. Owned files: daemon.py, config.py, commands.py, state.py, notify.py, l10n.py, ui/, recap/ledger modules and tests.
- [x] Validation: full pytest including offscreen Qt, JS suite, compile checks and Windows smoke tools where supported. Review the final diff independently; document native-Windows checks that cannot run here.

## Verification result

2026-10-04: 1,245 Python tests passed, ten skipped; two JavaScript tests passed.
Compileall and whitespace checks passed. Qt collection, recap and settings
were rendered offscreen at 400×640. Independent review findings for Cursor
month boundaries, active companions in recaps, Unown shorthand selection,
initial quota errors and unsupported sort choices were resolved and covered
by the final run. Native Windows execution and live account APIs were not run.
The original GNOME working-tree status is unchanged.

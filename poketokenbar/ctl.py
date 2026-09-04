"""poketokenctl — the plasmoid's only way to talk to the daemon."""

from __future__ import annotations

import sys

from . import commands, config


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: poketokenctl {set <key> <value>|scan-roots <provider> <paths>|"
              "represent <species-id|none>|refresh|buy <key>|use <key>|"
              "export <path>|import <path>|restore}",
              file=sys.stderr)
        return 2

    action, rest = argv[0], argv[1:]
    if action == "set":
        if len(rest) != 2:
            print("usage: poketokenctl set <key> <value>", file=sys.stderr)
            return 2
        try:
            config.set_value(config.default_path(), rest[0], rest[1])
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        commands.enqueue("reload_config", {})
        return 0

    if action == "scan-roots":
        if len(rest) != 2:
            print("usage: poketokenctl scan-roots <provider> <comma-separated paths>",
                  file=sys.stderr)
            return 2
        try:
            config.set_scan_roots(config.default_path(), rest[0], rest[1])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        commands.enqueue("reload_config", {})
        return 0

    if action == "represent":
        if len(rest) != 1:
            print("usage: poketokenctl represent <species-id|none>", file=sys.stderr)
            return 2
        commands.enqueue("represent", {"species_id": rest[0]})
        return 0

    if action == "refresh":
        commands.enqueue("refresh", {})
        return 0

    if action in ("export", "import"):
        if len(rest) != 1:
            print(f"usage: poketokenctl {action} <path>", file=sys.stderr)
            return 2
        from pathlib import Path

        commands.enqueue(action, {"path": str(Path(rest[0]).expanduser().resolve())})
        return 0

    if action == "restore":
        # The way back from an import that replaced the wrong save. The daemon
        # owns the backups, so this only asks; it does not touch the file.
        if rest:
            print("usage: poketokenctl restore", file=sys.stderr)
            return 2
        commands.enqueue("restore", {})
        return 0

    if action in ("buy", "use"):
        if len(rest) != 1:
            print(f"usage: poketokenctl {action} <key>", file=sys.stderr)
            return 2
        commands.enqueue(action, {"key": rest[0]})
        return 0

    print(f"unknown command: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

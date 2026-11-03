#!/usr/bin/env python3
"""Merge the mdindex hooks into ~/.claude/settings.json (idempotent, with backup)."""
from __future__ import annotations

import copy
import datetime
import difflib
import json
import shutil
import sys
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"

# event -> (matcher or None, hook subcommand)
HOOKS = [
    ("PostToolUse", "Write|Edit", "post-tool-use"),
    ("Stop", None, "stop"),
    ("SessionStart", None, "session-start"),
]


def merge_hooks(settings: dict, command_prefix: str) -> dict:
    out = copy.deepcopy(settings)
    hooks = out.setdefault("hooks", {})
    for event, matcher, sub in HOOKS:
        groups = hooks.setdefault(event, [])
        present = any(h.get("command", "").startswith(f"{command_prefix} hook ")
                      for g in groups for h in g.get("hooks", []))
        if present:
            continue
        group = {"hooks": [{"type": "command", "command": f"{command_prefix} hook {sub}"}]}
        if matcher:
            group = {"matcher": matcher, **group}
        groups.append(group)
    return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    current = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    merged = merge_hooks(current, "mdindex")
    before = json.dumps(current, indent=2).splitlines()
    after = json.dumps(merged, indent=2).splitlines()
    if before == after:
        print("hooks already installed; no change")
        return 0
    print("\n".join(difflib.unified_diff(before, after, str(SETTINGS), str(SETTINGS) + " (new)", lineterm="")))
    if dry:
        return 0
    if SETTINGS.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SETTINGS.with_name(f"settings.json.bak-{stamp}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup: {backup}")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_name("settings.json.tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    tmp.replace(SETTINGS)
    print(f"updated {SETTINGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

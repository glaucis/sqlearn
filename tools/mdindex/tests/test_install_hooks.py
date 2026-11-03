import copy
import sys
import unittest

from helpers import HERE

sys.path.insert(0, str(HERE.parent.parent))  # tools/

import install_hooks  # noqa: E402

EXISTING = {
    "attribution": {"commit": "", "pr": "", "sessionUrl": False},
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "codegraph prompt-hook"}]}
        ]
    },
}


def commands(settings, event):
    return [h["command"] for g in settings.get("hooks", {}).get(event, []) for h in g["hooks"]]


class MergeHooksTests(unittest.TestCase):
    def test_merge_adds_three_hooks(self):
        out = install_hooks.merge_hooks({}, "mdindex")
        self.assertEqual(commands(out, "PostToolUse"), ["mdindex hook post-tool-use"])
        self.assertEqual(commands(out, "Stop"), ["mdindex hook stop"])
        self.assertEqual(commands(out, "SessionStart"), ["mdindex hook session-start"])
        self.assertEqual(out["hooks"]["PostToolUse"][0]["matcher"], "Write|Edit")

    def test_merge_is_idempotent(self):
        once = install_hooks.merge_hooks(copy.deepcopy(EXISTING), "mdindex")
        twice = install_hooks.merge_hooks(copy.deepcopy(once), "mdindex")
        self.assertEqual(once, twice)

    def test_merge_keeps_existing_hooks(self):
        out = install_hooks.merge_hooks(copy.deepcopy(EXISTING), "mdindex")
        self.assertEqual(commands(out, "UserPromptSubmit"), ["codegraph prompt-hook"])
        self.assertEqual(out["attribution"], EXISTING["attribution"])

    def test_merge_does_not_mutate_input(self):
        src = copy.deepcopy(EXISTING)
        install_hooks.merge_hooks(src, "mdindex")
        self.assertEqual(src, EXISTING)


if __name__ == "__main__":
    unittest.main()

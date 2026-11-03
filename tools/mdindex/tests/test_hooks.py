import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import HERE, TempProject

import mdindex

SCRIPT = HERE.parent / "mdindex.py"


def hook_input(cwd, path=None, tool="Write"):
    d = {"cwd": str(cwd), "hook_event_name": "PostToolUse", "tool_name": tool}
    if path is not None:
        d["tool_input"] = {"file_path": str(path)}
    return json.dumps(d)


class HookTests(TempProject):
    def pending(self):
        p = self.root / ".mdindex/pending"
        return p.read_text().splitlines() if p.exists() else []

    def test_post_tool_use_queues_md(self):
        p = self.write("docs/a.md", "a")
        self.assertEqual(mdindex.cmd_hook("post-tool-use", hook_input(self.root, p)), 0)
        self.assertEqual(self.pending(), ["docs/a.md"])

    def test_post_tool_use_relative_path_uses_cwd(self):
        self.write("docs/b.md", "b")
        mdindex.cmd_hook("post-tool-use", hook_input(self.root, "docs/b.md"))
        self.assertEqual(self.pending(), ["docs/b.md"])

    def test_post_tool_use_ignores_non_md(self):
        p = self.write("src/a.py", "x")
        mdindex.cmd_hook("post-tool-use", hook_input(self.root, p))
        self.assertEqual(self.pending(), [])

    def test_post_tool_use_ignores_excluded(self):
        p = self.write("node_modules/pkg/README.md", "x")
        mdindex.cmd_hook("post-tool-use", hook_input(self.root, p))
        self.assertEqual(self.pending(), [])

    def test_post_tool_use_ignores_project_without_mdindex(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.md"
            p.write_text("a")
            self.assertEqual(mdindex.cmd_hook("post-tool-use", hook_input(d, p)), 0)
            self.assertFalse((Path(d) / ".mdindex").exists())

    def test_hook_bad_json_returns_zero(self):
        self.assertEqual(mdindex.cmd_hook("post-tool-use", "not json"), 0)
        self.assertEqual(mdindex.cmd_hook("post-tool-use", json.dumps({"cwd": str(self.root)})), 0)
        self.assertEqual(mdindex.cmd_hook("bogus-event", "{}"), 0)

    def test_stop_spawns_sync_when_pending(self):
        (self.root / ".mdindex/pending").write_text("a.md\n")
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(mdindex.cmd_hook("stop", json.dumps({"cwd": str(self.root)})), 0)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-3:], ["sync", "--pending", str(self.root)])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_stop_noop_when_nothing_pending(self):
        with mock.patch("subprocess.Popen") as popen:
            mdindex.cmd_hook("stop", json.dumps({"cwd": str(self.root)}))
        popen.assert_not_called()

    def test_session_start_spawns_full_sync(self):
        with mock.patch("subprocess.Popen") as popen:
            mdindex.cmd_hook("session-start", json.dumps({"cwd": str(self.root / "sub")}))
        self.assertEqual(popen.call_args.args[0][-2:], ["sync", str(self.root)])

    def test_session_start_noop_without_mdindex(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.Popen") as popen:
            mdindex.cmd_hook("session-start", json.dumps({"cwd": d}))
        popen.assert_not_called()

    def test_main_hook_reads_stdin(self):
        p = self.write("c.md", "c")
        with mock.patch("sys.stdin") as stdin:
            stdin.read.return_value = hook_input(self.root, p)
            self.assertEqual(mdindex.main(["hook", "post-tool-use"]), 0)
        self.assertEqual(self.pending(), ["c.md"])

    def test_hook_fast_path_under_50ms(self):
        def run(args, data):
            t = time.perf_counter()
            r = subprocess.run(args, input=data, capture_output=True, text=True)
            return time.perf_counter() - t, r

        with tempfile.TemporaryDirectory() as d:
            data = hook_input(d, Path(d) / "a.md")
            base = min(run([sys.executable, "-c", "pass"], "")[0] for _ in range(3))
            best, r = None, None
            for _ in range(3):
                el, r = run([sys.executable, str(SCRIPT), "hook", "post-tool-use"], data)
                best = el if best is None else min(best, el)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout + r.stderr, "")
            self.assertLess(best - base, 0.050)


if __name__ == "__main__":
    unittest.main()

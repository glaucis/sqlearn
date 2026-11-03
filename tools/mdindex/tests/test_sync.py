import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from helpers import FIXTURES

import mdindex


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "My Project"
        self.root.mkdir()
        self.log = self.root.parent / "qmd.log"
        env = mock.patch.dict(os.environ, {
            "MDINDEX_FAKE_RESPONSE": str(FIXTURES / "response_ok.json"),
            "MDINDEX_QMD": str(FIXTURES / "fake_qmd.sh"),
            "FAKE_QMD_LOG": str(self.log),
        })
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def qmd_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()

    def test_init_creates_config_and_registers_collection(self):
        self.write("docs/a.md", "a\n")
        rc, _ = self.quiet(mdindex.cmd_init, self.root)
        self.assertEqual(rc, 0)
        cfg = json.loads((self.root / ".mdindex/config.json").read_text())
        self.assertEqual(cfg["collection"], "my-project")
        add = [c for c in self.qmd_calls() if c.startswith("collection add")]
        self.assertEqual(len(add), 1)
        self.assertIn(str(self.root), add[0])
        self.assertIn("--name my-project", add[0])
        self.assertIn("--mask **/*.md", add[0])
        self.assertEqual(mdindex.read_doc((self.root / "docs/a.md").read_text()).fields["type"], "adr")

    def test_init_twice_is_noop(self):
        self.quiet(mdindex.cmd_init, self.root)
        n = len(self.qmd_calls())
        rc, out = self.quiet(mdindex.cmd_init, self.root)
        self.assertEqual(rc, 0)
        self.assertIn("already initialised", out)
        self.assertEqual(len(self.qmd_calls()), n)

    def test_sync_tags_then_indexes(self):
        self.quiet(mdindex.cmd_init, self.root)
        self.log.unlink()
        self.write("b.md", "b\n")
        rc, _ = self.quiet(mdindex.cmd_sync, self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(self.qmd_calls(), ["update", "embed"])
        self.assertIn("b.md", mdindex.load_state(self.root)["files"])

    def test_sync_pending_only(self):
        self.quiet(mdindex.cmd_init, self.root)
        self.write("x.md", "x\n")
        self.write("y.md", "y\n")
        (self.root / ".mdindex/pending").write_text("x.md\n")
        self.quiet(mdindex.cmd_sync, self.root, pending_only=True)
        files = mdindex.load_state(self.root)["files"]
        self.assertIn("x.md", files)
        self.assertNotIn("y.md", files)
        self.assertEqual((self.root / ".mdindex/pending").read_text(), "")

    def test_sync_survives_api_error(self):
        self.quiet(mdindex.cmd_init, self.root)
        p = self.write("e.md", "e\n")
        with mock.patch.object(mdindex, "request_tags", side_effect=mdindex.MdindexError("boom")):
            rc, _ = self.quiet(mdindex.cmd_sync, self.root)
        self.assertEqual(rc, 0)
        log = (self.root / ".mdindex/log").read_text().splitlines()
        self.assertEqual(len(log), 1)
        self.assertIn("e.md", log[0])
        self.assertIn("boom", log[0])
        self.assertNotIn("type:", p.read_text())
        self.quiet(mdindex.cmd_sync, self.root)
        self.assertIn("type: adr", p.read_text())

    def test_sync_survives_qmd_missing(self):
        self.quiet(mdindex.cmd_init, self.root)
        with mock.patch.dict(os.environ, {"MDINDEX_QMD": str(self.root / "no-such-qmd")}):
            rc, _ = self.quiet(mdindex.cmd_sync, self.root)
        self.assertEqual(rc, 0)
        self.assertIn("qmd", (self.root / ".mdindex/log").read_text())

    def test_second_sync_exits_when_locked(self):
        self.quiet(mdindex.cmd_init, self.root)
        self.assertTrue(mdindex.acquire_lock(self.root))
        self.log.unlink()
        self.write("z.md", "z\n")
        rc, _ = self.quiet(mdindex.cmd_sync, self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(self.qmd_calls(), [])
        self.assertNotIn("z.md", mdindex.load_state(self.root)["files"])
        mdindex.release_lock(self.root)
        self.assertFalse((self.root / ".mdindex/lock").exists())

    def test_stale_lock_taken_over(self):
        self.quiet(mdindex.cmd_init, self.root)
        lock = self.root / ".mdindex/lock"
        lock.write_text("99999")
        old = time.time() - 11 * 60
        os.utime(lock, (old, old))
        self.assertTrue(mdindex.acquire_lock(self.root))
        mdindex.release_lock(self.root)

    def test_status_counts(self):
        self.write("a.md", "a\n")
        self.quiet(mdindex.cmd_init, self.root)
        self.write("a.md", mdindex.render_doc(mdindex.read_doc((self.root / "a.md").read_text())) + "more\n")
        self.write("new.md", "n\n")
        self.write("s.md", "sk-ant-zzz\n")
        self.quiet(mdindex.cmd_sync, self.root, pending_only=True)  # nothing pending: no tagging
        state = mdindex.load_state(self.root)
        mdindex.tag_file(self.root, self.root / "s.md", mdindex.load_config(self.root), state)
        mdindex.save_state(self.root, state)
        rc, out = self.quiet(mdindex.cmd_status, self.root)
        self.assertEqual(rc, 0)
        lines = dict(l.split(": ", 1) for l in out.strip().splitlines())
        self.assertEqual(lines["collection"], "my-project")
        self.assertEqual(lines["docs"], "3")
        self.assertEqual(lines["tagged"], "0")
        self.assertEqual(lines["changed"], "1")
        self.assertEqual(lines["untagged"], "1")
        self.assertEqual(lines["skipped"], "1")

    def test_main_dispatches_status(self):
        self.quiet(mdindex.cmd_init, self.root)
        rc, out = self.quiet(mdindex.main, ["status", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertIn("collection: my-project", out)

    def test_main_errors_outside_project(self):
        other = self.root.parent / "other"
        other.mkdir()
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mdindex.main(["status", str(other)])
        self.assertEqual(rc, 1)
        self.assertIn("mdindex init", err.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the final-review findings (C1, I1-I8)."""
import io
import json
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest import mock

from helpers import FIXTURES, TempProject

import mdindex

OK = str(FIXTURES / "response_ok.json")
BUG = str(FIXTURES / "response_bug.json")


class Base(TempProject):
    def setUp(self):
        super().setUp()
        self.cfg = dict(mdindex.DEFAULT_CONFIG, collection="t")
        self.state = {"files": {}}
        self.log = self.root / "qmd.log"
        env = mock.patch.dict(os.environ, {
            "MDINDEX_FAKE_RESPONSE": OK,
            "MDINDEX_QMD": str(FIXTURES / "fake_qmd.sh"),
            "FAKE_QMD_LOG": str(self.log),
        })
        env.start()
        self.addCleanup(env.stop)

    def tag(self, p):
        return mdindex.tag_file(self.root, p, self.cfg, self.state)

    def rels(self, cfg=None):
        return [p.relative_to(self.root).as_posix() for p in mdindex.iter_docs(self.root, cfg or self.cfg)]


class BlockValueTests(Base):  # C1
    def test_block_style_user_values_untouched(self):
        fm = "tags:\n  - mine\n  - other\nsummary: >\n  My own folded\n  summary.\n"
        p = self.write("a.md", "---\n" + fm + "---\nbody\n")
        self.tag(p)
        out = p.read_text()
        self.assertTrue(out.startswith("---\n" + fm), out)
        self.assertIn("type: adr\n", out)
        self.assertEqual(out.count("tags:"), 1)
        self.assertEqual(out.count("summary:"), 1)


class OwnershipTests(Base):  # I1
    def test_ownership_survives_lost_state(self):
        p = self.write("a.md", "first body\n")
        self.tag(p)
        self.state = {"files": {}}  # fresh clone / deleted state.json
        p.write_text(p.read_text().replace("first body", "second body"))
        with mock.patch.dict(os.environ, {"MDINDEX_FAKE_RESPONSE": BUG}):
            self.assertEqual(self.tag(p), "tagged")
        fields = mdindex.read_doc(p.read_text()).fields
        self.assertEqual(fields["type"], "bug")
        self.assertEqual(fields["tags"], ["login"])

    def test_user_edit_of_owned_value_is_respected(self):
        p = self.write("a.md", "first body\n")
        self.tag(p)
        p.write_text(p.read_text().replace("type: adr", "type: spec").replace("first body", "second body"))
        self.state = {"files": {}}
        with mock.patch.dict(os.environ, {"MDINDEX_FAKE_RESPONSE": BUG}):
            self.tag(p)
        fields = mdindex.read_doc(p.read_text()).fields
        self.assertEqual(fields["type"], "spec")
        self.assertEqual(fields["tags"], ["login"])

    def test_marker_lists_owned_keys(self):
        p = self.write("a.md", "body\n")
        self.tag(p)
        marker = mdindex.read_doc(p.read_text()).fields["mdindex"]
        self.assertEqual(sorted(m.split("=")[0] for m in marker), ["related", "summary", "tags", "type"])


class LegacyStateTests(Base):  # docs tagged before the marker existed
    def test_old_state_ownership_still_honoured(self):
        p = self.write("a.md", "---\ntype: adr\n---\nnew body\n")
        self.state = {"files": {"a.md": {"hash": "old", "owned": {"type": "adr"}, "skipped": None}}}
        with mock.patch.dict(os.environ, {"MDINDEX_FAKE_RESPONSE": BUG}):
            self.tag(p)
        self.assertEqual(mdindex.read_doc(p.read_text()).fields["type"], "bug")


class CrashSafetyTests(Base):  # I2
    def test_state_saved_per_file(self):
        (self.root / ".mdindex/config.json").write_text(json.dumps(self.cfg))
        self.write("a.md", "a\n")
        self.write("b.md", "b\n")
        answers = [json.loads(open(OK).read()), SystemExit("killed")]
        with mock.patch.object(mdindex, "request_tags", side_effect=answers), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                mdindex.cmd_sync(self.root)
        self.assertIn("a.md", mdindex.load_state(self.root)["files"])

    def test_init_detach_spawns_background_sync(self):
        import shutil
        shutil.rmtree(self.root / ".mdindex")
        with mock.patch.object(mdindex, "_spawn_detached") as spawn, redirect_stdout(io.StringIO()):
            self.assertEqual(mdindex.cmd_init(self.root, detach=True), 0)
        spawn.assert_called_once_with(["sync", str(self.root)])
        self.assertTrue((self.root / ".mdindex/config.json").exists())


class LineEndingTests(Base):  # I3
    def test_crlf_frontmatter_recognised(self):
        p = self.root / "w.md"
        p.write_bytes(b"---\r\ntitle: Win\r\n---\r\nbody\r\nline2\r\n")
        self.tag(p)
        out = p.read_bytes()
        self.assertTrue(out.startswith(b"---\r\ntitle: Win\r\n"), out)
        self.assertEqual(out.count(b"---\r\n"), 2)
        self.assertNotIn(b"\n---\n", out)
        self.assertTrue(out.endswith(b"---\r\nbody\r\nline2\r\n"))
        self.assertIn(b"type: adr\r\n", out)

    def test_crlf_plain_doc_gets_crlf_frontmatter(self):
        p = self.root / "w2.md"
        p.write_bytes(b"# T\r\nbody\r\n")
        self.tag(p)
        self.assertTrue(p.read_bytes().startswith(b"---\r\ntype: adr\r\n"))

    def test_bom_preserved(self):
        p = self.root / "b.md"
        p.write_bytes(b"\xef\xbb\xbf---\ntitle: X\n---\nbody\n")
        self.tag(p)
        out = p.read_bytes()
        self.assertTrue(out.startswith(b"\xef\xbb\xbf---\ntitle: X\n"), out)
        self.assertEqual(out.count(b"---\n"), 2)


class EncodingTests(Base):  # I4
    def test_non_utf8_skipped_and_untouched(self):
        p = self.root / "l.md"
        p.write_bytes(b"Caf\xe9\n")
        self.assertEqual(self.tag(p), "skipped-encoding")
        self.assertEqual(p.read_bytes(), b"Caf\xe9\n")
        self.assertEqual(self.state["files"]["l.md"]["skipped"], "encoding")


class ExclusionTests(Base):  # I5
    def test_tool_dirs_excluded_at_any_depth_regardless_of_config(self):
        for rel in ["packages/a/node_modules/lib/README.md", ".pytest_cache/README.md",
                    ".github/PULL_REQUEST_TEMPLATE.md", ".venv/lib/x.md", "venv/x.md",
                    "vendor/pkg/x.md", "sub/.git/x.md", ".superpowers/sdd/x.md"]:
            self.write(rel, "x\n")
        self.write("docs/keep.md", "k\n")
        self.assertEqual(self.rels(dict(self.cfg, exclude=[])), ["docs/keep.md"])
        self.assertFalse(mdindex.is_included(".github/PULL_REQUEST_TEMPLATE.md", dict(self.cfg, exclude=[])))

    def test_gitignored_files_skipped_in_git_repo(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.write(".gitignore", "build/\n")
        self.write("build/out.md", "x\n")
        self.write("docs/new.md", "untracked but not ignored\n")
        self.assertEqual(self.rels(), ["docs/new.md"])

    def test_pending_respects_gitignore(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".mdindex/config.json").write_text(json.dumps(self.cfg))
        self.write(".gitignore", "build/\n")
        self.write("build/out.md", "x\n")
        (self.root / ".mdindex/pending").write_text("build/out.md\n")
        with redirect_stdout(io.StringIO()):
            mdindex.cmd_sync(self.root, pending_only=True)
        self.assertEqual((self.root / "build/out.md").read_text(), "x\n")


class SymlinkTests(Base):  # I6
    def test_symlinked_doc_skipped(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("secret-ish outside content\n")
            (self.root / "docs").mkdir()
            (self.root / "docs/link.md").symlink_to(target)
            self.assertEqual(self.rels(), [])
            self.assertEqual(self.tag(self.root / "docs/link.md"), "skipped-symlink")
            self.assertTrue((self.root / "docs/link.md").is_symlink())
            self.assertEqual(target.read_text(), "secret-ish outside content\n")


class InitTests(Base):  # I7
    def setUp(self):
        super().setUp()
        import shutil
        shutil.rmtree(self.root / ".mdindex")

    def test_init_failure_leaves_no_config(self):
        with mock.patch.dict(os.environ, {"FAKE_QMD_FAIL": "collection add"}), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(mdindex.MdindexError):
                mdindex.cmd_init(self.root)
        self.assertFalse((self.root / ".mdindex/config.json").exists())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(mdindex.cmd_init(self.root), 0)
        self.assertTrue((self.root / ".mdindex/config.json").exists())

    def test_init_name_clash_uses_unique_name(self):
        base = mdindex._collection_name(self.root)
        with mock.patch.dict(os.environ, {"FAKE_QMD_FAIL": f"--name {base} "}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(mdindex.cmd_init(self.root), 0)
        name = json.loads((self.root / ".mdindex/config.json").read_text())["collection"]
        self.assertTrue(name.startswith(base + "-"), name)
        self.assertEqual(len(name), len(base) + 7)


class YamlRenderTests(unittest.TestCase):  # I8
    def test_render_quotes_indicator_and_typed_scalars(self):
        for s in ["`mdindex` CLI notes", "*Draft* plan", "@scope/pkg", "!x", "%x", "- dash",
                  "& anchor", "| pipe", "> gt", "? q", "true", "No", "null", "~", "2026-10-01", "123", "1.5"]:
            line = "k: " + mdindex._render_value(s)
            self.assertTrue(line.startswith('k: "'), line)
            self.assertEqual(mdindex.read_doc(f"---\n{line}\n---\n").fields["k"], s)
        self.assertEqual(mdindex._render_value("plain words here"), "plain words here")
        self.assertEqual(mdindex._render_value("task-12"), "task-12")

    def test_list_item_with_quote_roundtrips(self):
        v = ['a"b', "c, d", "e"]
        out = mdindex.read_doc("---\nk: " + mdindex._render_value(v) + "\n---\n").fields["k"]
        self.assertEqual(out, v)


if __name__ == "__main__":
    unittest.main()

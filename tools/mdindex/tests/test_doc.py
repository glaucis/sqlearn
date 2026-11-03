import unittest

from helpers import TempProject

import mdindex


class DocModelTests(unittest.TestCase):
    def test_roundtrip_without_frontmatter(self):
        t = "# Title\n\nBody text.\n"
        self.assertEqual(mdindex.render_doc(mdindex.read_doc(t)), t)

    def test_roundtrip_with_frontmatter(self):
        t = "---\ntitle: Hello\ntags: [a, b]\n---\n# Body\n"
        self.assertEqual(mdindex.render_doc(mdindex.read_doc(t)), t)

    def test_parses_inline_list(self):
        doc = mdindex.read_doc("---\ntags: [a, b]\n---\nx\n")
        self.assertEqual(doc.fields["tags"], ["a", "b"])

    def test_preserves_unparsed_frontmatter_lines(self):
        raw = ["notes: |", "  first line", "  second line", "# comment"]
        t = "---\n" + "\n".join(raw) + "\n---\nbody\n"
        doc, _ = mdindex.set_fields(mdindex.read_doc(t), {"type": "adr"}, {})
        out = mdindex.render_doc(doc)
        for line in raw:
            self.assertIn(line + "\n", out)
        self.assertIn("type: adr\n", out)
        self.assertTrue(out.endswith("---\nbody\n"))

    def test_set_fields_respects_user_value(self):
        doc = mdindex.read_doc("---\ntype: spec\n---\nx\n")
        doc, owned = mdindex.set_fields(doc, {"type": "adr"}, {})
        self.assertEqual(doc.fields["type"], "spec")
        self.assertNotIn("type", owned)

    def test_set_fields_updates_owned_value(self):
        doc = mdindex.read_doc("---\ntype: idea\n---\nx\n")
        doc, owned = mdindex.set_fields(doc, {"type": "adr"}, {"type": "idea"})
        self.assertEqual(doc.fields["type"], "adr")
        self.assertIn("type: adr\n", mdindex.render_doc(doc))
        self.assertEqual(owned["type"], "adr")

    def test_set_fields_adds_frontmatter_to_plain_doc(self):
        doc = mdindex.read_doc("# T\n")
        doc, _ = mdindex.set_fields(doc, {"type": "bug", "tags": ["x"]}, {})
        self.assertEqual(mdindex.render_doc(doc), "---\ntype: bug\ntags: [x]\n---\n# T\n")

    def test_string_with_colon_is_quoted_and_reparsed(self):
        doc, _ = mdindex.set_fields(mdindex.read_doc("x\n"), {"summary": 'a: b "c"'}, {})
        again = mdindex.read_doc(mdindex.render_doc(doc))
        self.assertEqual(again.fields["summary"], 'a: b "c"')

    def test_body_hash_ignores_frontmatter(self):
        a = mdindex.read_doc("---\ntype: x\n---\nsame\n")
        b = mdindex.read_doc("same\n")
        self.assertEqual(mdindex.body_hash(a.body), mdindex.body_hash(b.body))
        self.assertNotEqual(mdindex.body_hash("same\n"), mdindex.body_hash("other\n"))


class ProjectTests(TempProject):
    def test_find_root_walks_up(self):
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(mdindex.find_root(deep), self.root)

    def test_find_root_none_without_mdindex(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(mdindex.find_root(Path(d)))

    def test_iter_docs_applies_excludes(self):
        self.write("docs/a.md", "a")
        self.write("node_modules/x.md", "x")
        self.write("raw/y.md", "y")
        self.write("notes.txt", "n")
        docs = mdindex.iter_docs(self.root, mdindex.DEFAULT_CONFIG)
        self.assertEqual([p.relative_to(self.root).as_posix() for p in docs], ["docs/a.md"])

    def test_state_roundtrip(self):
        st = {"files": {"a.md": {"hash": "h", "owned": {"type": "adr"}, "skipped": None}}}
        mdindex.save_state(self.root, st)
        self.assertEqual(mdindex.load_state(self.root), st)

    def test_load_state_default_when_missing(self):
        self.assertEqual(mdindex.load_state(self.root), {"files": {}})


if __name__ == "__main__":
    unittest.main()

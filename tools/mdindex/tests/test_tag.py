import json
import os
import unittest
from unittest import mock

from helpers import FIXTURES, TempProject

import mdindex


class TagTests(TempProject):
    def setUp(self):
        super().setUp()
        self.cfg = dict(mdindex.DEFAULT_CONFIG, collection="t")
        self.state = {"files": {}}
        env = mock.patch.dict(os.environ, {"MDINDEX_FAKE_RESPONSE": str(FIXTURES / "response_ok.json")})
        env.start()
        self.addCleanup(env.stop)

    def test_tag_writes_frontmatter(self):
        p = self.write("docs/adr/0002.md", "# Use Postgres\n\nWe pick Postgres.\n")
        self.assertEqual(mdindex.tag_file(self.root, p, self.cfg, self.state), "tagged")
        doc = mdindex.read_doc(p.read_text())
        self.assertEqual(doc.fields["type"], "adr")
        self.assertEqual(doc.fields["tags"], ["database", "storage"])
        self.assertEqual(doc.fields["summary"], "Decision to use Postgres for storage.")
        self.assertEqual(doc.body, "# Use Postgres\n\nWe pick Postgres.\n")
        entry = self.state["files"]["docs/adr/0002.md"]
        self.assertEqual(entry["hash"], mdindex.body_hash(doc.body))
        self.assertEqual(entry["owned"]["type"], "adr")

    def test_tag_unchanged_when_hash_matches(self):
        p = self.write("a.md", "body\n")
        mdindex.tag_file(self.root, p, self.cfg, self.state)
        with mock.patch.dict(os.environ, {"MDINDEX_FAKE_RESPONSE": str(self.root / "gone.json")}):
            self.assertEqual(mdindex.tag_file(self.root, p, self.cfg, self.state), "unchanged")

    def test_invalid_type_falls_back_to_note(self):
        out = mdindex.validate_tags({"type": "banana", "tags": [], "summary": "s"}, self.cfg["types"])
        self.assertEqual(out["type"], "note")

    def test_validate_limits_and_cleans(self):
        out = mdindex.validate_tags(
            {"type": "bug", "tags": [f"T{i}" for i in range(10)], "summary": "x" * 300 + "\nmore",
             "related": [str(i) for i in range(12)]}, self.cfg["types"])
        self.assertEqual(len(out["tags"]), 6)
        self.assertEqual(out["tags"][0], "t0")
        self.assertLessEqual(len(out["summary"]), 160)
        self.assertNotIn("\n", out["summary"])
        self.assertEqual(len(out["related"]), 8)

    def test_validate_drops_empty_values(self):
        out = mdindex.validate_tags({"type": "idea", "tags": [], "summary": "", "related": []}, self.cfg["types"])
        self.assertEqual(out, {"type": "idea"})

    def test_secret_docs_not_sent(self):
        text = "key: sk-ant-abc123\n"
        p = self.write("s.md", text)
        with mock.patch.object(mdindex, "request_tags", side_effect=AssertionError("sent")):
            self.assertEqual(mdindex.tag_file(self.root, p, self.cfg, self.state), "skipped-secret")
        self.assertEqual(p.read_text(), text)
        self.assertEqual(self.state["files"]["s.md"]["skipped"], "secret")

    def test_contains_secret_patterns(self):
        self.assertTrue(mdindex.contains_secret("AKIAABCDEFGHIJKLMNOP"))
        self.assertTrue(mdindex.contains_secret("-----BEGIN RSA PRIVATE KEY-----"))
        self.assertFalse(mdindex.contains_secret("we use sk-learn and akia"))

    def test_tag_skips_file_changed_during_request(self):
        p = self.write("c.md", "original\n")

        def edit_then_answer(rel, body, cfg):
            with open(p, "a", encoding="utf-8") as f:
                f.write("added by user\n")
            return json.loads((FIXTURES / "response_ok.json").read_text())

        with mock.patch.object(mdindex, "request_tags", side_effect=edit_then_answer):
            self.assertEqual(mdindex.tag_file(self.root, p, self.cfg, self.state), "skipped-changed")
        self.assertEqual(p.read_text(), "original\nadded by user\n")
        self.assertNotIn("c.md", self.state["files"])

    def test_missing_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        failed = mock.Mock(returncode=44, stdout="")
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("subprocess.run", return_value=failed):
            with self.assertRaises(mdindex.MdindexError) as cm:
                mdindex.get_api_key()
        self.assertIn("mdindex-anthropic", str(cm.exception))

    def test_key_from_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-1234567890"}):
            self.assertEqual(mdindex.get_api_key(), "sk-test-1234567890")

    def test_request_builds_structured_output_call(self):
        captured = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"stop_reason": "end_turn", "content": [
                    {"type": "text", "text": json.dumps({"type": "bug", "tags": ["a"], "summary": "s", "related": []})}
                ]}).encode()

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = json.loads(req.data)
            return Resp()

        env = {k: v for k, v in os.environ.items() if k != "MDINDEX_FAKE_RESPONSE"}
        env["ANTHROPIC_API_KEY"] = "sk-test-key"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = mdindex.request_tags("docs/x.md", "y" * 20000, self.cfg)
        self.assertEqual(out["type"], "bug")
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(captured["headers"]["x-api-key"], "sk-test-key")
        self.assertEqual(captured["headers"]["anthropic-version"], "2026-10-21")
        body = captured["body"]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertIn("adr", body["system"])
        self.assertLessEqual(body["messages"][0]["content"].count("y"), 12000)

    def test_refusal_raises(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"stop_reason": "refusal", "content": []}).encode()

        env = {k: v for k, v in os.environ.items() if k != "MDINDEX_FAKE_RESPONSE"}
        env["ANTHROPIC_API_KEY"] = "k"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", return_value=Resp()):
            with self.assertRaises(mdindex.MdindexError):
                mdindex.request_tags("x.md", "b", self.cfg)


if __name__ == "__main__":
    unittest.main()

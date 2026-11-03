#!/usr/bin/env python3
"""mdindex: tag markdown docs with Haiku and keep a QMD index current.

A project opts in by having a `.mdindex/` folder (created by `mdindex init`).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "collection": "",
    "include": ["**/*.md"],
    "exclude": [".git/**", "node_modules/**", ".mdindex/**", ".claude/**", "raw/**"],
    "types": ["adr", "spec", "architecture", "guide", "bug", "idea", "question", "task", "note"],
    "model": "claude-haiku-5-5",
    "max_chars": 12000,
}

MD_DIR = ".mdindex"


class MdindexError(Exception):
    pass


# ---------------------------------------------------------------- documents

@dataclass
class Doc:
    lines: list[str] = field(default_factory=list)  # raw frontmatter lines, no fences
    fields: dict = field(default_factory=dict)  # parsed top-level key: value / key: [list]
    body: str = ""
    has_frontmatter: bool = False


_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s(.*))?$")


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_parse_scalar(x) for x in _split_list(inner)] if inner else []
    return _parse_scalar(raw)


def _split_list(inner: str) -> list[str]:
    out, cur, q = [], "", None
    for ch in inner:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip() for x in out]


def _parse_scalar(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)
        except ValueError:
            return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def _render_scalar(v: str) -> str:
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{},\"'\n]", s) or s != s.strip():
        return json.dumps(s, ensure_ascii=False)
    return s


def _render_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_render_scalar(x) for x in v) + "]"
    return _render_scalar(v)


def read_doc(text: str) -> Doc:
    if not text.startswith("---\n"):
        return Doc([], {}, text, False)
    end = text.find("\n---\n", 3)
    if end == -1:
        if text.endswith("\n---"):
            end = len(text) - 4
        else:
            return Doc([], {}, text, False)
    block = text[4:end + 1]
    body = text[end + 5:]
    lines = block.split("\n")[:-1] if block else []
    fields_: dict = {}
    for line in lines:
        m = _KEY_RE.match(line)
        if m and m.group(2) is not None and m.group(2).strip() not in ("", "|", ">", "|-", ">-"):
            fields_[m.group(1)] = _parse_value(m.group(2))
    return Doc(lines, fields_, body, True)


def render_doc(doc: Doc) -> str:
    if not doc.has_frontmatter:
        return doc.body
    return "---\n" + "".join(l + "\n" for l in doc.lines) + "---\n" + doc.body


def set_fields(doc: Doc, new: dict, owned: dict) -> tuple[Doc, dict]:
    lines = list(doc.lines)
    fields_ = dict(doc.fields)
    owned_out = dict(owned)
    for k, v in new.items():
        if k in fields_ and fields_[k] != owned.get(k):
            owned_out.pop(k, None)
            continue  # user-set value: never touch
        rendered = f"{k}: {_render_value(v)}"
        for i, line in enumerate(lines):
            m = _KEY_RE.match(line)
            if m and m.group(1) == k:
                lines[i] = rendered
                break
        else:
            lines.append(rendered)
        fields_[k] = v
        owned_out[k] = v
    has = doc.has_frontmatter or bool(lines)
    return Doc(lines, fields_, doc.body, has), owned_out


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- project

def find_root(start: Path) -> Path | None:
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / MD_DIR).is_dir():
            return d
    return None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.mdindex-tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_config(root: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(root / MD_DIR / "config.json", {}))
    return cfg


def load_state(root: Path) -> dict:
    st = _read_json(root / MD_DIR / "state.json", {"files": {}})
    st.setdefault("files", {})
    return st


def save_state(root: Path, state: dict) -> None:
    _write_atomic(root / MD_DIR / "state.json", json.dumps(state, indent=2, sort_keys=True))


def _matches(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
    return False


def is_included(rel: str, config: dict) -> bool:
    return _matches(rel, config["include"]) and not _matches(rel, config["exclude"])


def iter_docs(root: Path, config: dict) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        reld = d.relative_to(root).as_posix()
        dirnames[:] = [n for n in dirnames
                       if not _matches((f"{reld}/{n}" if reld != "." else n) + "/x", config["exclude"])]
        for name in filenames:
            p = d / name
            rel = p.relative_to(root).as_posix()
            if is_included(rel, config):
                out.append(p)
    return sorted(out)

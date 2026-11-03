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


# ---------------------------------------------------------------- tagging

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
KEYCHAIN_SERVICE = "mdindex-anthropic"

_SECRET_RES = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

_TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "related": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["type", "tags", "summary", "related"],
    "additionalProperties": False,
}


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    import subprocess
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    raise MdindexError(f"no API key: set ANTHROPIC_API_KEY or add Keychain item {KEYCHAIN_SERVICE}")


def contains_secret(body: str) -> bool:
    return any(r.search(body) for r in _SECRET_RES)


def _system_prompt(types: list[str]) -> str:
    return (
        "You classify one markdown document from a software project so it can be found later.\n"
        f"type: exactly one of: {', '.join(types)}. Use note when nothing else fits.\n"
        "tags: 2-6 short lowercase topic keywords (single words or kebab-case).\n"
        "summary: one sentence, at most 160 characters, saying what the document is about.\n"
        "related: IDs of other items the document mentions, such as ADR-0003 or task-12; "
        "empty list if none. Do not invent IDs."
    )


def request_tags(rel: str, body: str, config: dict) -> dict:
    fake = os.environ.get("MDINDEX_FAKE_RESPONSE")
    if fake:
        return json.loads(Path(fake).read_text(encoding="utf-8"))
    import urllib.error
    import urllib.request
    payload = {
        "model": config["model"],
        "max_tokens": 1024,
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": _TAG_SCHEMA}},
        "system": _system_prompt(config["types"]),
        "messages": [{"role": "user",
                      "content": f"Path: {rel}\n\n<document>\n{body[:config['max_chars']]}\n</document>"}],
    }
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "content-type": "application/json",
        "x-api-key": get_api_key(),
        "anthropic-version": API_VERSION,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise MdindexError(f"API HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MdindexError(f"API unreachable: {e}") from None
    if data.get("stop_reason") == "refusal":
        raise MdindexError("API refused to tag this document")
    text = next((b.get("text") for b in data.get("content", []) if b.get("type") == "text"), None)
    if not text:
        raise MdindexError(f"API returned no text (stop_reason={data.get('stop_reason')})")
    try:
        return json.loads(text)
    except ValueError:
        raise MdindexError("API returned invalid JSON") from None


def validate_tags(raw: dict, types: list[str]) -> dict:
    out: dict = {}
    t = str(raw.get("type", "")).strip().lower()
    out["type"] = t if t in types else "note"
    tags: list[str] = []
    for x in raw.get("tags") or []:
        x = str(x).strip().lower()
        if x and x not in tags:
            tags.append(x)
    if tags:
        out["tags"] = tags[:6]
    summary = " ".join(str(raw.get("summary") or "").split())
    if summary:
        out["summary"] = summary[:160]
    related = [str(x).strip() for x in (raw.get("related") or []) if str(x).strip()]
    if related:
        out["related"] = related[:8]
    return out


def tag_file(root: Path, path: Path, config: dict, state: dict) -> str:
    rel = path.relative_to(root).as_posix()
    original = path.read_bytes()
    doc = read_doc(original.decode("utf-8", "replace"))
    h = body_hash(doc.body)
    entry = state["files"].get(rel)
    if entry and entry.get("hash") == h:
        return "unchanged"
    if contains_secret(doc.body):
        state["files"][rel] = {"hash": h, "owned": (entry or {}).get("owned", {}), "skipped": "secret"}
        return "skipped-secret"
    tags = validate_tags(request_tags(rel, doc.body, config), config["types"])
    if path.read_bytes() != original:
        return "skipped-changed"
    new_doc, owned = set_fields(doc, tags, (entry or {}).get("owned", {}))
    _write_atomic(path, render_doc(new_doc))
    state["files"][rel] = {"hash": h, "owned": owned, "skipped": None}
    return "tagged"


# ---------------------------------------------------------------- commands

LOCK_STALE_SECONDS = 10 * 60


def run_qmd(args: list[str]) -> None:
    import subprocess
    exe = os.environ.get("MDINDEX_QMD", "qmd")
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True)
    except OSError as e:
        raise MdindexError(f"qmd not runnable ({exe}): {e}") from None
    if r.returncode != 0:
        raise MdindexError(f"qmd {' '.join(args)} failed ({r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")


def _log(root: Path, msg: str) -> None:
    import datetime
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(root / MD_DIR / "log", "a", encoding="utf-8") as f:
        f.write(f"{ts} {' '.join(msg.split())}\n")


def acquire_lock(root: Path) -> bool:
    import time
    lock = root / MD_DIR / "lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            return False
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def release_lock(root: Path) -> None:
    try:
        (root / MD_DIR / "lock").unlink()
    except FileNotFoundError:
        pass


def _collection_name(root: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "docs"


def cmd_init(root: Path) -> int:
    root = Path(root).resolve()
    md = root / MD_DIR
    if (md / "config.json").exists():
        print("already initialised")
        return 0
    md.mkdir(exist_ok=True)
    cfg = dict(DEFAULT_CONFIG, collection=_collection_name(root))
    (md / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    save_state(root, {"files": {}})
    run_qmd(["collection", "add", str(root), "--name", cfg["collection"], "--mask", "**/*.md"])
    print(f"initialised mdindex for {root} (collection {cfg['collection']})")
    return cmd_sync(root)


def _read_pending(root: Path) -> list[str]:
    try:
        lines = (root / MD_DIR / "pending").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return list(dict.fromkeys(l.strip() for l in lines if l.strip()))


def cmd_sync(root: Path, pending_only: bool = False) -> int:
    root = Path(root).resolve()
    if not acquire_lock(root):
        return 0
    try:
        config = load_config(root)
        state = load_state(root)
        if pending_only:
            rels = _read_pending(root)
            (root / MD_DIR / "pending").write_text("", encoding="utf-8")
            paths = [root / r for r in rels if is_included(r, config) and (root / r).is_file()]
        else:
            paths = iter_docs(root, config)
        counts: dict[str, int] = {}
        for p in paths:
            rel = p.relative_to(root).as_posix()
            try:
                result = tag_file(root, p, config, state)
            except Exception as e:  # never let one doc break the sync
                result = "error"
                _log(root, f"{rel}: {e}")
            counts[result] = counts.get(result, 0) + 1
        live = {p.relative_to(root).as_posix() for p in iter_docs(root, config)}
        state["files"] = {k: v for k, v in state["files"].items() if k in live}
        save_state(root, state)
        try:
            run_qmd(["update"])
            run_qmd(["embed"])
        except MdindexError as e:
            _log(root, str(e))
        if counts:
            print(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        return 0
    except Exception as e:
        _log(root, f"sync failed: {e}")
        return 0
    finally:
        release_lock(root)


def cmd_status(root: Path) -> int:
    root = Path(root).resolve()
    config = load_config(root)
    state = load_state(root)
    c = {"tagged": 0, "untagged": 0, "changed": 0, "skipped": 0}
    docs = iter_docs(root, config)
    for p in docs:
        rel = p.relative_to(root).as_posix()
        entry = state["files"].get(rel)
        if entry and entry.get("skipped"):
            c["skipped"] += 1
        elif not entry:
            c["untagged"] += 1
        elif entry.get("hash") != body_hash(read_doc(p.read_text(encoding="utf-8", errors="replace")).body):
            c["changed"] += 1
        else:
            c["tagged"] += 1
    print(f"collection: {config['collection']}")
    print(f"docs: {len(docs)}")
    for k in ("tagged", "untagged", "changed", "skipped"):
        print(f"{k}: {c[k]}")
    return 0


def cmd_tag(files: list[str]) -> int:
    rc = 0
    for f in files:
        p = Path(f).resolve()
        root = find_root(p.parent)
        if root is None:
            print(f"{f}: not inside an mdindex project", file=sys.stderr)
            rc = 1
            continue
        config, state = load_config(root), load_state(root)
        try:
            print(f"{f}: {tag_file(root, p, config, state)}")
        except MdindexError as e:
            print(f"{f}: {e}", file=sys.stderr)
            rc = 1
        save_state(root, state)
    return rc


def _project_root(path: str) -> Path | None:
    root = find_root(Path(path))
    if root is None:
        print(f"{path}: not an mdindex project (run `mdindex init` there first)", file=sys.stderr)
    return root


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="mdindex", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status"):
        s = sub.add_parser(name)
        s.add_argument("path", nargs="?", default=".")
    s = sub.add_parser("sync")
    s.add_argument("--pending", action="store_true")
    s.add_argument("path", nargs="?", default=".")
    s = sub.add_parser("tag")
    s.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            return cmd_init(Path(args.path))
        if args.cmd == "tag":
            return cmd_tag(args.files)
        root = _project_root(args.path)
        if root is None:
            return 1
        if args.cmd == "status":
            return cmd_status(root)
        return cmd_sync(root, pending_only=args.pending)
    except MdindexError as e:
        print(f"mdindex: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

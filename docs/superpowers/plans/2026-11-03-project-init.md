# Project Init Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A global `/project-init` skill that sets up any project. It applies a fixed baseline, then lets the user switch on CodeGraph, a docs layout, mdindex (QMD search with Haiku auto-tagging), and Matt Pocock's setup.

**Architecture:** `mdindex` is a single-file Python CLI using only the standard library. Global Claude Code hooks call it, and it switches on per project through a `.mdindex/` folder. It writes frontmatter itself and calls the Messages API directly, so it can never re-trigger hooks. `/project-init` is a manual-only skill that inspects the project, applies the baseline, asks about each module, and records the choices in CLAUDE.md. Everything is built in this repo, then `install.sh` installs it globally.

**Tech Stack:** Python 3.15 (stdlib only: `urllib`, `json`, `hashlib`, `fnmatch`, `unittest`), QMD (`@tobilu/qmd`), Claude Code hooks and skills, macOS Keychain (`security`).

**Spec:** `docs/superpowers/specs/2026-11-03-project-init-design.md`

## Global Constraints

- No AI or tool attribution anywhere: no `Co-Authored-By`, no "Generated with", no AI notes in code or docs. Commit messages end after the body.
- Commits use Conventional Commits. Commit only at the plan's commit steps.
- Python standard library only. No pip installs.
- Model: `claude-haiku-5-5`. API: `POST https://api.anthropic.com/v1/messages`, header `anthropic-version: 2023-06-01`.
- API key: `ANTHROPIC_API_KEY` env var, else `security find-generic-password -s mdindex-anthropic -w`. Never write the key to any file.
- Hook commands must exit 0 and print nothing in projects without `.mdindex/`. That path must finish in under 50 ms.
- mdindex never runs the `claude` CLI.
- Tests: `python3 -m unittest discover -s tools/mdindex/tests -v`. No network calls. The fakes are `MDINDEX_FAKE_RESPONSE` (path to a JSON file) and `MDINDEX_QMD` (path to a fake qmd script).
- Before writing the API client (Task 2), load the `claude-api` skill and confirm the model ID and request shape against it.

## Review Focus

1. **User frontmatter, including lines mdindex can't parse** (multi-line values, comments). These must survive byte-for-byte; only owned keys change. Test: `test_preserves_unparsed_frontmatter_lines` (Task 1).
2. **No key, offline, or API errors during a hook-triggered sync.** Expected: no crash and exit 0, an error line in `.mdindex/log`, the file stays untagged and is retried on the next sync. Test: `test_sync_survives_api_error` (Task 3).
3. **Claude edits a doc while a background sync is rewriting it.** Expected: sync re-reads the file before writing and skips it if it changed. Writes are atomic (temp file plus `os.replace`). Test: `test_tag_skips_file_changed_during_request` (Task 2).
4. **Stop and SessionStart syncs overlap.** Expected: a lock file `.mdindex/lock` holds `O_EXCL` plus the PID; the second sync exits 0 at once; a lock older than 10 minutes is taken over. Test: `test_second_sync_exits_when_locked` (Task 3).
5. **A doc contains a secret.** Expected: bodies matching `sk-ant-`, `AKIA[0-9A-Z]{16}`, or `-----BEGIN [A-Z ]*PRIVATE KEY-----` are never sent; the file is marked `skipped: secret` in state and in `status`. Test: `test_secret_docs_not_sent` (Task 2).

---

### Task 0: Repo baseline

**Files:**
- Create: `.claude/settings.json`, `CLAUDE.md`, `.gitignore`

- [ ] **Step 1:** Run `git init` in `/Users/tomas/coding/glaucis/sqlearn`.
- [ ] **Step 2:** Write `.claude/settings.json` exactly as `{"attribution": {"commit": "", "pr": "", "sessionUrl": false}}`, pretty-printed.
- [ ] **Step 3:** Write `CLAUDE.md` with a one-line project description and the "Commit conventions" section copied verbatim from `~/.claude/CLAUDE.md`, including its "Every new repo carries this itself" subsection.
- [ ] **Step 4:** Write `.gitignore` with `.codegraph/`, `.mdindex/state.json`, `.mdindex/pending`, `.mdindex/lock`, `.mdindex/log`, `__pycache__/`.
- [ ] **Step 5:** Verify with `git status`. Expected: the three files plus `docs/`, untracked.
- [ ] **Step 6: Commit**: `git add -A && git commit -m "chore: initial repo setup with plan and spec"`

### Task 1: mdindex document model (frontmatter, hashing, config, state)

**Files:**
- Create: `tools/mdindex/mdindex.py`
- Test: `tools/mdindex/tests/test_doc.py`

**Interfaces:**
- Produces:
  - `@dataclass Doc(lines: list[str], fields: dict[str, str | list[str]], body: str)`. `lines` holds the raw frontmatter lines, without the `---` fences. `fields` holds only the top-level keys that parsed as `key: value` or `key: [a, b]`.
  - `read_doc(text: str) -> Doc`. Text without a leading `---\n` block gives `Doc([], {}, text)`.
  - `render_doc(doc: Doc) -> str`
  - `set_fields(doc: Doc, new: dict[str, str | list[str]], owned: dict[str, str | list[str]]) -> tuple[Doc, dict]`. It writes key `k` only if `k` is missing from `doc.fields`, or `doc.fields[k] == owned.get(k)`. It returns the updated doc and the new owned map. It rewrites an existing key's line in place and appends new keys at the end.
  - `body_hash(body: str) -> str` (sha256 hex)
  - `DEFAULT_CONFIG: dict` (the values in the spec's "Default config"; `collection` is filled in by `init`)
  - `find_root(start: Path) -> Path | None`: walks up to the first directory containing `.mdindex/`.
  - `load_config(root: Path) -> dict`, `load_state(root: Path) -> dict`, `save_state(root: Path, state: dict) -> None`. State shape: `{"files": {"<posix relpath>": {"hash": str, "owned": dict, "skipped": str | None}}}`. `save_state` writes atomically.
  - `iter_docs(root: Path, config: dict) -> list[Path]`: matches `include` and `exclude` against posix relative paths with `fnmatch`, sorted.

- [ ] **Step 1: Write failing tests**: `test_roundtrip_without_frontmatter` (`render_doc(read_doc(t)) == t`), `test_roundtrip_with_frontmatter`, `test_parses_inline_list` (`tags: [a, b]` → `["a", "b"]`), `test_preserves_unparsed_frontmatter_lines` (a doc holding `notes: |` plus two indented lines and a `# comment`, after `set_fields` with `{"type": "adr"}`, still contains those 4 lines unchanged), `test_set_fields_respects_user_value` (user `type: spec`, owned `{}` → stays `spec`), `test_set_fields_updates_owned_value` (field `type: idea`, owned `{"type": "idea"}`, new `adr` → `adr`), `test_body_hash_ignores_frontmatter`, `test_find_root_walks_up`, `test_iter_docs_applies_excludes` (`node_modules/x.md` and `raw/y.md` excluded, `docs/a.md` included).
- [ ] **Step 2: Run** `python3 -m unittest discover -s tools/mdindex/tests -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the interfaces above in `tools/mdindex/mdindex.py`. Lists render as `key: [a, b]`. Strings containing `:` or `#` render double-quoted, with JSON-style escaping.
- [ ] **Step 4: Run** the tests. Expected: all PASS.
- [ ] **Step 5: Commit**: `git commit -m "feat(mdindex): frontmatter model, state and config"`

### Task 2: Tagging via Haiku

**Files:**
- Modify: `tools/mdindex/mdindex.py`
- Test: `tools/mdindex/tests/test_tag.py`, `tools/mdindex/tests/fixtures/response_ok.json`

**Interfaces:**
- Consumes: Task 1, all of it.
- Produces:
  - `get_api_key() -> str`: raises `MdindexError("no API key: set ANTHROPIC_API_KEY or add Keychain item mdindex-anthropic")` when neither source has one.
  - `contains_secret(body: str) -> bool`, using the three patterns in Review Focus 5.
  - `request_tags(rel: str, body: str, config: dict) -> dict`: when `MDINDEX_FAKE_RESPONSE` is set, it returns that file's JSON and makes no network call. Otherwise it POSTs to the Messages API with `max_tokens: 400`, sends the first `config["max_chars"]` characters of the body plus the path, and asks for one JSON object with keys `type, tags, summary, related`. The system prompt lists `config["types"]`.
  - `validate_tags(raw: dict, types: list[str]) -> dict[str, str | list[str]]`: falls back to `note` for an unknown `type`; `tags` becomes lowercase, deduplicated, at most 6; `summary` is cut to 160 characters on one line; `related` holds at most 8 strings. Empty values are dropped.
  - `tag_file(root: Path, path: Path, config: dict, state: dict) -> str`: returns one of `"tagged" | "unchanged" | "skipped-secret" | "skipped-changed"`. It mutates `state`.
  - `class MdindexError(Exception)`

- [ ] **Step 1: Load the `claude-api` skill** and check the model ID, headers, and how to get JSON-only output for `claude-haiku-5-5`. Record any change to these constraints in this plan before you code.
- [ ] **Step 2: Write failing tests**: `test_tag_writes_frontmatter` (fake response → file gains `type`, `tags`, `summary`; state holds the hash and owned values), `test_tag_unchanged_when_hash_matches` (second call → `"unchanged"`, the fake is not read again: point the env var at a deleted file), `test_invalid_type_falls_back_to_note`, `test_secret_docs_not_sent` (body containing `sk-ant-abc` → `"skipped-secret"`, file bytes unchanged, fake not read), `test_tag_skips_file_changed_during_request` (patch `request_tags` to append to the file before returning → `"skipped-changed"`, the appended text is kept, no frontmatter added), `test_missing_key_raises` (no env var, `security` patched to fail).
- [ ] **Step 3: Run** the tests. Expected: FAIL.
- [ ] **Step 4: Implement** the interfaces. `tag_file` reads the bytes, computes the hash, compares it with state, checks for secrets, calls `request_tags` and `validate_tags`, then re-reads the file. If the bytes differ from the first read, it returns `"skipped-changed"`. Otherwise it calls `set_fields` and writes through a temp file plus `os.replace`.
- [ ] **Step 5: Run** the tests. Expected: all PASS.
- [ ] **Step 6: Commit**: `git commit -m "feat(mdindex): tag docs with Haiku"`

### Task 3: init, sync, status and QMD

**Files:**
- Modify: `tools/mdindex/mdindex.py`
- Test: `tools/mdindex/tests/test_sync.py`, `tools/mdindex/tests/fixtures/fake_qmd.sh` (appends its argv to `$FAKE_QMD_LOG`, exits 0)

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - `run_qmd(args: list[str]) -> None`: binary is `os.environ.get("MDINDEX_QMD", "qmd")`. Raises `MdindexError` on a non-zero exit or a missing binary.
  - `cmd_init(root: Path) -> int`: creates `.mdindex/config.json` (`DEFAULT_CONFIG` with `collection = root.name`, lowercase with non-alphanumerics replaced by `-`) and an empty state, runs `qmd collection add <root> --name <collection> --mask "**/*.md"`, then runs `cmd_sync(root)`. On an already initialised project it prints `already initialised` and returns 0.
  - `cmd_sync(root: Path, pending_only: bool = False) -> int`: takes the lock and tags each doc. With `pending_only`, it tags only the paths in `.mdindex/pending`, which it clears when done. It then runs `qmd update` and `qmd embed`, and appends one line per error to `.mdindex/log` (ISO timestamp, message). It always returns 0 when called from a hook path. Every error is caught.
  - `cmd_status(root: Path) -> int`: prints `collection`, `docs`, `tagged`, `untagged`, `changed`, `skipped`, one per line as `key: value`.
  - `acquire_lock(root: Path) -> bool`, `release_lock(root: Path) -> None`

- [ ] **Step 1: Write failing tests**: `test_init_creates_config_and_registers_collection` (fake qmd log contains `collection add`, the `--name` value, and `--mask **/*.md`), `test_init_twice_is_noop`, `test_sync_tags_then_indexes` (fake log shows `update` and then `embed`), `test_sync_pending_only` (two docs, one pending → only that one tagged; `pending` emptied), `test_sync_survives_api_error` (`request_tags` raises → returns 0, `.mdindex/log` has one line, the doc stays untagged, the next successful sync tags it), `test_second_sync_exits_when_locked`, `test_stale_lock_taken_over` (lock mtime 11 minutes old), `test_status_counts`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces, plus `main(argv: list[str]) -> int` built on argparse, with subcommands `init`, `sync [--pending]`, `tag <file>...`, `status`, and `[path]` defaulting to cwd. End the file with `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.
- [ ] **Step 4: Run** the tests. Expected: all PASS.
- [ ] **Step 5: Commit**: `git commit -m "feat(mdindex): init, sync, status with QMD"`

### Task 4: Hook entry points

**Files:**
- Modify: `tools/mdindex/mdindex.py`
- Test: `tools/mdindex/tests/test_hooks.py`

**Interfaces:**
- Consumes: Task 3 (`find_root`, `cmd_sync`).
- Produces: `cmd_hook(event: str, stdin_text: str) -> int`, where `event` is one of `post-tool-use`, `stop`, `session-start`. It always returns 0 and prints nothing.
  - `post-tool-use`: reads `cwd` and `tool_input.file_path` from the JSON. If the path ends in `.md` and `find_root(dirname)` finds a root, and the file is not excluded, it appends the posix relative path to `.mdindex/pending`.
  - `stop`: if `pending` is non-empty, it starts `[sys.executable, __file__, "sync", "--pending", root]` detached (`start_new_session=True`, stdio to `DEVNULL`).
  - `session-start`: starts `[..., "sync", root]` detached.
  - Invalid JSON or a missing field returns 0.

- [ ] **Step 1: Write failing tests**: `test_post_tool_use_queues_md` (path appears in `pending`), `test_post_tool_use_ignores_non_md`, `test_post_tool_use_ignores_project_without_mdindex`, `test_hook_bad_json_returns_zero`, `test_stop_spawns_sync_when_pending` (patch `subprocess.Popen`, assert the argv includes `--pending`), `test_stop_noop_when_nothing_pending`, `test_hook_fast_path_under_50ms` (the `post-tool-use` hook run as a real subprocess on a temp dir without `.mdindex/`, measured wall time under 50 ms plus the interpreter start time measured with `python3 -c pass`).
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** `cmd_hook` and add the subcommand `hook <event>` to `main`, reading stdin. Keep imports at module top cheap: no `urllib` import until `request_tags` runs.
- [ ] **Step 4: Run** the full suite. Expected: all PASS.
- [ ] **Step 5: Commit**: `git commit -m "feat(mdindex): Claude Code hook entry points"`

### Task 5: QMD install and real smoke test

**Files:**
- Create: `tools/mdindex/README.md` (usage, key setup, troubleshooting)

- [ ] **Step 1:** Run `npm install -g @tobilu/qmd`, then `qmd --version`. Expected: a version prints. Check the README at github.com/tobi/qmd: if the package name or the `collection add`, `update` and `embed` flags differ from Task 3, fix `mdindex.py` and its tests first.
- [ ] **Step 2:** Run `claude plugin marketplace add tobi/qmd && claude plugin install qmd@qmd`, then `claude plugin list`. Expected: `qmd@qmd` is enabled.
- [ ] **Step 3: Key setup (the user does this):** ask the user to run `! security add-generic-password -s mdindex-anthropic -a "$USER" -w` and paste their key at the prompt. Verify with `python3 -c "import sys; sys.path.insert(0,'tools/mdindex'); import mdindex; print(len(mdindex.get_api_key())>20)"`. Expected: `True`.
- [ ] **Step 4: Smoke test** in a scratch dir holding 3 docs (an ADR, a bug, an idea): `python3 tools/mdindex/mdindex.py init <dir>`, then `status`. Expected: `tagged: 3`, and each file has a sensible `type`. Then run `qmd query "<a phrase from the bug doc>" -c <collection>`. Expected: the bug doc ranks first.
- [ ] **Step 5:** Write `tools/mdindex/README.md` covering install, key setup, the commands, the hooks, and where the log is.
- [ ] **Step 6: Commit**: `git commit -m "docs(mdindex): README and verified QMD integration"`

### Task 6: `/project-init` skill

**Files:**
- Create: `skills/project-init/SKILL.md`

**Interfaces:**
- Consumes: the `mdindex init` and `mdindex status` CLIs, `codegraph init -y` and `codegraph status`, and the built-in `init` skill.

- [ ] **Step 1:** Write `SKILL.md` with frontmatter `name: project-init`, `description: Set up this project: baseline rules, then choose CodeGraph, docs layout, docs index, and Matt Pocock setup.`, and `disable-model-invocation: true`. The body is the five-step flow from the spec, written as instructions:
  - Inspection commands to run: `git rev-parse`, `ls -a`, a count of code files by extension, `find . -name '*.md' -not -path './node_modules/*' | wc -l`, and `codegraph status` / `mdindex status` when their folders exist.
  - The baseline steps with their exact content. The commit section is read from `~/.claude/CLAUDE.md` at run time, not copied into the skill.
  - One `AskUserQuestion` per module, with the recommended option first. Recommendation rules: CodeGraph is "yes" when code files exist, otherwise "yes, it'll fill as you code". Docs layout is "yes" when `docs/` is missing. mdindex is "later" when there are fewer than 20 `.md` files, otherwise "yes". Matt Pocock is "yes" for new projects.
  - Each module's install command and its verification command, with the expected output.
  - The `## Project tools` CLAUDE.md template: one bullet per enabled module, giving its usage and how to turn it off.
  - Re-run behaviour: read `## Project tools`, report what's on, ask only about what's missing.
  - The last line of the summary, when Matt Pocock was chosen: "Now type `/setup-matt-pocock-skills`."
- [ ] **Step 2:** Self-check the skill against the spec's flow, one step at a time. Each step should have a concrete command or template.
- [ ] **Step 3: Commit**: `git commit -m "feat: project-init skill"`

### Task 7: Global install

**Files:**
- Create: `install.sh`, `tools/install_hooks.py`
- Test: `tools/mdindex/tests/test_install_hooks.py`

**Interfaces:**
- Produces: `merge_hooks(settings: dict, command_prefix: str) -> dict`. It adds the three hook entries from the spec, each with `"command": f"{command_prefix} hook <event>"`. It is idempotent: an entry whose command starts with `command_prefix` is never added twice. It leaves every existing hook unchanged, including the `codegraph prompt-hook` entry.

- [ ] **Step 1: Write failing tests**: `test_merge_adds_three_hooks`, `test_merge_is_idempotent`, `test_merge_keeps_existing_hooks` (the existing `UserPromptSubmit` codegraph entry survives).
- [ ] **Step 2: Run** them. Expected: FAIL. **Step 3: Implement** `merge_hooks`, plus a `__main__` that backs up `~/.claude/settings.json` to `settings.json.bak-<timestamp>` and then writes it. **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5:** Write `install.sh` (`set -euo pipefail`). It copies `tools/mdindex/mdindex.py` to `~/.local/bin/mdindex` with mode 755 and a `#!/usr/bin/env python3` shebang, symlinks `skills/project-init` to `~/.claude/skills/project-init`, and runs `python3 tools/install_hooks.py`.
- [ ] **Step 6:** Show the user the planned changes to `~/.claude/settings.json` (a diff from a dry run) and get their OK. Then run `./install.sh`, and verify with `which mdindex`, `ls -l ~/.claude/skills/project-init`, and `python3 -m json.tool ~/.claude/settings.json`.
- [ ] **Step 7: Commit**: `git commit -m "feat: global installer for mdindex and project-init"`

### Task 8: End-to-end test

- [ ] **Step 1:** Create a fresh scratch project containing one `.py` file and 25 `.md` docs. In a **new Claude Code session** there, run `/project-init` and accept everything. Expected: a git repo, settings, a CLAUDE.md with the commit section and `## Project tools`, `.codegraph/` populated, `docs/` folders, and `mdindex status` showing `tagged: 25`.
- [ ] **Step 2:** In that session, ask Claude to create `docs/bugs/login-timeout.md`. End the turn, wait 10 seconds, then check the file. Expected: it has frontmatter with `type: bug`, and `qmd query "login timeout"` finds it.
- [ ] **Step 3:** Run `/project-init` again. Expected: it reports everything as enabled and asks nothing.
- [ ] **Step 4:** In a project without `.mdindex/`, edit a `.md` file. Expected: no `.mdindex/` gets created and nothing is written to the file.
- [ ] **Step 5:** Run `/project-init` on sqlearn itself. Expected: the baseline is already in place, so it only asks about the modules.
- [ ] **Step 6:** Fix any problems found, then re-run the affected steps. Commit the fixes as `fix: ...`.

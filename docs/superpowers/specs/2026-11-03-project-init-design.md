# Project Init Toolkit: Design

Date: 2026-11-03
Status: draft for review

## Goal

One command, `/project-init`, sets up any project. It does a fixed baseline
without asking, then explains each optional tool and lets the user switch on
only what this project needs. The tooling is built and tested in this repo
first, then installed globally.

## Components

### 1. `/project-init` skill (global, manual-only)

Lives at `~/.claude/skills/project-init/SKILL.md` after install. It has
`disable-model-invocation: true`, so only the user can start it.

Flow:

1. **Inspect** the project: git repo or not; code present or not, and which
   languages; existing `CLAUDE.md`, `.claude/settings.json`, `.codegraph/`,
   `.mdindex/`, `docs/`; how many `.md` files.
2. **Baseline, no questions** (the user's global rules require these in
   every new repo):
   - `git init` if this is not a repo.
   - `.claude/settings.json` holds
     `{"attribution": {"commit": "", "pr": "", "sessionUrl": false}}`, merged
     into any existing file.
   - `CLAUDE.md` contains the "Commit conventions" section copied from
     `~/.claude/CLAUDE.md`. If the project has code and no CLAUDE.md, run the
     built-in `init` skill first, then add the section.
3. **Optional modules, asked one at a time.** Each question gives one line
   on what it does, one on the cost, and a recommendation based on step 1:
   - **CodeGraph:** code map that updates itself; free. Runs `codegraph init -y`.
   - **Docs layout:** `docs/adr/`, `docs/architecture/`, `docs/specs/`,
     `docs/questions/`, each created with a one-line README.
   - **Docs index (mdindex):** QMD search plus Haiku auto-tagging. Costs API
     credits, a fraction of a cent per changed doc. Runs `mdindex init`.
   - **Matt Pocock engineering setup:** issue tracker, ADRs, glossary. That
     skill is manual-only, so project-init cannot start it. It tells the user
     to type `/setup-matt-pocock-skills` as the last step.
4. **Record** the choices in a `## Project tools` section of CLAUDE.md: what
   is on, how to use it, and how to turn it off.
5. **Summary:** the enabled tools, how to verify each, and next steps.

Re-running it on a project that is already set up shows what is enabled and
offers only what is missing. It never redoes or overwrites existing setup.

### 2. `mdindex` CLI (global)

A single Python 3 file using only the standard library, installed as
`~/.local/bin/mdindex`. Each project switches it on with a `.mdindex/` folder.

Commands:

- `mdindex init [path]`: creates `.mdindex/config.json` and
  `.mdindex/state.json`, registers a QMD collection, tags untagged docs, and
  runs the first index.
- `mdindex sync [path] [--pending]`: tags changed docs, then runs
  `qmd update` and `qmd embed`. With `--pending`, it handles only the files
  queued in `.mdindex/pending`.
- `mdindex tag <file>...`: tags the given files right away.
- `mdindex status [path]`: shows counts of tagged, untagged and changed
  docs, plus the collection name.
- `mdindex hook <post-tool-use|stop|session-start>`: entry points for the
  global hooks. Reads the hook JSON from stdin. Exits 0 silently when the
  project has no `.mdindex/`.

Tagging writes, or merges into, YAML frontmatter at the top of each doc:

```yaml
---
type: adr          # one of config.types
tags: [auth, database]
summary: One line on what this file is about.
related: [ADR-0003, task-12]
---
```

Rules:

- Ownership is tracked per file in `state.json`. mdindex only fills fields
  that are missing, or that it wrote itself and that still hold its value.
  It never overwrites a field the user set.
- A doc is tagged again only when the sha256 of its body, excluding
  frontmatter, changes.
- `type` must be in `config.types`. An invalid answer from the model falls
  back to `note`.
- At most 12,000 characters of the body are sent to the model.

Model calls go straight to the Messages API (`claude-haiku-5-5`) through
`urllib`. They never go through the `claude` CLI, so hooks cannot loop. The
key comes from `ANTHROPIC_API_KEY`, or else from the macOS Keychain with
`security find-generic-password -s mdindex-anthropic -w`.

### 3. Global hooks (in `~/.claude/settings.json`)

| Event | Command | Behaviour |
|---|---|---|
| PostToolUse, matcher `Write\|Edit` | `mdindex hook post-tool-use` | If the file is a `.md` inside an mdindex project, append its path to `.mdindex/pending`. No API call. |
| Stop | `mdindex hook stop` | If anything is pending, start `mdindex sync --pending` detached and return at once. |
| SessionStart | `mdindex hook session-start` | Start `mdindex sync` detached, to catch docs edited by hand. |

### 4. QMD

Installed globally: the `@tobilu/qmd` npm package, plus the `qmd@qmd` Claude
Code plugin for MCP search. It uses one global index, with one collection per
project, named after the project folder.

## Default config (`.mdindex/config.json`)

```json
{
  "collection": "<folder-name>",
  "include": ["**/*.md"],
  "exclude": [".git/**", "node_modules/**", ".mdindex/**", ".claude/**", "raw/**"],
  "types": ["adr", "spec", "architecture", "guide", "bug", "idea", "question", "task", "note"],
  "model": "claude-haiku-5-5",
  "max_chars": 12000
}
```

## Out of scope

- Indexing code. CodeGraph covers it.
- A live file watcher. SessionStart sync covers files edited by hand.
- Local LLMs (Ollama).
- Non-macOS key storage.

## Build location

Everything is developed here first and installed globally by `install.sh`:

- `tools/mdindex/` holds the CLI and its tests.
- `skills/project-init/` holds the skill.

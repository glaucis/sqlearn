# mdindex

Tags markdown docs with Claude Haiku and keeps a [QMD](https://github.com/tobi/qmd) search index up to date. It does nothing in a project until that project has a `.mdindex/` folder.

## What it writes

For each doc it adds frontmatter like this:

```yaml
---
type: bug              # adr, spec, architecture, guide, bug, idea, question, task, note
tags: [auth, session]
summary: Users on slow networks are logged out before the lesson page loads.
related: [task-12]
---
```

It also adds an `mdindex: [type=…, tags=…]` line recording which fields it wrote, with a short hash of each value. It updates those fields when the doc changes, but never touches a field you set or edited yourself, or any multi-line (block-style) value. Because this record lives in the file, it survives a fresh clone or a deleted `state.json`.

Never tagged: `CLAUDE.md` and `AGENTS.md` anywhere, root `README.md`/`CHANGELOG.md`/`LICENSE.md`/`CONTRIBUTING.md`, anything gitignored, symlinks, non-UTF-8 files, and tool folders at any depth (`node_modules`, `.venv`, `vendor`, `.github`, `.git`, caches…). Windows line endings and a UTF-8 BOM are kept as they are. A doc is sent to the model again only when its body changes. Docs that look like they contain a secret (`sk-ant-…`, `AKIA…`, private keys) are never sent; they are marked `skipped`.

## Setup

```sh
npm install -g @tobilu/qmd                              # search engine
security add-generic-password -s mdindex-anthropic -a "$USER" -w   # paste API key at prompt
```

The key can also come from the `ANTHROPIC_API_KEY` environment variable, which takes precedence over the Keychain. `install.sh` at the repo root installs the `mdindex` command and the Claude Code hooks.

## Commands

| Command | Does |
|---|---|
| `mdindex init [--detach] [path]` | Turn on for a project: QMD collection, config, tag all docs, first index (`--detach`: tag in the background) |
| `mdindex sync [path]` | Tag changed docs, then `qmd update` + `qmd embed` |
| `mdindex sync --pending [path]` | Same, only for docs queued by the hooks |
| `mdindex tag <file>…` | Tag specific files now |
| `mdindex status [path]` | Counts: tagged, untagged, changed, skipped |

Search with `qmd query "…" -c <collection>`, or `qmd search` for keyword-only matching. The collection name is in `mdindex status`.

## Hooks (global, in `~/.claude/settings.json`)

| Event | What happens |
|---|---|
| PostToolUse (`Write`/`Edit`) | A `.md` file Claude wrote is queued in `.mdindex/pending`. No API call. |
| Stop | If anything is queued, sync runs in the background. |
| SessionStart | Full sync in the background, which catches docs you edited by hand. |

Hooks always exit 0 and print nothing, so they can never block Claude Code.

## Files

| Path | Commit it? |
|---|---|
| `.mdindex/config.json` | Yes: types, include/exclude patterns, model |
| `.mdindex/state.json` | No: hashes and which fields mdindex owns |
| `.mdindex/pending`, `lock`, `log` | No |

## Troubleshooting

- **Nothing gets tagged:** check `.mdindex/log`. A missing key or an API error is logged there, and the doc is retried on the next sync.
- **Sync seems stuck:** a `.mdindex/lock` file older than 10 minutes is taken over automatically.
- **Turn it off for a project:** delete `.mdindex/`, then run `qmd collection remove <name>`.

## Tests

```sh
python3 -m unittest discover -s tools/mdindex/tests -v
```

The tests make no network calls. `MDINDEX_FAKE_RESPONSE` and `MDINDEX_QMD` swap in fakes for the model and for qmd.

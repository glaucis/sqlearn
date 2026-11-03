---
name: project-init
description: Set up this project: baseline rules, then choose CodeGraph, docs layout, docs index, and Matt Pocock setup.
disable-model-invocation: true
---

# Project init

Set up the current project in five steps. The baseline is applied without asking. Each optional module is explained and offered separately, so the user enables only what this project needs. Never redo or overwrite setup that already exists.

Work in the project root, which is the current directory. If it looks like the home directory or a filesystem root, stop and ask.

## 1. Inspect

Run these and keep the results; later steps use them:

```sh
git rev-parse --is-inside-work-tree 2>/dev/null || echo "no-git"
ls -a
find . -type f \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.go' -o -name '*.rs' -o -name '*.java' -o -name '*.rb' -o -name '*.php' -o -name '*.cs' -o -name '*.swift' -o -name '*.kt' -o -name '*.sql' \) -not -path './node_modules/*' -not -path './.git/*' | sed 's/.*\.//' | sort | uniq -c
find . -name '*.md' -not -path './node_modules/*' -not -path './.git/*' | wc -l
```

Also read `CLAUDE.md` if it exists, and check whether it has a `## Project tools` section.

- **If `## Project tools` exists, this is a re-run.** Report what it lists as enabled. For each module, confirm it really is on: `.codegraph/` exists; `docs/adr/` exists; `.mdindex/config.json` exists; `docs/agents/` exists for Matt Pocock. Then skip to step 3 and offer only the modules that are off. If every module is on, say so and stop after step 5.

## 2. Baseline (no questions)

These follow the user's global rules for every repository. Do each one only if it's missing.

1. **Git.** If `no-git`, run `git init -b main`.
2. **`.claude/settings.json`.** Ensure it contains exactly this `attribution` value, merged into any existing JSON without dropping other keys:
   ```json
   { "attribution": { "commit": "", "pr": "", "sessionUrl": false } }
   ```
3. **`CLAUDE.md`.**
   - If it's missing and step 1 found code files, run the built-in `init` skill first (Skill tool, `init`) so CLAUDE.md describes the codebase.
   - If it's missing and there's no code, create it with `# <folder name>` and one line describing the project. Ask the user for that line, in plain chat.
   - Then make sure CLAUDE.md contains the `## Commit conventions` section. Copy it verbatim from `~/.claude/CLAUDE.md`, from that heading up to the next `## ` heading, including the "Every new repo carries this itself" subsection. Don't paraphrase it. If the section is already present, leave it alone.

Tell the user in one or two lines what the baseline added. Don't commit anything.

## 3. Optional modules

Ask about each module with its own `AskUserQuestion` call, in this order. Each question says what the module does and what it costs, in one line each. The recommended option comes first, with "(Recommended)" on its label, and the recommendation follows the rules below. Offer "Skip" as the alternative.

### a. CodeGraph: code map

- **Gives:** a local map of the code (functions, who calls what) that updates itself on save. Claude finds code in one lookup instead of reading many files.
- **Costs:** nothing. It runs locally, with no tokens and no API.
- **Recommend:** "Yes" if step 1 found code files. Otherwise "Yes, it fills in as you write code".
- **Install:** `codegraph init -y`
- **Verify:** `codegraph status` prints `Index is up to date`.
- **Ignore:** add `.codegraph/` to `.gitignore`.

### b. Docs layout

- **Gives:** standard folders for project knowledge, so docs land in predictable places.
- **Costs:** nothing.
- **Recommend:** "Yes" if `docs/` doesn't exist. If it does, show its top-level folders and recommend "Skip" unless the user wants these folders added next to them.
- **Install:** create these folders, each with a `README.md` whose single line is given here:
  - `docs/adr/`: "Architecture decision records: one file per decision, `NNNN-short-title.md`, never edited after acceptance (supersede instead)."
  - `docs/architecture/`: "How the system works now: overview, data model, key flows."
  - `docs/specs/`: "What to build: one spec per feature, written before implementation."
  - `docs/questions/`: "Open questions. Move the answer into the right doc, then delete the question."
- **Verify:** `ls docs` shows the four folders.

### c. Docs index (mdindex): search and auto-tagging

- **Gives:** every `.md` gets a header block (type, tags, summary, related IDs) written by Claude Haiku, and QMD makes all docs searchable by keyword and by meaning. It updates by itself after Claude edits docs and at session start.
- **Costs:** API credits, a fraction of a cent per changed doc. Unchanged docs are never re-sent. QMD's search models use about 2 GB of disk and run locally.
- **Recommend:** "Later" if step 1 counted fewer than 20 `.md` files, otherwise "Yes". Offer the options "Yes", "Later" and "Skip". "Later" is recorded in Project tools as not enabled.
- **Before installing, check both of these:**
  - `command -v mdindex && command -v qmd`. If either is missing, tell the user it must be installed first (`./install.sh` from the toolkit repo, and `npm install -g @tobilu/qmd`) and treat the answer as "Later".
  - `security find-generic-password -s mdindex-anthropic >/dev/null 2>&1 || test -n "$ANTHROPIC_API_KEY"`. If neither has a key, ask the user to run `! security add-generic-password -s mdindex-anthropic -a "$USER" -w` and paste their key at the prompt. Never ask for the key in chat, and never write it to a file.
- **Install:** `mdindex init`
- **Verify:** `mdindex status` shows `untagged: 0`, or a `.mdindex/log` explains why not. Report the collection name.
- **Ignore:** add `.mdindex/state.json`, `.mdindex/pending`, `.mdindex/lock` and `.mdindex/log` to `.gitignore`. `.mdindex/config.json` is committed.

### d. Matt Pocock engineering setup: tickets, ADRs, glossary

- **Gives:** an issue tracker (GitHub Issues, or local markdown under `.scratch/`), triage labels, and the glossary-and-ADR rules that `/grill-with-docs`, `/to-spec`, `/to-tickets` and `/implement` rely on.
- **Costs:** nothing to run. Its skills overlap with superpowers' planning, TDD and review skills.
- **Recommend:** "Yes" for a new project, meaning step 1 found few or no code files. "Skip" if the user already tracks work elsewhere and says so.
- **Check:** the skill `mattpocock-skills:setup-matt-pocock-skills` must be available. If it isn't, say the plugin isn't installed (`claude plugin install mattpocock-skills@mattpocock`) and record the module as not enabled.
- **Install:** you can't run it yourself, because it's manual-only. Record it as "pending: run `/setup-matt-pocock-skills`" and tell the user in step 5.

## 4. Record

Write or update a `## Project tools` section at the end of CLAUDE.md. It has one bullet per module that's on, and a single `Not enabled:` line listing the rest:

```markdown
## Project tools

- **CodeGraph:** code map in `.codegraph/`, updates on save. Use `codegraph_explore` before grep or reading files. Off: `codegraph uninit`.
- **Docs layout:** `docs/adr/` (decisions), `docs/architecture/` (how it works), `docs/specs/` (what to build), `docs/questions/` (open questions). New decision → new ADR. Answered question → move the answer into the right doc.
- **Docs index:** docs are tagged automatically (frontmatter `type`, `tags`, `summary`, `related`) and searchable with `qmd query "<question>" -c <collection>`. Search here before grepping docs. Status: `mdindex status`. Off: delete `.mdindex/` and run `qmd collection remove <collection>`.
- **Matt Pocock setup:** see `docs/agents/` for the issue tracker and the domain doc rules. (Before setup has run: "pending: run `/setup-matt-pocock-skills`".)

Not enabled: <modules>. Re-run `/project-init` to add them.
```

Keep only the bullets that apply, with the real collection name filled in.

## 5. Summary

End with a short summary:

- **Baseline:** what was added, or "already in place".
- **Enabled:** each module plus its verification result: the command and what it printed.
- **Not enabled:** each module, with how to add it later (re-run `/project-init`).
- **Next:** if Matt Pocock was chosen, the last line is exactly: "Now type `/setup-matt-pocock-skills`."

Say that nothing was committed, and suggest a commit message: `chore: project setup (<enabled modules>)`.

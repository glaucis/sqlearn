---
type: architecture
tags: [workflow, process, agents, skills, docs-layout]
summary: "Describes how work flows from spec to merge, where each document type lives, and which agents and skills are used."
mdindex: [type=4ca303, tags=e7ae13, summary=f7f178]
---
# How work runs

How a part of [the overview](overview.md) goes from idea to merged code, where
each kind of document goes, and which agents and skills do the work.

## From idea to merge

1. **Spec.** Every part becomes a spec through `superpowers:brainstorming`,
   saved in `docs/specs/`. Tomas approves it.
2. **Plan.** The spec becomes a plan through `superpowers:writing-plans`,
   saved in `docs/plans/`.
3. **Branch.** The plan runs on its own branch, in a worktree
   (`superpowers:using-git-worktrees`), through
   `superpowers:subagent-driven-development`: an implementer and a reviewer
   per task, then a final review.
4. **Merge.** Tomas approves the merge
   (`superpowers:finishing-a-development-branch`).

Small work outside a plan runs on `main`, done by one agent.

What runs at each point:

| When | Recipe |
|---|---|
| A commit | the pre-commit hook: `just pre-commit` over the files committed |
| A push | none: a push runs no suite |
| A merge to `main` | the pre-merge-commit hook runs what the pre-commit hook runs; `just done` on `main` runs nothing for a tree that passed |
| Work is done | `just done`: `check-lockfile`, `check-mirror`, `check-no-devdata`, then each check on what changed (`format`, `lint`, `docstrings`, `types`, `test`, `sql`, `validate`, `docs`), then the tree is remembered |
| A release | `just verify`: the same three, each check with `just full` (`validate` as `validate-all`), then `test-all` (coverage) and `test-python-versions`, by hand before `1.0.0` |

`just done` remembers each tree that passed in `sqlearn-passed`, in the git
common directory (the 50 newest, shared by worktrees), with the place it passed
in (Python, platform, machine): in a new place it runs again. Only a committed
tree
counts, the checks' own outputs aside, so a fast-forward or a `--no-ff` merge of
a passed tree runs nothing. Each check runs only on what changed since it
passed, and `just done` runs every one even when one fails:
[testing](testing.md), "How each check finds what changed".

## Where things go

| What | Where |
|---|---|
| Decisions that shape the system | `docs/adr/`, one file each, `NNNN-short-title.md` |
| How the system works now | `docs/architecture/` |
| What to build: one spec per part or feature | `docs/specs/` |
| How to build it: implementation plans | `docs/plans/` |
| Open questions | `docs/questions/`; answered, the answer moves to the right doc |
| Bugs, requests and tasks | GitHub Issues on `glaucis/sqlearn` ([docs/agents/issue-tracker.md](../agents/issue-tracker.md)) |
| Domain vocabulary | `GLOSSARY.md` at the root, created when the first term is settled ([docs/agents/domain.md](../agents/domain.md)) |

The superpowers skills default to `docs/superpowers/specs/` and
`docs/superpowers/plans/`. In this repository they use `docs/specs/` and
`docs/plans/` instead.

## Agents and skills

What exists today, installed for the user rather than in this repository:

- **Method:** the superpowers skills (brainstorming, writing-plans,
  subagent-driven-development, test-driven-development,
  systematic-debugging, code review, verification-before-completion).
- **Planning and tickets:** the Matt Pocock skills (`/to-spec`, `/to-tickets`,
  `/triage`, `/grill-with-docs`, `/domain-modeling`), configured in
  [`docs/agents/`](../agents/).
- **Commits:** the `commit-message` skill, with the rules in `CLAUDE.md`.
- **DuckDB:** the `duckdb-skills` (query, read files, search the DuckDB docs).
- **Finding things:** CodeGraph for code, the docs index (`qmd`) for docs.
- **Agent types:** the built-in general-purpose, Explore and Plan agents.

The rule for adding more (proposed): an agent is created when a kind of work
recurs and needs its own rules; a skill when a method has to be written down to
be repeated. Agents and skills that belong to sqlearn are committed under
`.claude/`. The candidates are listed in
[questions/agents-and-skills.md](../questions/agents-and-skills.md).

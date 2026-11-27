---
type: question
tags: [earlier-attempts, process, agents, validation, foundation]
summary: "Lessons from the autumn sqlearn (30 September – 4 October 2026), the attempt just before this repository: a foundation spec carried over almost whole, agent rehearsals, and no library code."
related: [docs/questions/archived/earlier-attempts/README.md, docs/specs/foundation.md, docs/architecture/workflow.md, docs/questions/agents-and-skills.md, docs/questions/validation-method.md]
---
# What does the autumn `sqlearn` teach the library core?

The autumn `sqlearn` is GitHub `glaucis/sqlearn` from 30 September to
4 October 2026 (ROOT `sqlearn`, 316 commits, branches `main` and
`rehearsal`): the attempt just before this repository. Two batches read it;
the notes, with citations as `OLD:path:Lnn`, are in [notes/](notes/):
[docs and code](notes/A-docs-code.md) and
[records and process](notes/B-records-process.md). Most records and agent
files were skimmed; the checklists say which.

## Summary

- **No library code.** 284 of 316 commits are documentation, 140 of them
  `docs(records)`; the `feat` and `fix` commits are agent scaffolding (hooks,
  an orchestrator, a commit skill) and three commits of throwaway rehearsal
  code. It has no ADRs and no open questions; its decisions sat in a
  `BLUEPRINT.md` that later moved into the foundation spec.
- **Its foundation spec is this repository's.** 21 rows approved on 1 October,
  three decided questions (the per-commit gate, Python versions in a web
  session, commitlint), planned and never built here: `pyproject.toml` still
  said it was not a package. This repository carried the spec over nearly whole
  ([foundation.md](../../../../specs/foundation.md) §18–§19 say so), with the
  commitlint rules, the commit conventions and the attribution settings.
- **"Rehearsal" tested the agent rules, not the product:** four cases on toy
  code with planted faults, checking stop-and-ask, a bug ladder, pauses and
  resumes, with agents nested up to five deep. Case four alone is a
  3,174-line plan with a 74-file work folder.
- **`records/` was a tracker for faults in the agents' own briefs:** 88
  Markdown records (66 bugs, 12 research, 10 ideas), nearly every bug found
  in a brief, spec or plan by the next agent to read it.
- **Tools ended fault classes where prose rules did not:** rumdl and typos
  stopped drift that written rules kept letting through, as a checker script
  did in the war room.

## Bearing on the core

- **Validation:** `tools/sweep.py` checks a function in seeded, reproducible
  chunks against `decimal` at 50 digits, measures the error in ULPs against a
  stated bound, and commits the result lines as text: the measured-bound
  method in a small, runnable form.
- **An independent reference must be independent.**
  `statistics.NormalDist.inv_cdf` is itself Wichura's AS 241 algorithm, so it
  cannot check an AS 241 implementation.
- **DuckDB 2.0.0 has no `erf` and no normal quantile** (it has `gamma` and
  `lgamma`; checked): quantile transforms and normality checks need their own
  implementations.
- **Identifiers:** a hand-typed reserved-word list (split on `" "`) left 15,
  then 31, keywords unquoted. DuckDB lists its own: `duckdb_keywords()` has
  508 keywords, 75 reserved (checked). Quote every identifier, or derive the
  list from DuckDB.
- **SQL representation:** rehearsal case three built SQL as plain strings,
  with no sqlglot: the one attempt that did not use it, on toy code only.

## Against this repository

Kept: the attribution block in `.claude/settings.json`, commitlint, `just`,
uv, Sphinx, Apache-2.0, 80-column Markdown. Dropped: the orchestrator, the
fixed Opus and Sonnet agents, three hooks, 61 copied skill files, the records
and the stop protocol. Possibly worth a look for
[agents-and-skills.md](../../../agents-and-skills.md): the rule on quoting
`$CLAUDE_PROJECT_DIR` in hooks, and the measured facts about agents (a
hand-back wakes an idle parent; a message to a working agent arrives at its
next tool call; 255k to 432k tokens per agent after resumes; web sessions
reach GitHub only through `gh api` REST routes).

## Guard against

Rehearsing the process before building the product; records that track the
process's own faults; plans of thousands of lines for toy cases; nested agents
where one would do.

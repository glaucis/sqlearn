---
type: question
tags: [earlier-attempts, process, fit, duckdb, agents]
summary: "Lessons from the two sql_learn restarts (26–30 August 2026): agent tooling and a task tracker built, no library; chained DuckDB relations found to blow up, and an invariant beats a second copy as an oracle."
related: [docs/questions/archived/earlier-attempts/README.md, docs/questions/archived/fit-execution-model.md, docs/architecture/workflow.md]
---
# What do the `sql_learn` restarts teach the library core?

Two restarts, both GitHub `glaucis/sql_learn` with separate histories:
`sql_learn_27.08.2026` (ROOT, 26 August 2026, 47 commits, 8 files; OLD1) and
`sql_learn` (ROOT, 27–30 August 2026, 68 commits, 75 files; OLD2). One batch
read both; the notes, with citations as `OLD1:` or `OLD2:path:Lnn`, are in
[notes/A-both.md](notes/A-both.md). The task-tracker scripts, half the agent
files and most task notes were skimmed; the checklist says which.

## Summary

- **No library code.** OLD1 has none in 47 commits; OLD2's `src/` is one
  docstring and its `tests/` are empty. OLD2's real code is a task-tracker
  command (`scripts/todo`, about 5,000 lines, 388 tests) and 13 agent
  definitions.
- **OLD1 enforced sole authorship with a `commit-msg` hook, then deleted it**
  (`3add633`, then `3528d48`) with its four-agent git roster, after a git agent
  took 10.5 minutes to commit one Markdown file and was cancelled
  (`OLD1:TODO.md:L71-L78`). Its own `CLAUDE.md` ends "It is NOT enforced".
- **OLD2 rebuilt the same pipeline under new names:** a bug inbox that freezes
  new work, a plan writer and reviewer, and a frozen-contract build in which
  the test writer never sees the implementation. A SessionStart hook injected
  an orchestrator brief and the next task; subagents never saw it.
- **An oracle that is a second copy shares the first copy's bugs.** Two jq
  implementations of the tracker's dependency logic were kept as differential
  oracles; deleting them (`29f0d36`) exposed a defect both had. The lesson
  recorded: a property that states the invariant catches what a second copy
  of the same misunderstanding cannot.
- **Neither records why it stopped.** OLD2 stopped at a clean boundary (clean
  tree, tests passing, the library parked behind a phase only Tomas could
  close), with four blocking bug reports dated after the last commit.

## DuckDB facts, rechecked on 2.0.0

OLD2's plan review measured on DuckDB 1.5.5 that a chain of lazy relations,
each step reading its input twice (a scaler: once for the statistics, once to
apply them), produced SQL text growing about four times per step, 2,916,231
characters at depth 14, and hung at depth 20. On 2.0.0:

| Chain of standardising steps | depth 8 | depth 12 | depth 24 |
|---|---|---|---|
| relation methods (`aggregate`, `cross`, `project`) | 0.03 s | 0.67 s, doubling each step | not run |
| `WITH` stages, default | | 0.007 s | 0.010 s |
| `WITH` stages, `MATERIALIZED` | 0.005 s | 0.005 s | |
| `WITH` stages, `NOT MATERIALIZED` | 0.46 s | out of memory after 46 s (12.8 GiB) | |

The SQL text of the relation chain now grows linearly (about 355 characters a
step), but its running time still doubles with each step, because every step
recomputes its input twice. DuckDB materialises a `WITH` stage that is read
more than once, which keeps a staged fit in one query fast. The other 1.5.5
findings were not rechecked: fitted state held as a lazy relation silently
refits; a relation exposes no connection; duplicate column names resolve
silently through a subquery; `row_number() OVER ()` costs 5.7 to 7.2 times a
plain scan. `inf` and `nan` are not bare SQL literals (`'inf'::DOUBLE` works;
checked).

## Worth keeping

- For fit: stages as `WITH` clauses (left to DuckDB's default, or marked
  `MATERIALIZED`), never chained lazy relations and never `NOT MATERIALIZED`.
- Fitted values as plain values, not as relations that recompute.
- Invariants as oracles, not second implementations.
- The frozen-contract build: tests written against the interface by an agent
  that never sees the code.

## Guard against

Agent rosters slow enough to cost minutes per commit; a task tracker built
before the product; rebuilding a deleted pipeline under new names; an
authorship rule that is written down but not enforced.

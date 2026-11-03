---
type: question
tags: [earlier-attempts, library-core, tracking, plan]
summary: "Plan and progress for absorbing every earlier sqlearn attempt: the numbered steps, each attempt's status, how to resume in a new session, and what is known so far."
related: [docs/architecture/overview.md, docs/questions/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# Earlier attempts

sqlearn was attempted many times before this repository. Each attempt is read
for what is worth keeping and what went wrong, so that the library core (part
3.2 of [the overview](../../architecture/overview.md)) is designed with those
lessons. This page is both the plan and the record of progress. It is the only
place that says what is done and what is next; the GitHub issue
[#8, Library core (3.2)](https://github.com/glaucis/sqlearn/issues/8) tracks
the steps after it (decisions, spec, plan, build).

## Resuming in a new session

1. Read this page to the end.
2. Find the first step under **Plan** that is not ticked. Its attempt row under
   **Attempts** says how far it got.
3. If an attempt is **reading**, look in its `notes/` folder: a batch whose
   notes file exists and ends with a complete **Files covered** checklist is
   done; run only the missing batches.
4. Carry on with the procedure below, then tick the step, update the row and
   **What we know so far**, and commit, all in one commit.

## Plan

- [x] 1. Absorb `sqlearn_000` (before the map existed).
- [x] 2. Absorb sqlearn v0.4 (`sqlearn-ecosystem_old/sqlearn`).
- [ ] 3. Map the folder of attempts:
  `/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas`.
  Adds one row per attempt below, with a tier, and one numbered absorb step
  per attempt here. Tomas confirms the order and the skips.
- [ ] 4. … absorb steps, added by step 3, one per attempt, in the agreed order.
- [ ] Last. Combine **What we know so far** into answers for the four open
  questions; this closes the drain and unblocks the decisions in issue #8.

## Attempts

| Attempt | Source | Tier | Status | Review | Not read |
|---|---|---|---|---|---|
| `sqlearn_000` | GitHub `glaucis/sqlearn_000` | full | merged | [review](sqlearn_000/review.md) | `sqlearn-private`, which it quotes |
| sqlearn v0.4 | `toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn` | full | merged | [review](sqlearn-v04/review.md), [exploration helpers](sqlearn-v04/exploration-helpers.md), [batch notes](sqlearn-v04/notes/) | two standards files; long plans read by heading; 139 test files skimmed |

**Tier:** **full** (unique and substantial: batches as below), **light**
(mostly documents, or a short-lived start: one agent reads its docs and
decisions), **skip** (a duplicate, empty or bare scaffolding; the reason goes
in **Not read**).

**Status:** **to do**, **mapped** (files listed, batches chosen), **reading**
(some batch notes written), **merged** (review written and committed).

## Procedure

**Map** (step 3). For each attempt folder, without reading content in depth:
size, file counts by type, date range, the first lines of its README, and for
git repositories the remote, branch and commit count, read with `git log`
only. Duplicates are found by matching remote and commit, or by matching file
hashes against attempts already read. Generated folders (`.venv`, caches,
build output, `mutants/`, `.hypothesis/`) and data files are counted, not read.
`.env` files and anything that looks like a secret are never opened or copied.

**Absorb** (one step per attempt):

1. **Batches.** Sort the attempt's files by what they answer: design and
   decisions, core code, transformers or steps, validation and tests, process,
   other. A light attempt is one batch.
2. **Agents.** One background agent per batch, briefed as below. Opus for
   design and core code, Sonnet for the rest. Two small attempts may run at
   once; a large one runs alone.
3. **Notes.** Each agent writes `<attempt>/notes/<letter>-<batch>.md`, ending
   with a **Files covered** checklist of every file in its batch.
4. **Review.** The notes are merged into `<attempt>/review.md`: only what is
   new, what contradicts an earlier review, and what confirms an earlier
   finding (one line each). DuckDB claims are rechecked on the current DuckDB.
5. **Close.** Tick the plan step, update the row and **What we know so far**,
   run `just fmt` and `just check`, and commit.

**Agent brief.** Every agent is told: the source folder and that it is read
only (never run code, tests, scripts, package managers or any git command that
writes; never open `.env`); the files in its batch; to read this page's
**What we know so far** and report what is new, what contradicts it and what
confirms it; to cite every claim as `OLD:path:Lnn` and mark inference; and the
notes file to write, with its sections and the **Files covered** checklist.

## What we know so far

From `sqlearn_000` and sqlearn v0.4. Evidence, not decisions; the decisions
are made in issue #8.

- **How fit runs.** Both attempts learned a later step's statistics from the
  raw or stage input, so `Impute` then `Scale` scaled un-imputed data. The
  boundary rule has to be "a learning step reads a value an earlier step
  changed". A staged fit can still be one query with `WITH` clauses (checked on
  DuckDB 2.0.0). Fit must see the same row-level steps as transform, through
  one composer, and nothing in transform may query data.
- **Learned state.** Both kept it as Python values inlined as SQL literals and
  saved as JSON. Failures: `None` meaning both "not fitted" and "learned
  NULL", keys split on `__`, selectors and custom classes that could not be
  saved, float literals never checked. Tables were never considered.
- **SQL representation.** Both used sqlglot from the start. Costs: version
  pins, type-checker noise, AST aliasing bugs, a dialect that changed NULL
  ordering. Portability was never tested beyond parsing.
- **Validation.** Both wrote a strong method (exact references, bounds set from
  measurement) and never enforced it: validators outside the gate, parity
  tests that skipped, hand-picked or correlation-only tolerances, datasets
  downloaded over the network.
- **API.** Both renamed scikit-learn's methods and then added bridges back.
  ADR 0003 stands.
- **Process.** Plans and standards outgrew the product, and nobody updated
  them.

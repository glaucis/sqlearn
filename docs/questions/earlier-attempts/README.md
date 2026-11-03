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
- [x] 3. Map the folder of attempts (called ROOT below):
  `/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas`.
  Eleven projects; order (oldest first) and skips confirmed by Tomas on
  2026-11-03.
- [x] 4. Absorb `ducklearn` (light).
- [x] 5. Absorb `Tomosius/sqlearn`: `sqlearn-desktop`, plus the git history of
  `test/sqlearn` (full).
- [ ] 6. Absorb the April planning repo,
  `sqlearn-ecosystem_old/sqlearn-private`, without `_old_sqlearn` (full).
- [ ] 7. Absorb the war room, `sqlearn-ecosystem/sqlearn-private` (full).
- [ ] 8. Absorb the six commits `sqlearn-ecosystem/sqlearn` has beyond
  `sqlearn_000` (light).
- [ ] 9. Absorb `sql_learn_test` (light, two agents).
- [ ] 10. Absorb `sql_learn_27.08.2026` and `sql_learn` (light).
- [ ] 11. Absorb `sqlearn` of September and October (light, two agents).
- [ ] 12. Combine **What we know so far** into answers for the four open
  questions; this closes the drain and unblocks the decisions in issue #8.

## Attempts

| Attempt | Source | Tier | Status | Review | Not read |
|---|---|---|---|---|---|
| `sqlearn_000` | GitHub `glaucis/sqlearn_000` | full | merged | [review](sqlearn_000/review.md) | `sqlearn-private`, which it quotes |
| sqlearn v0.4 | ROOT `sqlearn-ecosystem_old/sqlearn` (Apr 10–12, 236 commits) | full | merged | [review](sqlearn-v04/review.md), [exploration helpers](sqlearn-v04/exploration-helpers.md), [batch notes](sqlearn-v04/notes/) | two standards files; long plans read by heading; 139 test files skimmed |
| `ducklearn` | ROOT `ducklearn` (Mar 13, no git): 14 design docs | light | merged | [review](ducklearn/review.md), [batch notes](ducklearn/notes/) | |
| `Tomosius/sqlearn` | ROOT `sqlearn-desktop` (no git, 378 files) and ROOT `test/sqlearn` (GitHub `Tomosius/sqlearn`, Mar 13 – Apr 9, 271 commits) | full | merged | [review](tomosius-sqlearn/review.md), [batch notes](tomosius-sqlearn/notes/) | `test/sqlearn`'s 297 cloud-only files; it shares 92% of its local files with `sqlearn-desktop` |
| April planning repo | ROOT `sqlearn-ecosystem_old/sqlearn-private` (GitHub `glaucis/sqlearn-private`, Apr 9–24, 593 commits), 411 files | full | mapped | `sqlearn-private-april/` | `_old_sqlearn/`: an exact copy of v0.4 |
| War room | ROOT `sqlearn-ecosystem/sqlearn-private` (GitHub `glaucis/sqlearn-private`, Apr 26 – Jun 13, 410 commits), 218 docs | full | mapped | `sqlearn-private-war-room/` | |
| `sqlearn_000`, later commits | ROOT `sqlearn-ecosystem/sqlearn` (same first commit, 82 commits against 76) | light | mapped | `sqlearn_000/` | the 76 commits already reviewed |
| `sql_learn_test` | ROOT `sql_learn_test` (Aug 21–24, 59 commits), 85 files | light | mapped | `sql_learn_test/` | |
| `sql_learn` | ROOT `sql_learn_27.08.2026` (Aug 26, 47 commits, 8 files) and ROOT `sql_learn` (Aug 27–30, 68 commits, 75 files), separate histories | light | mapped | `sql_learn/` | |
| `sqlearn`, autumn | ROOT `sqlearn` (Sep 30 – Oct 4, 316 commits), 270 files, mostly agent records | light | mapped | `sqlearn-autumn/` | |

Generated folders, data files and `.env` files are skipped everywhere. Some
files on ROOT are cloud-only (iCloud): reading one starts a download and can
hang, so the map script skipped them by their `dataless` flag.

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

From `ducklearn`, `Tomosius/sqlearn`, `sqlearn_000` and sqlearn v0.4, oldest
first. Evidence, not decisions; the decisions are made in issue #8.

- **How fit runs.** Every attempt learned a later step's statistics from the
  raw or stage input, so `Impute` then `Scale` scaled un-imputed data. The
  defect was designed in from the first document, diagnosed in writing on
  17 March, and kept; `Tomosius/sqlearn` substituted only non-learning steps
  into later aggregates, and v0.4 lost even that. The boundary rule has to be
  "a learning step reads a value an earlier step changed", covering set
  queries (`DISTINCT`) as well as aggregates. A staged fit can still be one
  query with `WITH` clauses (checked on DuckDB 2.0.0; the idea was on file
  since March). Fit must see the same row-level steps as transform, through
  one composer, and nothing in transform may query data. Per-fold
  `FILTER (WHERE fold != k)` aggregates give every cross-validation fold's
  statistics in one scan, equal to the subset's for `AVG`, `STDDEV_POP`,
  `MEDIAN`, `QUANTILE_CONT` and `MODE … ORDER BY` (checked on DuckDB 2.0.0).
- **Learned state.** Normally Python values inlined as SQL literals, saved as
  JSON (v0.4, `sqlearn_000`) or pickle only (`Tomosius/sqlearn`). Failures:
  `None` meaning both "not fitted" and "learned NULL", keys split on `__`
  (where `Tomosius/sqlearn`'s `(step, parameter)` tuples worked), stale keys
  after a refit, selectors and custom classes that could not be saved, float
  literals never checked. Learned state as a relation was designed once, for
  cross-validation: a `stats` CTE joined with `CROSS JOIN`, and per-fold
  DuckDB tables as a cache.
- **SQL representation.** Every attempt used sqlglot, chosen for
  "multi-database from day one". Costs: version pins, type-checker noise, AST
  aliasing bugs, a dialect that changed NULL ordering. Portability was never
  tested beyond parsing.
- **Validation.** No attempt ever compared a whole pipeline with scikit-learn's
  (`Pipeline([SimpleImputer(), StandardScaler()])` would have caught the fit
  defect every time). Early attempts used scikit-learn as the reference with a
  fixed tolerance; v0.4 and `sqlearn_000` wrote a strong method (exact
  references, bounds set from measurement) and never enforced it. Parity
  tests were few, hand-tuned, sometimes correlation-only, sometimes skipped,
  and loosened to hide known mismatches. Tests that assert a known divergence
  with its reason, and snapshots that fail when missing, are worth keeping.
- **API.** `ducklearn` and `Tomosius/sqlearn` kept scikit-learn's names with
  `get_params`, `set_params` and `clone`; v0.4 and `sqlearn_000` renamed them
  and then added bridges back. ADR 0003 stands. Every attempt took `y` as a
  column name and `fit` a data source, and never excluded the target from the
  default columns: departures that need an ADR.
- **Process.** Bursts of building, then stalls. Plans, standards, skills and
  tooling outgrew the product; status was kept by hand in several places and
  drifted. A separate review sweep after a burst found real bugs every time it
  was run. Docs with hand-typed numbers were wrong.

---
type: question
tags: [earlier-attempts, library-core, tracking, plan]
summary: "Plan and progress for absorbing every earlier sqlearn attempt: the numbered steps, each attempt's status, how to resume in a new session, and what is known so far."
related: [docs/architecture/overview.md, docs/questions/archived/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# Earlier attempts

sqlearn was attempted many times before this repository. Each attempt is read
for what is worth keeping and what went wrong, so that the library core (part
3.2 of [the overview](../../../architecture/overview.md)) is designed with those
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
- [x] 6. Absorb the April planning repo,
  `sqlearn-ecosystem_old/sqlearn-private`, without `_old_sqlearn` (full).
- [x] 7. Absorb the war room, `sqlearn-ecosystem/sqlearn-private` (full).
- [x] 8. Absorb the six commits `sqlearn-ecosystem/sqlearn` has beyond
  `sqlearn_000` (light).
- [x] 9. Absorb `sql_learn_test` (light, two agents).
- [x] 10. Absorb `sql_learn_27.08.2026` and `sql_learn` (light).
- [x] 11. Absorb `sqlearn` of September and October (light, two agents).
- [x] 12. Combine **What we know so far** into answers for the four open
  questions; this closes the drain and unblocks the decisions in issue #8.

## Attempts

| Attempt | Source | Tier | Status | Review | Not read |
|---|---|---|---|---|---|
| `sqlearn_000` | GitHub `glaucis/sqlearn_000` | full | merged | [review](sqlearn_000/review.md) | `sqlearn-private`, which it quotes |
| sqlearn v0.4 | ROOT `sqlearn-ecosystem_old/sqlearn` (Apr 10–12, 236 commits) | full | merged | [review](sqlearn-v04/review.md), [exploration helpers](sqlearn-v04/exploration-helpers.md), [batch notes](sqlearn-v04/notes/) | two standards files; long plans read by heading; 139 test files skimmed |
| `ducklearn` | ROOT `ducklearn` (Mar 13, no git): 14 design docs | light | merged | [review](ducklearn/review.md), [batch notes](ducklearn/notes/) | |
| `Tomosius/sqlearn` | ROOT `sqlearn-desktop` (no git, 378 files) and ROOT `test/sqlearn` (GitHub `Tomosius/sqlearn`, Mar 13 – Apr 9, 271 commits) | full | merged | [review](tomosius-sqlearn/review.md), [batch notes](tomosius-sqlearn/notes/) | `test/sqlearn`'s 297 cloud-only files; it shares 92% of its local files with `sqlearn-desktop` |
| April planning repo | ROOT `sqlearn-ecosystem_old/sqlearn-private` (GitHub `glaucis/sqlearn-private`, Apr 9–24, 593 commits), 411 files | full | merged | [review](sqlearn-private-april/review.md), [batch notes](sqlearn-private-april/notes/) | `_old_sqlearn/`: an exact copy of v0.4 |
| War room | ROOT `sqlearn-ecosystem/sqlearn-private` (GitHub `glaucis/sqlearn-private`, Apr 26 – Jun 13, 410 commits), 218 docs | full | merged | [review](sqlearn-private-war-room/review.md), [batch notes](sqlearn-private-war-room/notes/) | most ideas and long rules skimmed |
| `sqlearn_000`, later commits | ROOT `sqlearn-ecosystem/sqlearn` (same first commit, 82 commits against 76) | light | merged | [review, Later commits](sqlearn_000/review.md#later-commits) | the 76 commits already reviewed |
| `sql_learn_test` | ROOT `sql_learn_test` (Aug 21–24, 59 commits), 85 files | light | merged | [review](sql_learn_test/review.md), [batch notes](sql_learn_test/notes/) | agent-only syntheses and most research reports read in part |
| `sql_learn` | ROOT `sql_learn_27.08.2026` (Aug 26, 47 commits, 8 files) and ROOT `sql_learn` (Aug 27–30, 68 commits, 75 files), separate histories | light | merged | [review](sql_learn/review.md), [batch notes](sql_learn/notes/) | task-tracker scripts and half the agent files skimmed |
| `sqlearn`, autumn | ROOT `sqlearn` (Sep 30 – Oct 4, 316 commits), 270 files, mostly agent records | light | merged | [review](sqlearn-autumn/review.md), [batch notes](sqlearn-autumn/notes/) | most records and agent files skimmed |

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

From all ten attempts: `ducklearn`, `Tomosius/sqlearn`, sqlearn v0.4, the April
planning repo, `sqlearn_000`, the war room, `sql_learn_test`, the two
`sql_learn` restarts and the autumn `sqlearn`, oldest first. Evidence, not
decisions; the decisions are made in issue #8. DuckDB facts are checked on
2.0.0 and listed in each review.

- **How fit runs.** Every attempt that designed a fit learned a later step's
  statistics from the raw or stage input, so `Impute` then `Scale` scaled
  un-imputed data. It was designed in from the first document, diagnosed in
  writing on 17 March and kept; the April repo wrote it down as the rule and
  tested for it; the war room kept it (standard deviation 1.6997 its way,
  1.4720 staged). `Tomosius/sqlearn` substituted only non-learning steps into
  later aggregates, and v0.4 lost even that. The boundary rule has to be "a
  learning step reads a value an earlier step changed", covering set queries
  (`DISTINCT`) as well as aggregates. A staged fit can be one query: each
  stage's learned values in a `WITH` clause gives scikit-learn's answer, and
  DuckDB materialises a stage read more than once (24 stages in 0.01 s).
  Never mark the stages `NOT MATERIALIZED` (out of memory at 12) and never
  chain lazy relation objects (the work doubles with each step). Row filters
  must reach fit as they reach transform (the war room's rule), `where=` on a
  learning step means fit scope (`FILTER (WHERE …)`), and nothing in transform
  may query data. Per-fold `FILTER (WHERE fold != k)` aggregates give every
  cross-validation fold's statistics in one scan, equal to the subset's for
  `AVG`, `STDDEV_POP`, `MEDIAN`, `QUANTILE_CONT` and `MODE … ORDER BY`.
- **Learned state.** Usually Python values inlined as SQL literals, saved as
  JSON or pickle. Failures: `None` meaning both "not fitted" and "learned
  NULL" (the war room first kept them apart, with `NotLearnedError`); keys
  split on `__` (structured `(step, parameter)` keys worked); stale keys after
  a refit; selectors and custom classes that could not be saved; folds
  overwriting state on shared step objects, so fitted state must live apart
  from the steps; lazy relations as state, which silently refit; float
  literals never checked (DuckDB reads `44.2` as `DECIMAL(3,1)`, and `inf` and
  `nan` are not literals). A `DECIMAL` precision mode does not work: DuckDB's
  aggregates of `DECIMAL` return `DOUBLE`. With several threads DuckDB's sums,
  means and standard deviations differ in the last digits from run to run;
  at one thread they repeat exactly. No attempt handled NaN, which DuckDB
  keeps apart from NULL: NaN equals NaN, sorts above every number, makes `AVG`
  NaN and `MEDIAN` silently wrong, and passes through `COALESCE`.
- **SQL representation.** Most attempts used sqlglot, chosen for
  "multi-database from day one"; `sql_learn_test` rejected it and the
  restarts after it used plain SQL. Costs: version pins, type-checker noise,
  AST aliasing bugs, a dialect that changed NULL ordering. Portability was
  never tested beyond parsing; two repositories admit transpilation is
  "syntactic, not semantic" (`STDDEV` is sample in DuckDB, population in
  MySQL). The war room's portable rewrites gave wrong answers with NULLs. The
  only multi-engine designs reach other engines natively or through DuckDB
  `ATTACH`; none ran. Identifiers need quoting: DuckDB lists its own keywords
  (`duckdb_keywords()`, 75 reserved), and hand-typed lists drifted.
- **Validation.** No attempt ever compared a whole pipeline with scikit-learn's
  (`Pipeline([SimpleImputer(), StandardScaler()])` would have caught the fit
  defect every time); `sql_learn_test` named the gap: parity per method can
  pass while `fit_transform` is wrong. Two methods compete: exact references
  (mpmath or `Decimal` at 50 digits, `Fraction`) with error bounds measured in
  ULPs (v0.4, April repo, `sqlearn_000`, the autumn `sqlearn`'s `sweep.py`),
  and a live scikit-learn as the oracle with tolerances measured from noise
  (`sql_learn_test`); they answer different questions and the strongest
  designs used both, with an `anomaly` flag for a reference library that
  misses its own precision. Neither was ever enforced as a gate. Parity tests
  were few, hand-tuned, sometimes correlation-only, sometimes skipped, and
  loosened to hide known mismatches. Useful rules: datasets bundled or
  generated, never downloaded; small and large fixtures, because a `ddof`
  error is 15% at n = 4 and 5e-6 at n = 100,000; every run on small, medium
  and large data; tests that assert a known divergence with its reason;
  snapshots that fail when missing; a hash gate against quietly weakened
  tests; invariants rather than second implementations as oracles; a reference
  that is truly independent (`statistics.NormalDist` is the same algorithm as
  the AS 241 it would check). DuckDB has no `erf` and no normal quantile.
- **API.** `ducklearn`, `Tomosius/sqlearn` and `sql_learn_test` kept
  scikit-learn's names, with `get_params`, `set_params` and `clone`;
  `sql_learn_test` made the API identical to scikit-learn's and the live
  scikit-learn its oracle. The April repo declared `learn`/`apply`
  "settled", v0.4, `sqlearn_000` and the war room used them, and bridges back
  were added. ADR 0003 stands. Most attempts took `y` as a column name and
  `fit` a data source, and none excluded the target from the default columns:
  departures that need an ADR.
- **Process.** Of about 2,000 commits across the ten attempts, a minority
  touched library code; four repositories wrote none (the April repo 593
  commits, the war room 410, the autumn `sqlearn` 316, both `sql_learn`
  restarts). Bursts, then stalls; no attempt recorded why it stopped. Plans,
  standards, skills, agent rosters and trackers outgrew the product; status
  kept by hand in several places drifted; scope swung by conversation.
  Deterministic tools (a checker script, rumdl, typos, hash gates) stopped
  drift where agent reviewers and prose rules had not. A separate review sweep
  after a burst of building found real bugs every time it was run.

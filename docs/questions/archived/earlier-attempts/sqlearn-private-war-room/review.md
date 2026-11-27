---
type: question
tags: [earlier-attempts, library-core, multi-engine, fit, specs]
summary: "Lessons from the war room (glaucis/sqlearn-private, 26 April – 13 June 2026): a multi-engine redesign specified in full and never coded; the fit defect stayed, NaN went unnoticed, and filters finally reached fit."
related: [docs/questions/archived/earlier-attempts/README.md, docs/questions/archived/earlier-attempts/sqlearn_000/review.md, docs/questions/archived/earlier-attempts/sqlearn-private-april/review.md, docs/questions/archived/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# What does the war room teach the library core?

The war room is GitHub `glaucis/sqlearn-private` from 26 April to 13 June
2026 (ROOT `sqlearn-ecosystem/sqlearn-private`, 410 commits): the specs,
rules and plans that directed [`sqlearn_000`](../sqlearn_000/review.md) and,
after 30 April, replaced it. Five batches read it; the notes, with citations
as `OLD:path:Lnn`, are in [notes/](notes/): [direction](notes/A-direction.md),
[core specs](notes/B-core-specs.md), [step specs](notes/C-step-specs.md),
[plans](notes/D-plans.md) and
[rules, ideas and process](notes/E-rules-ideas-process.md). Some long rules
and most ideas were skimmed; the checklists say which.

## Summary

- **A redesign widened the scope and the code was wiped.** A conversation on
  29–30 April moved from DuckDB only to many SQL engines; `sqlearn_000`'s code
  was deleted (`ff880ba`) and its four open bug reports were marked superseded,
  not fixed
  (`OLD:plans/archived/2026-04-30-sqlearn-multi-dialect-redesign.md:L3-L5`).
  Scope then swung from four engines to DuckDB and SQLite (3 May) to five with
  ClickHouse (7 June), none of it recorded as a decision.
- **No library code was written.** Twenty-four plans (17,600 lines) produced
  specification edits; the repository has no `src/`. Of 410 commits, about
  119 were process machinery; 125 fell on 2 May, none between 8 May and
  6 June. Work stopped on 13 June with no focus and eight commits unpushed;
  nothing records a decision to stop.
- **The fit defect stayed.** A layer ends only at a step whose output schema
  depends on what it learned; Impute and Scale are both "static", so their
  statistics are batched in one query over the layer's input
  (`OLD:projects/sqlearn/core/pipeline.md:L156-L170`). Measured on DuckDB 2.0.0
  by the batch: standard deviation 1.6997 the specs' way, 1.4720 staged.
  OneHot's `DISTINCT` runs in the same batch and reads un-imputed values.
- **Row filters finally reach fit.** Filter, DropNulls, Distinct and `where=`
  fold into the `WHERE` of every later step's input at fit and at transform
  (`OLD:projects/sqlearn/core/pipeline.md:L236-L319`), with a framework row key
  giving `Distinct` a deterministic survivor.
- **"Not learned" and "learned NULL" are apart for the first time:** reading
  a value before fit raises `NotLearnedError`; a learned NULL is a value.
  State still lives on the step objects, routed back by `id(step)`.
- **Aggregates became steps.** Thirteen aggregate specs (Mean, Median, Mode,
  Quantile, Std, Var, Corr, DistinctValues and others), each with one learned
  value; scalers, `Impute(value=Mean())` and encoders are built from them as
  "substeps". Median and Quantile use `QUANTILE_CONT`, Mode uses
  `MODE(x ORDER BY x)`, Std and Var the population forms: three of the known
  departures fixed.
- **Multi-engine as specified:** a per-step table of native, rewritten or
  aliased SQL for each engine, and a rule refusing aliases whose meaning
  differs between engines. The war room wrote down that sqlglot translates
  syntax only. DuckDB became an optional extra with a fallback to Python's
  `sqlite3`, against this repository's ADRs. Nothing ran on any engine.
- **The API renaming stayed** (`learn`, `apply`, `learn_apply`); `get_params`,
  `set_params` and `clone` were removed and there is no separate `y`.

## DuckDB facts, checked on 2.0.0

| Behaviour | Result | Consequence |
|---|---|---|
| `STDDEV(x)` on 1, 2, 3, 4 | 1.291 (sample) | `STDDEV` means sample in DuckDB and population in MySQL: refuse the bare name |
| `AVG`, `MAX` with one NaN | NaN | one NaN poisons a learned mean |
| `MEDIAN` of 1, NaN, 3 | 3.0 | NaN sorts as the largest value: a wrong median, not an error |
| `NaN IS NULL`, `COALESCE(NaN, 0)` | false, NaN | imputation does not touch NaN |
| `1.0 / 0`, `0.0 / 0`, `(x − mean) / 0` | `inf`, NaN, NaN | a constant column gives NaN, not NULL or scikit-learn's 0 |
| `list_indexof(['a','b'], 'z')` | NULL | an "unseen category" error built on 0 never fires |
| `42.5` as a literal | `DECIMAL(3,1)` | learned floats need an explicit literal rule |

The batch also ran the specs' portable rewrites ("low nodes") on DuckDB: with
NULLs present the rewritten Median gave 3.5 against 2.5, Quantile 2.25
against 1.7, Corr −0.06 against 0.99, and the one-pass Std 0.0 against 0.816
at magnitude 1e9. Portable SQL needs the same parity tests as native SQL.

## New against earlier reviews

- **NaN was never considered** in any spec: NaN and NULL are different in
  DuckDB, and the specs treat NaN as ordinary data.
- **Filters with one meaning** at fit and transform, and a row key; no page
  mentions `y` or the target, so alignment is still open.
- **Unseen categories default to an error** in OneHot and Ordinal (April gave
  zeros and NULL), and NULL is a OneHot category.
- **"Static" changed meaning** again: now "the SQL needs no data", the
  opposite of April's usage. Mean is static in one spec and dynamic in
  another; `Std` is sample in one file and population in three.
- **A deterministic checker script** (`40d02de`, 7 June) ended the drift that
  six rounds of agent verifiers had not.
- **Rule revisions:** 7 of 11 renamed or narrowed a "lock" made days earlier.
  One found a real bug: `Impute(value="mean")` silently turned a literal
  category into an aggregate.
- **An idea that would leak:** the search design's Mode A filters by fold id
  after statistics are learned once, so validation rows feed training
  statistics (inference, `OLD:ideas/sq-search-engines.md`).

## Worth keeping

- Aggregates as steps with one learned value each, and steps parameterised by
  them (`Scale(center=Mean())`).
- The alias-rejection rule and its table of names that differ between
  engines (`STDDEV`, `VARIANCE`, bare `MODE`).
- Filters that apply at fit and transform alike, with a row key, so that
  statistics come from the rows the transform keeps.
- `NotLearnedError` apart from a learned NULL.
- Per-aggregate rules for empty input, all NULL and one row; "defaults
  divergence" lists against scikit-learn.
- Rules: honest names, explicit defaults, error messages that teach, JSON not
  pickle with a round-trip test, a precision table by operation, and a written
  reason before any tolerance is loosened.
- A deterministic checker rather than agent reviewers for drift between
  documents.

## Guard against

Widening scope by conversation, without an ADR; specifications ahead of any
code; locking API shapes before code exists and then renaming them; plans of
17,600 lines for document edits; status in several places (an 80 KB TODO, a
42 KB skill loaded at every session); agent fan-out used to detect drift; a
project that stops without a recorded decision.

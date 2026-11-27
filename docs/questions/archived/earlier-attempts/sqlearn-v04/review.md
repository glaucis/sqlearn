---
type: question
tags: [earlier-attempts, library-core, fit, learned-state, sqlglot, validation]
summary: "Lessons from the earlier sqlearn v0.4 for the library core: fit read the wrong data, state was stringly typed, sqlglot cost more than it gave, validation was mostly unenforced."
related: [docs/architecture/overview.md, docs/questions/archived/earlier-attempts/sqlearn_000/review.md, docs/questions/archived/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md, docs/questions/archived/earlier-attempts/sqlearn-v04/exploration-helpers.md]
---
# What does sqlearn v0.4 teach the library core?

The earlier sqlearn reached v0.4 in April 2026: 236 commits in three days,
about 22k lines of source, 89 transformer files and 2,934 tests. It was read
from a local copy (`sqlearn-ecosystem_old/sqlearn`, called OLD below) in six
batches; every file outside generated folders (`.venv`, `mutants/`,
`.hypothesis`, caches, `docs/_build`) was covered, with the per-transformer
test files skimmed after a representative sample was read in full. Citations
are `OLD:path:Lnn`. Inference is marked as such. DuckDB behaviour was rechecked
on DuckDB 2.0.0 on 2026-11-03.

This review sits beside [the sqlearn_000 review](../sqlearn_000/review.md). The
two repositories made the same central mistakes independently, which makes those
lessons firmer.

## Summary

- **Fit learned from the wrong data, again.** Within a stage, every step's
  aggregates read the stage's input, so `Impute` then `Scale` learns the
  standard deviation of un-imputed data. A snapshot test locks in the wrong
  value (5.0 where scikit-learn gives about 4.08), and a parity test was
  weakened to `sql() is not None` rather than fixed
  (`OLD:tests/snapshots/impute_then_scale.sql`,
  `OLD:tests/transforms/scalers/test_scalers_deep.py:L109-L113`).
- **Fit leaked into transform.** TargetEncode ran its own SQL inside
  `expressions()` and fell back silently to the global mean after a reload;
  PowerScale computed its lambda lazily, and `to_config()` called `sql()` with
  errors suppressed to fill it in
  (`OLD:src/sqlearn/core/pipeline.py:L253-L258`).
- **Learned state was flat string-keyed dicts** (`price__mean`,
  `{col}__cat__{v}__mean`), routed by splitting on `__`, inlined as SQL
  literals and saved as JSON. Selectors, nested steps, dates and custom classes
  could not be saved (inference from the code).
- **sqlglot was the IR and cost more than it gave**: a pin below v30 after v30
  produced 292 type errors, relaxed type checking, an AST-aliasing bug class,
  and "six dialects" checked by parsing only.
- **The API departed from scikit-learn on purpose** (`learn`/`apply`, no
  `get_params`) and kept being pulled back (`as_sklearn()`, `from_sklearn()`).
- **Validation looked strong and was not**: about 95 of 2,750 test functions
  compared against a reference; the real-data ones skipped silently in CI; some
  comparisons were tautological or correlation-only.
- **Process outran product**: about 12k lines of plans and standards, one ADR
  about the agent workflow itself, and almost no plan checkbox ever ticked.

## Fit execution

How it ran (`OLD:src/sqlearn/compiler/compile.py:L64-L114`,
`OLD:src/sqlearn/compiler/layers.py:L153-L230`): one `DESCRIBE`; then per
"layer" one batched aggregate `SELECT` with aliases `step__param`, one
`SELECT DISTINCT` per learned set, and a `CREATE OR REPLACE TEMP VIEW` before
the next layer. A layer is cut only after a step that both learns and changes
the schema (`layers.py:L215-L224`).

What went wrong:

- `discover()` receives column names, never the upstream expressions, so a
  step cannot see what earlier steps in its layer did
  (`OLD:src/sqlearn/core/transformer.py:L210-L236`).
- Filter, `where=`, `drop_null=` and every whole-query step are ignored while
  fitting, so statistics come from rows the transform later drops
  (`layers.py:L179-L224`).
- From the third layer on, the view builder replays every step from the start
  over the previous view, applying earlier steps twice (inference; no test runs
  three layers, `compile.py:L272-L284`).
- Fit-time views and `apply`/`sql()` use two different composers that disagree
  (`compile.py:L240-L287` against `pipeline.py:L615-L725`).
- View names are fixed, global and never dropped; a second fit replaces a view
  an earlier fitted TargetEncode still reads (inference).

What this suggests for [fit-execution-model.md](../../fit-execution-model.md):

- The stage boundary rule must be "a learning step reads a value an earlier
  step changed", not "a step changed the schema". Both earlier repos got this
  wrong.
- A staged fit can still be one query. Each step's learned values form a one-row
  relation in a `WITH` clause, and a later step's aggregate reads the earlier
  step's expression over it. Checked on DuckDB 2.0.0, this gives 4.08,
  scikit-learn's answer:

  ```sql
  WITH s1 AS (SELECT MEDIAN(x) AS m FROM t)
  SELECT STDDEV_POP(COALESCE(x, s1.m)) FROM t, s1
  ```

  Cost on large data and deep pipelines is unmeasured.
- Fit must see the same row-level steps as transform, through one composer.
- Every statistic a step needs is computed in fit, by the fit plan. Nothing in
  the transform path may query data.

## Learned state

- State lived in `_params`, `_sets`, `_resolved_columns` and `_fitted` on each
  step (`transformer.py:L176-L179`), with ad hoc extras (`_learn_source`,
  `_y_column` set inside `discover()`).
- Values were DuckDB's Python values, inlined as literals. Nobody tested
  whether a float survives the round trip to a SQL literal (the same gap as
  sqlearn_000).
- CountEncode puts its whole category map in a `CASE`; the spec accepted this
  (`OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2103-L2123`).
  Keeping learned state in DuckDB tables was never considered (inference: no
  trace of it in the docs).
- Sentinels went wrong both ways: `()` was falsy, so `None` was needed
  (`OLD:TODO.md:L95-L109`); sqlearn_000 had `None` meaning both "not fitted" and
  "learned NULL".
- Saving found classes by name in `dir(sqlearn)`, so custom steps could not be
  loaded (`OLD:src/sqlearn/core/config.py:L39-L48`, `L166-L168`).

The `WITH`-clause route above treats learned state as a relation. That points
towards keeping it in DuckDB (or at least representing it as rows) rather than
as Python literals, at least for large maps (inference; the decision is the
core spec's).

## SQL representation and sqlglot

For [multi-engine-support.md](../../../multi-engine-support.md):

- ADR-001 chose sqlglot because "multi-database support is free"
  (`OLD:docs/decisions/ADR-001-sqlglot-ast.md:L43-L49`). That premise does not
  hold here: DuckDB is the only runtime dependency and other engines are later
  work.
- Costs: the `<30` pin and 292 type errors (`ADR-001:L52-L62`); pyright checks
  relaxed for its stubs (`OLD:pyproject.toml:L140-L147`); AST nodes reused
  without `.copy()` corrupted trees in three transformers
  (`OLD:TODO.md:L217-L270`); aggregates built as `exp.Anonymous("AVG")`, which
  sqlglot cannot rewrite per dialect (inference).
- The "no f-string SQL" rule was broken by the fixes themselves: TargetEncode,
  `connect()` (an injection) and paths in `read_parquet('…')`; the injection
  lint `S608` was ignored globally (`OLD:pyproject.toml:L110`).
- The SQL relied on DuckDB features anyway (`HISTOGRAM`, `USING SAMPLE`,
  `IGNORE NULLS`), and no other engine ever ran it.
- What sqlglot did give: composition by substitution, quoting and pretty
  snapshots. A small internal representation of the core's own (expressions per
  column, a source, learned-value references) would give the first two and
  could be rendered to sqlglot later if another engine is ever added
  (inference).

## API and scikit-learn conformance

For [scikit-learn-api-survey.md](../../../scikit-learn-api-survey.md):

- ADR-002 renamed `fit`/`transform` to `learn`/`apply`, dropped `get_params`,
  `set_params` and `fit_transform`, and made `learn()` return a copy
  (`OLD:docs/decisions/ADR-002-learn-apply-naming.md:L14-L44`). There were no
  users to be "surprised" (every release is "Unreleased"). Parameters stored
  as `_name` forced serialisation to guess attribute names
  (`config.py:L152-L158`). This supports the new ADR 0003 as it stands.
- `Columns` (its ColumnTransformer) could not work in a pipeline: resolution
  raised and learned values never reached the branches
  (`OLD:src/sqlearn/core/columns.py:L54`, `L88-L171`).
- Fit mutated the user's original steps despite promising not to
  (`transformer.py:L340-L342`).
- Universal parameters (`where`, `drop_null`, `group_by`, `order_by`, `dtype`
  on every step) were half built: `group_by` and `order_by` were stored and
  ignored. sqlearn_000 had the same.
- The target column was not excluded from default selectors (inference).

## Validation

For [validation-method.md](../../../validation-method.md):

- **Written policy, good:** an exact reference (`Decimal` at 50 digits), every
  library ranked by distance from it, tolerance one decade above the worst
  measured difference, and a divergence register
  (`OLD:docs/execution-standards.md:L478-L520`). Only Scale was ever measured
  this way, by hand (`OLD:tests/PRECISION.md:L8-L27`): DuckDB's parallel
  summation gave about 2.7e-15 error in the mean and up to 1.42e-12 in z-scores
  on 20k rows, and numpy was closer to the truth.
- **Practice, weak:**
  - Hand-picked tolerances (`rtol=1e-14` in 183 asserts, `atol=1e-10` in 164),
    loosened after failures.
  - PowerScale and QuantileScale passed if correlation with scikit-learn
    exceeded 0.90 or 0.95; TargetEncode was "N/A" while broken
    (`OLD:REVIEW.md:L67-L77`).
  - Normality "comparisons" called scipy on both sides.
  - Snapshots wrote themselves when missing and so passed.
  - Hypothesis ignored its generated input.
  - Real-data parity tests skipped when the downloaded files were absent,
    which in CI was always (inference).
  - The verification ledger had one feature (Scale) with blank test paths.
- **Found by review, not tests:** three agent reviews found six bugs and five
  warnings after 2,278 tests passed (`OLD:TODO.md:L1-L3`).
- **Network:** datasets were downloaded (`OLD:datasets/download.py`), which
  ADR 0006 now forbids. scikit-learn's `load_iris`, `load_wine`,
  `load_diabetes` and `load_breast_cancer` ship in the wheel;
  `fetch_california_housing` downloads.

Worth keeping: the written policy, implemented as code; a divergence register;
absolute tolerance near zero and per-dtype bounds; seeded synthetic Parquet
plus an adversarial set (constant column, single row, all NULL, 1e15 and
1e-15, large mean with small variance, ties); a parity job that fails, not
skips, when a reference is missing; snapshots that fail when absent; a ledger
generated from the tests; mutation testing on a schedule.

## DuckDB facts, checked on 2.0.0

| Behaviour | Result | Consequence |
|---|---|---|
| `QUANTILE(x, 0.5)` on 1, 2, 3, 4 | 2.0 (discrete) | scikit-learn interpolates (2.5): use `QUANTILE_CONT` |
| `MEDIAN(x)` on the same | 2.5 | continuous; OLD's RobustScale mixed the two |
| `LEAST(NULL, 5)`, `GREATEST(NULL, 5)` | 5 | clipping turns NULL into the bound; guard it |
| `MODE(x)` vs `MODE(x ORDER BY x)` on 3, 1, 3, 1, 2 | 3 vs 1 | only the ordered form gives scikit-learn's smallest tie |
| `ROUND(2.5)`, `ROUND(-2.5)` | 3, -3 | numpy rounds half to even: `ROUND_EVEN` |
| `LN(0)`, `LN(-1)`, `SQRT(-1)` | `-inf`, NaN, NaN | no error is raised; guard the domain |
| `ARRAY_AGG` over no rows | NULL | wrap in `COALESCE(…, [])` |

## Transformer lessons

Departures from scikit-learn found in OLD's transformers, as a checklist for
the new ones (`OLD:src/sqlearn/transforms/`, details in the batch notes):

- RobustScale emits 0 when the IQR is 0; scikit-learn uses scale 1.
- Scale, MinMax and MaxAbs turn NULL into 0 on a constant column.
- NULL falls into the `ELSE` bucket in Bin and QuantileScale, and becomes 0 in
  Binarize and IsWeekend.
- MissingIndicator flags every column, where scikit-learn's default flags only
  those missing in fit.
- Normalize gives NULL for a zero-norm row; scikit-learn gives 0.
- PowerScale picks lambda by a skewness grid, not maximum likelihood.
- FrequencyEncode and GroupAggregate compute their statistics over the data
  being transformed, with nothing learned in fit.
- Window steps order by columns with no tiebreak, so ties are
  nondeterministic; `ROW_NUMBER() OVER ()` was injected into every query as a
  row id.

Two kinds of step: OLD needed a second hook, `query(input)`, that wraps the
previous step as a subquery, for windows, filters, sorting, sampling,
deduplication, joins and renames. Row-expression steps and whole-query steps
need to be distinct kinds in the new core, and row-count-changing steps need a
rule for when they apply (fit only, or fit and transform) and for keeping `y`
aligned.

SQL formulations worth keeping: `STDDEV_POP` and `VAR_POP` (scikit-learn's
ddof=0), `x / NULLIF(scale, 0)` division guards, the piecewise Yeo-Johnson and
Box-Cox `CASE`, `HISTOGRAM(col)` for category counts, forward and backward fill
with `IGNORE NULLS`, `TABLESAMPLE BERNOULLI(p PERCENT) REPEATABLE (seed)`, and
`SIN`/`COS` over a period for cyclical features.

## Designs worth keeping

- `expressions()` returns only the columns a step changes; the rest pass
  through. Make dropping explicit rather than implied by omission (several
  steps had to re-emit a column to keep it).
- Independent aggregates batched into one `SELECT`, with structured rather
  than `__`-split namespacing.
- Static/dynamic classification with "if it cannot be proved static, treat it
  as dynamic" (`OLD:docs/architecture/compiler.md:L311-L322`).
- The schema threaded through `output_schema()` so selectors resolve after
  OneHot; type-category selectors and `matching(glob)`.
- Validating the training schema on apply (`pipeline.py:L158-L217`).
- `sql()` that needs no data, with an `__input__` placeholder for the source.
- Versioned JSON config with the input schema, no pickle.
- Result objects with `__str__`, `_repr_html_` and `to_dict()`, no plotting
  dependency.

## Process lessons

The new [workflow](../../../../architecture/workflow.md) already covers most of
these; they are listed so the core's plan can be checked against them.

- Plans contained their deliverables verbatim (a 1,815-line plan for a
  640-line document) and nobody updated them (2 of about 190 checkboxes).
- A whole effort (about 5k lines of plan) went into standards for the agents'
  own workflow, written the same day v0.4 shipped.
- Specs and plans lived in a gitignored folder, so they left no history.
- Docs contradicted measurements: "under 10 s" for deep analysis on 1M rows,
  against a measured 39 s (`OLD:docs/benchmarks/v0.4.0-report.md:L88-L92`).
- Four overlapping Opus agents each loaded a 425-line standards skill.
- ADR-008 rejected `sq.connect()`; v0.3 shipped it.

## Coverage

Six batches: design and decisions (23 files), compiler and core (19),
transformers (89), validation and tests (38 read, 139 skimmed), process (37)
and exploration helpers (40, reported in
[exploration-helpers.md](exploration-helpers.md)). Two process files
(`python-standards.md`, `documentation-standards.md`) were not read, and the
long numbered plans were read by heading.

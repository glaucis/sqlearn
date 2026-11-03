---
type: question
tags: [sqlearn-000, earlier-attempts, library-core, fit, sqlglot, validation, review]
summary: "Review of the earlier sqlearn_000 repository: its architecture, what to keep, what went wrong, and what its evidence says about the four open library-core questions."
related: [docs/questions/scikit-learn-api-survey.md, docs/questions/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/validation-method.md, docs/architecture/overview.md]
---

# What does `sqlearn_000` teach the library core?

`sqlearn_000` (GitHub `glaucis/sqlearn_000`, private, MIT) is one of the earlier
attempts named in [overview §5](../../../architecture/overview.md). This page
reads it from its source, tests, docs and history, at commit `a4fc0d6` (76
commits, 2026-04-28 to 2026-04-30). Citations take the form
`sqlearn_000:path:Lnn` or a short SHA. The specs it implemented lived in a
separate repository, `../sqlearn-private/` (`sqlearn_000:CLAUDE.md:L3`), which
this review did not read; claims about those specs come only from what
`sqlearn_000` quotes. Inference is marked as such.

## Summary

- **Scope reached:** foundation (errors, `Step`, DuckDB backend, composer,
  `Pipeline` with JSON save and load) and eleven leaf steps: seven aggregates
  (`Mean`, `Std`, `Min`, `Max`, `Median`, `Mode`, `Distinct`), three
  row-wise transforms (`Log`, `Sqrt`, `Abs`) and `MissingIndicator`. No
  scaler, imputer or encoder that consumes a learned value was ever built
  (`sqlearn_000:TODO.md`, "Phase 3"), so the fit-then-substitute design was
  never tried on a real step.
- **Shape:** every step builds a sqlglot AST; aggregates are steps whose
  scalar result is cached on `result_`; the learn pass runs one query per
  aggregate, all against the raw input; the apply pass nests one `SELECT` per
  step.
- **Defects visible in the code:** a later step's statistics are learned
  from the raw input, not from the previous step's output; multi-column and
  grouped aggregates cannot be learned; transforms drop every column they do
  not touch; `None` is both "not fitted" and "learned NULL"; `Log` raises on
  non-positive input against its spec.
- **Ended** two days in, with its open reports marked superseded by a
  "multi-dialect redesign" plan in the private repository (`a4fc0d6`).
- **Worth keeping:** exact references (`mpmath` at 50 digits, `Fraction` for
  order statistics), ULP-based error with a declared bound per step,
  real-dataset comparison against several libraries, the DuckDB and sqlglot
  gotchas in `LESSONS.md`, and several verified SQL formulations.
- **Dependencies:** `sqlglot` and `numpy` at runtime besides `duckdb`;
  `numpy` was never imported by the library.

## Architecture

**Steps.** `Step` is an abstract class with one abstract method,
`apply(table) -> sqlglot Expression`
(`sqlearn_000:src/sqlearn/core/step.py:L321`). Each subclass declares
`_classification` as `"static"` (no learn pass) or `"dynamic"`, checked at class
creation (`step.py:L236-L262`). Every step takes the same "universal"
parameters: `columns` first, then keyword-only `where`, `group_by`, `order_by`,
`drop_nulls`, `dtype`, `out_column` (`step.py:L264-L305`). The constructor
normalises `columns` into the attribute `columns_` (`step.py:L299`): a
constructor argument stored under a trailing-underscore, fitted-looking name.
Names are verbs and statistics (`Log`, `Mean`), not scikit-learn's
(`sqlearn_000:CLAUDE.md:L59`).

**Aggregates are steps.** `Aggregate(Step)` fixes `_classification =
"dynamic"` and adds `result_`, which starts as `None`
(`step.py:L451-L506`). `is_fitted` is `result_ is not None`
(`step.py:L508-L521`). A consuming step was to hold an aggregate as a
parameter, for example `Impute("price", value=Mean("price"))`
(`sqlearn_000:src/sqlearn/compiler/compose.py:L137-L140`). The composer finds
aggregates by a one-level walk of each step's `vars()`
(`compose.py:L165-L172`), keyed by Python object identity (`compose.py:L128`).

**Fit (the "learn pass").** `learn` collects every aggregate, builds each one's
AST against the placeholder table `__input__`, and hands the mapping to the
backend (`compose.py:L217-L225`). The backend runs one query per aggregate
(`sqlearn_000:src/sqlearn/backend/duckdb.py:L289-L322`). Every aggregate reads
the raw input: `agg.apply(_input_table())` (`compose.py:L222`). An aggregate
query must project exactly one column, and a one-row result becomes a scalar, a
many-row result a list (`duckdb.py:L562-L580`). `Pipeline.learn` returns a deep
copy and leaves the original alone
(`sqlearn_000:src/sqlearn/core/pipeline.py:L202`), unlike scikit-learn's `fit`,
which returns `self`.

**Learned state** lives in Python, on `result_`. A consuming step inlines it
into its SQL as a literal at apply time; the only example is a test fixture,
`COALESCE(col, <literal>)` built with `exp.convert(result_)`
(`sqlearn_000:tests/unit/compiler/test_compose.py:L148-L171`). Saving writes
JSON: class name, constructor parameters and, for aggregates, `result_`
(`pipeline.py:L684-L704`). Loading resolves the class by
`getattr(sqlearn, name)` (`pipeline.py:L965`) and calls the constructor with
the stored parameters; the slot `columns_` has to be renamed back to `columns`
(`pipeline.py:L744-L755`).

**Transform (the "apply pass").** `apply` threads the steps: each step's
`apply` receives the previous step's `Select`, wrapped as a subquery
(`compose.py:L263-L275`), so a pipeline is one nested query. The composer does
no fusion and leaves flattening to DuckDB's planner (`compose.py:L32-L38`).
`Pipeline.apply(out=...)` returns the AST, a SQL string in any sqlglot
dialect, or a materialised NumPy, Arrow, pandas or DuckDB result
(`pipeline.py:L209-L275`, `duckdb.py:L625-L657`).

**Execution.** One process-wide in-memory DuckDB connection, opened lazily
(`duckdb.py:L118-L143`). Input of any accepted form (file path, table name,
SQL string, DataFrame, AST) is bound by `CREATE OR REPLACE VIEW __input__`
on that shared connection (`pipeline.py:L662-L676`).

**Dialects.** All SQL is built as sqlglot ASTs, never as strings
(`step.py:L1-L7`), and rendered with `dialect="duckdb"`. Other dialects were
promised but deferred (`sqlearn_000:TODO.md`, "Additional dialects").

**Testing.** 883 tests at the end (`sqlearn_000:TODO.md`, header), in about
22,700 lines against about 4,900 lines of library code, written per unit by
"Hardener" agents in tiers: exact SQL strings, `parse_one` round trips,
sqlglot's Python executor for semantics where it supports the function, DuckDB
execution otherwise (`sqlearn_000:tests/unit/aggregates/test_mean.py:L444-L451`,
`L950-L980`). The gate is ruff `ALL`, strict pyright, 95 % branch coverage, 100
% docstrings, xenon grade A (`sqlearn_000:justfile`,
`sqlearn_000:pyproject.toml`). The only integration test imports the package
(`sqlearn_000:tests/integration/test_smoke.py:L6`).

**Validation** is separate from the tests: one script per formula-bearing step
in `validators/` compares the step's SQL, run in DuckDB, with an exact
reference and with numpy, pandas, polars and native DuckDB on scikit-learn's
datasets, and reports the error in ULPs per cell
(`sqlearn_000:validators/validate_std.py:L1-L56`, `L181-L197`). scikit-learn
was used only for its datasets: no validator calls a scikit-learn estimator,
since none of the steps built has one.

## Worth keeping

**SQL formulations verified against references** (by the validators, on
DuckDB 1.5.2, `sqlearn_000:uv.lock`):

- `Std` as `STDDEV_POP`, population form
  (`sqlearn_000:src/sqlearn/aggregates/std.py:L99`). That matches
  `StandardScaler`, which uses "a biased estimator for the standard deviation,
  equivalent to `numpy.std(x, ddof=0)`"
  ([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html)).
- `Mode` as `MODE(col ORDER BY col)`
  (`sqlearn_000:src/sqlearn/aggregates/mode.py:L68-L88`), reported as returning
  the smallest tied value (`sqlearn_000:validators/validate_mode.py:L1-L30`).
  That is the tie-break `SimpleImputer(strategy="most_frequent")` documents:
  "only the smallest is returned"
  ([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.impute.SimpleImputer.html)).
  DuckDB documents only that `mode` "is affected by ordering"
  ([DuckDB](https://duckdb.org/docs/2.0/sql/functions/aggregates.html)), not
  which tied value wins. Checked on DuckDB 2.0.0 (2026-11-03):
  `MODE(x ORDER BY x)` over 3, 1, 3, 1, 2 returns 1, plain `MODE(x)` returns 3,
  so the `ORDER BY` matters; a new test must still pin it.
- `Distinct` as `COALESCE(ARRAY_AGG(DISTINCT col), [])`, because `ARRAY_AGG`
  over zero rows is NULL (confirmed on DuckDB 2.0.0)
  (`sqlearn_000:src/sqlearn/aggregates/distinct.py:L226-L250`,
  `LESSONS.md:L196-L204`).
- `Sqrt` guarded by `CASE WHEN col < 0 THEN NULL ELSE SQRT(col) END`, because
  DuckDB's `SQRT` raised on negatives in the old repo (on DuckDB 2.0.0,
  `SQRT(-1.0)` returns NaN instead; the guard is still needed to give NULL)
  (`sqlearn_000:src/sqlearn/transforms/sqrt.py:L9-L22`, `L77-L102`); 0 ULP
  observed on 3,000 cells (`LESSONS.md:L351-L359`).
- `MissingIndicator` as `CAST(col IS NULL AS INTEGER) AS col_missing` beside
  `*` (`sqlearn_000:src/sqlearn/imputers/missing_indicator.py:L109-L133`).

**Validation technique.** Exact references (`mpmath` at 50 digits for
transcendentals and sums, `fractions.Fraction` for order statistics,
`LESSONS.md:L236-L244`); error measured in ULPs against a bound written down
per step and per dtype; two dataset sizes, because DuckDB's `STDDEV_POP`
misses by 4 to 26 ULP at N = 20,640 but not at N = 442 (`LESSONS.md:L226-L234`);
relative error when the true value is near zero, where ULPs explode
(`LESSONS.md:L216-L224`). Each cell records the dataset, its licence and the
library versions (`validate_std.py:L444-L466`).

**Gotchas already paid for** (`sqlearn_000:LESSONS.md`):

- DuckDB `LN(0)` and `LN(x<0)` raised rather than returned NULL (`L293-L321`).
  On DuckDB 2.0.0 they no longer raise: `LN(0.0)` is `-inf` and `LN(-1.0)` is
  NaN, so a guard is still needed, for a different reason.
- NaN in a pandas float column reaches DuckDB as NULL (`L361-L387`).
- `con.sql("")` returns `None` (`L125-L133`).
- Polars ingest needs pyarrow (`L135-L143`).
- `ATTACH ''` opens an empty database silently (`L145-L153`).
- sqlglot's `Select.from_(select)` emits `FROM SELECT` unless wrapped
  (`L115-L123`).
- sqlglot's executor lacks `LN` and `MEDIAN` (`L256-L331`).
- The generic dialect adds and then drops `NULLS LAST` inside an ordered
  aggregate (`sqlearn_000:PROCEDURE_FEEDBACK.md`, commit `9d7ade3`).

**API and design ideas** worth weighing, not yet proven:

- A learned statistic as a first-class object passed as a parameter
  (`value=Mean("price")`): fit becomes "evaluate every aggregate", and a
  node editor can show it as an edge.
- `out="sql"` and `out="ast"` returning the compiled query without running it.
- JSON serialisation that resolves classes by name from one namespace and
  never unpickles (`pipeline.py:L956-L972`).
- Errors that carry the offending values and the ways forward
  (`step.py:L395-L436`).

## What went wrong

**Fit does not see earlier steps' output.** All aggregates are learned from
`__input__` (`compose.py:L222`). In a pipeline like "impute, then scale", the
scaler's mean would come from un-imputed data. Nothing in the code or tests
handles this ordering; inference: the consuming steps that would have exposed
it were never written.

**Aggregates mostly could not be learned.** The backend accepts one projected
column per aggregate (`duckdb.py:L562`), so `Mean(["x","y"])` and
`Mean("x", group_by="g")` fail at `learn`. The tests pin this as a v0.1.0
limitation rather than fixing it
(`sqlearn_000:tests/unit/aggregates/test_mean.py:L793-L815`, and the same in
`test_max.py:L661`, `test_median.py:L827`). The universal `group_by`,
`order_by` and `dtype` parameters were thus accepted everywhere but usable
nowhere in fit.

**NULL as a sentinel.** `is_fitted` means `result_ is not None`, so a mean
over an all-NULL column leaves the pipeline unfitted for ever; a test pins it
(`test_mean.py:L765-L770`). `Distinct` had to wrap its result in `COALESCE`
for the same reason (`LESSONS.md:L200`).

**Column contract undefined.** `Log`, `Sqrt` and `Abs` select only their own
columns (`sqlearn_000:src/sqlearn/transforms/log.py:L171-L172`,
`sqrt.py:L207`, `abs.py:L151-L154`), while `MissingIndicator` keeps `*`
(`missing_indicator.py:L109`). Inference from the code: `Pipeline([Log("x"),
Abs("y")])` would fail, as `y` is gone after the first step. `Log` also renames
to `x_log` while `Abs` keeps `x`.

**Spec and runtime drift.** The spec said `LN` of non-positive values returns
NULL; it raises, filed as a blocker (`sqlearn_000:reports/2026-04-29-20-00.md`).
Aggregate specs said `"static"`, the base class `"dynamic"`
(`reports/2026-04-29-18-40.md`, `reports/2026-04-29-19-00.md`). `load` was
documented to keep unknown fields and dropped them
(`reports/2026-04-29-18-26.md`, pinned at
`sqlearn_000:tests/unit/core/test_pipeline.py:L2132`). All four were closed
as "superseded" by the redesign, not fixed (`a4fc0d6`).

**Validation could not fail where it mattered.** In `validate_std.py`, any
failing DuckDB cell is labelled an anomaly (`L442`), and only non-anomaly
failures exit non-zero (`L752-L757`); the sqlearn path is a DuckDB path, so
inference: that validator could not fail the step. `Mean`'s bound is n ULPs
(`sqlearn_000:validators/validate_mean.py:L353-L356`), 20,640 ULPs on the
largest dataset. Validators ran outside `just gate` (`justfile`: `validate`
only lists them). They call `step.apply` on a fresh connection
(`validate_std.py:L249-L275`), so they test the formula, not the pipeline.
The `Log` validator cited in `LESSONS.md:L295` is not in the history (`git log
--all -- validators/validate_log.py` is empty).

**Not offline.** Validators load `fetch_california_housing` and claim it is
bundled (`sqlearn_000:validators/validate_std.py:L118-L135`); scikit-learn's
documentation says it downloads on first use and caches
([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html)).

**Shared global state.** One connection and one view name, `__input__`, per
process (`duckdb.py:L118-L143`, `pipeline.py:L676`). Inference: two pipelines
in flight, or a learn inside an apply, would rebind each other's input.

**Error taxonomy overloaded.** `UnsupportedDialectError` covers a missing
file, bad JSON, an unserialisable value and missing pandas
(`duckdb.py:L445-L460`, `duckdb.py:L642-L657`, `pipeline.py:L1008-L1015`).

**Process outweighed product** (inference from the history). 4,900 lines of
library came with 22,700 lines of tests, 7,900 of validators and 5,500 lines
of agent and skill instructions (`.claude/`); 36 of 76 commits are `chore` or
`docs`. Rules lived in a second repository the code repo could only read
(`CLAUDE.md:L7-L13`), so drift had to travel by report files and never closed
in the code repo.

## Bearing on the open questions

Evidence only; the decisions are Tomas's.

### [scikit-learn API survey](../../scikit-learn-api-survey.md)

- The old repo departed from scikit-learn (`learn`/`apply`, verb class names,
  a fitted copy returned) with no recorded reason in this repo. Its own
  serialiser then needed special cases, because `columns` was stored as
  `columns_` (`pipeline.py:L744-L755`). scikit-learn's rule, that `__init__`
  stores each parameter unchanged under its own name, is what makes generic
  `get_params`, cloning and serialisation work; this is evidence for copying it
  as is.
- The universal parameters (`where`, `group_by`, `order_by`, `dtype`) on every
  step went unimplemented in fit; evidence against a wide shared signature
  before the core supports it.
- Column pass-through needs one rule for every step, as `ColumnTransformer`'s
  `remainder` makes explicit in scikit-learn; the old repo had none.

### [How `fit` executes](../../fit-execution-model.md)

- One-query fit was never attempted: one query per aggregate, by design
  (`duckdb.py:L289-L291`).
- Batching every aggregate against the raw input is wrong for dependent steps
  (`compose.py:L222`). The evidence favours learning in step order, each
  step's aggregates against the previous steps' transform SQL, with
  independent aggregates batched into one `SELECT` within a stage.
- Learned values as Python attributes, inlined as SQL literals, serialised to
  JSON, was the design; only a fixture exercised the inlining, and how floats
  render as literals (full precision or not) was never tested.
- "Not fitted" must be its own state, not `None`, or an all-NULL column
  breaks it (`test_mean.py:L765`).
- One-query transform worked as nested subqueries, with flattening left to
  DuckDB; no performance or larger-than-memory test exists.

### [Multi-engine support](../../multi-engine-support.md)

- sqlglot was the internal representation from day one. It gave structural
  tests and safe identifier quoting.
- It cost: three stub-typing traps (`LESSONS.md:L55-L63`, `L105-L113`,
  `L246-L254`), the subquery wrap, the `from_` key, an executor too small for
  `LN` and `MEDIAN`, and a generic dialect that rewrites `NULLS LAST`, which
  shows that translation can change NULL ordering, not just syntax.
- Portability was never tested: 501 `dialect="duckdb"` calls in tests and one
  `dialect="postgres"`, which only checks the string is non-empty
  (`test_pipeline.py:L485-L487`).
- DuckDB behaviours the SQL depends on (`LN` and `SQRT` raising, `MODE`
  ordering, `ARRAY_AGG` over no rows) are engine-specific and needed guards
  on DuckDB itself; each would need re-checking per engine.
- The repo stopped at a "multi-dialect redesign" (`a4fc0d6`); its content is
  in the private repository and unread here.

### [Validation method](../../validation-method.md)

- **Precision:** `mpmath` at 50 digits for transcendentals and sums,
  `Fraction` for selection and interpolation; `Fraction` is exact and so
  stronger where it applies (`LESSONS.md:L236-L244`).
- **Tolerances used:** 0 ULP for min, max, mode, distinct, abs and odd-N
  median; 1 ULP for sqrt (0 observed); 2 ULP for std; n ULPs for mean. The
  n-ULP bound is worst-case and too loose to catch errors; the std anomaly
  rule hid real misses. Evidence that a tolerance needs a stated derivation and
  that failures of the library's own path must fail.
- **Presentation:** per-cell JSON or Markdown tables with value, reference,
  ULPs, bound, status and versions (`validate_std.py:L444-L466`).
- **Iterative algorithms:** no evidence; none were built.
- **Datasets:** use bundled ones (`load_diabetes`, `load_wine`, `load_iris`)
  or generated data; `fetch_california_housing` needs the network. Check the
  pandas NaN-to-NULL step at ingest before testing NaN behaviour.

## Dependencies and licences

| Dependency | Where | Licence | Against "duckdb only" |
| --- | --- | --- | --- |
| `duckdb>=1.4` (1.5.2 locked) | runtime | MIT ([GitHub](https://github.com/duckdb/duckdb/blob/main/LICENSE)) | allowed |
| `sqlglot>=27.0` (30.6.0 locked) | runtime, imported in 34 places | MIT ([GitHub](https://github.com/tobymao/sqlglot/blob/main/LICENSE)) | needs an ADR 0005 reason |
| `numpy>=2.2` (2.4.4 locked) | runtime, never imported by `src/` | BSD-3-Clause ([numpy](https://numpy.org/doc/stable/license.html)) | not needed; `out="numpy"` only calls DuckDB's `fetchnumpy` |
| `mpmath`, `scipy`, `scikit-learn`, `pandas`, `polars`, `statsmodels` | `validators` group | permissive | dev-only, allowed |
| ruff, pyright, pytest, mutmut, interrogate, xenon, pre-commit, detect-secrets, pip-audit | `dev` group | permissive | dev-only, allowed |

Sources: `sqlearn_000:pyproject.toml` (dependencies and groups),
`sqlearn_000:uv.lock` (versions). The repo itself was MIT
(`sqlearn_000:LICENSE`); this one is Apache-2.0
([ADR 0004](../../../adr/0004-apache-2-licence.md)).

## Later commits

The local copy (ROOT `sqlearn-ecosystem/sqlearn`) has six commits on 30 April
beyond the 76 reviewed above, read with `git log` and `git diff` only
(step 8 of [the plan](../README.md)).

- **The code was wiped for the redesign.** `ff880ba` ("reset implementation
  for v0.1.0 redesign") deletes the source, tests, validators, reports, plans
  and `LESSONS.md`: 37,526 lines out, the whole of what this review describes.
  The war room's multi-dialect redesign replaced it.
- **Only validation scaffolding was rebuilt** (`bed78e7`, `335e12c`,
  `d11ce71`, `bdc93f1`), and no validator was written: the results file is a
  header only. As designed in `validators/README.md`:
  - `canonical` (mpmath at 50 digits) is one reference among the named
    libraries (numpy, scipy, scikit-learn, pandas, polars, statsmodels, R,
    DuckDB), so "faithful to the maths" and "matches what users expect" are
    separate rows;
  - one result per step × dataset × DuckDB type × reference, with worst
    absolute, relative and ULP error against a precision floor derived from
    the operation and type;
  - an `anomaly` flag for a reference library that misses its own
    algorithm's precision, distinct from pass or fail;
  - a "2-2-2" rule enforced in code: every run covers two small (up to 5,000
    rows), two medium (20,000 to 50,000) and two large (200,000 or more)
    datasets, because cancellation and engine effects only show at size;
  - the exact reference subsampled to 10,000 rows above 50,000, with the
    sample size recorded;
  - per-feature JSON history (append-only), a current-state CSV and a
    rendered Markdown page, all written by one helper.
- **Against this repository's rules:** the datasets are downloaded from
  Kaggle, UCI, scikit-learn and HuggingFace (`datasets/download.py`), which
  ADR 0006 forbids; tests use synthetic data and only the validators use real
  data.

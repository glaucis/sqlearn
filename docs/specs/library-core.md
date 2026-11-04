---
type: spec
tags: [library-core, pipeline, steps, learn, apply, search, selectors, learning-store]
summary: "Spec for sqlearn's library core (overview 3.2): the step contract, how runs are planned, the learning store, selectors, lazy results, the search, and the vertical slice that proves them."
related: [docs/architecture/overview.md, docs/adr/0012-static-and-dynamic-steps.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0014-learning-store.md, docs/adr/0015-duckdb-expressions-no-sqlglot.md, docs/adr/0016-validation-method.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/0018-runs-follow-the-chains-between-steps.md, docs/adr/0019-custom-steps-and-failure-feedback.md, docs/adr/0020-column-selectors.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/adr/0022-one-search-with-pluggable-methods.md, docs/adr/0023-lazy-results-out-and-feed.md]
---
# Library core

Part 3.2 of [the overview](../architecture/overview.md): the contracts every
later part is built on, proven by one vertical slice.

Status: approved by Tomas on 2026-11-04. Written from the design talk of that
day; every decision it rests on is in ADRs 0012–0025. Where this spec
makes a call of its own, it says "(spec's call)".

Built: see [the plan](../plans/2026-11-04-library-core.md). The rulings made
while building are in the branch's history.

## 1. Purpose

sqlearn prepares data in DuckDB, as SQL, so it works on data larger than
memory, and hands the prepared data to a model library the user already uses.
The core is the machinery under every step: how a step is written, how a
pipeline becomes as few SQL queries as possible, how learned values are kept
and reused, how columns are chosen, what results look like, and how a search
over settings runs.

It must be **fast in the normal case** and **explain itself in full when
something fails**. The normal path does only what it must; diagnosis runs only
after a failure ([ADR 0019](../adr/0019-custom-steps-and-failure-feedback.md)).

## 2. The slice

The script the core must run, end to end:

```python
import sqlearn as sq
from sklearn.linear_model import LogisticRegression

pipe = sq.Pipeline(
    [
        ("impute", sq.Impute(cols=sq.numeric(), strategy="median")),
        ("onehot", sq.OneHot(cols=["city"])),
        ("ordinal", sq.Ordinal(cols=["plan"])),
        ("scale", sq.Scale(cols=sq.numeric())),
        ("model", LogisticRegression()),
    ]
)

search = sq.Search(
    pipe,
    params={"model__C": [0.1, 1, 10], "impute__strategy": ["median", "mean"]},
    metric=sq.accuracy,
)
search.train("data/train/*.parquet", target="churned")
print(search.best_params_, search.best_score_)
search.results_.show()
search.predict("data/new.parquet", out="pandas")
```

It shows, and its tests prove:

- **chaining:** `Scale` learns from imputed values, inside one query;
- **dynamic steps:** `OneHot` and `Ordinal` are independent and learn in the
  same run; `Scale` reads `OneHot`'s new columns (it selects `sq.numeric()`)
  and so goes in the next run;
- **the store:** over 2 imputer settings × 3 values of `C` × 5 folds (30
  trainings), `Impute` and `Scale` learn 10 times, `OneHot` and `Ordinal` 5
  times (they never read what `Impute` writes); changing only `C` learns
  nothing ([ADR 0024](../adr/0024-store-keys-follow-what-a-step-reads.md));
- **fold first:** the data is transformed once per fold and imputer setting,
  10 times for 30 trainings;
- **the hand-over:** numpy to scikit-learn's `LogisticRegression`;
- **the metric:** accuracy, computed in SQL;
- **larger than memory:** the preparation runs under a DuckDB memory limit
  smaller than the data (§13).

## 3. Steps

### 3.1 The contract

A step prepares data. It has two parts: what it learns and how it applies it.
Both are built from DuckDB's expression objects
([ADR 0015](../adr/0015-duckdb-expressions-no-sqlglot.md)), never SQL text.

```python
class Scale(sq.Step):
    def __init__(self, cols=sq.numeric(), keep=False):
        self.cols = cols
        self.keep = keep

    def learn(self, x):
        return {"mean": sq.avg(x), "scale": sq.stddev_pop(x)}

    def apply(self, x, learned):
        return (x - learned.mean) / learned.scale
```

- `learn(x)` is called once per selected column; `x` is that column as an
  expression. It returns named aggregates. A step that learns nothing does not
  define it.
- `apply(x, learned)` is called once per selected column. It returns one
  expression (the column's new value) or a dict of name to expression (new
  columns, as `OneHot` does).
- `learned` gives each learned value by name. While a query that both learns
  and applies is built, it holds **placeholders**: references to the learn
  stage of the same query. When values are known (a later run, or `apply` on
  new data) it holds them as constants.
- Settings are `__init__` arguments stored under their own names, as
  scikit-learn does, so `get_params`, `set_params` and `clone` can be added
  later ([ADR 0013](../adr/0013-learn-apply-train-predict.md)).
- Learned values are readable after `learn` as attributes named after what
  `learn` returned, with `_` added: `pipe["scale"].mean_`, a dict of column to
  value (no numpy at run time). They are read from the store entry of the step's
  most recent `learn`, as scikit-learn's attributes reflect the last `fit`. A
  pipeline is indexed by step name (`pipe["scale"]`) or position, as in
  scikit-learn; `pipe.steps` keeps scikit-learn's `(name, step)` pairs
  (spec's call).
- `sq.avg`, `sq.stddev_pop`, `sq.median` and the like are thin wrappers that
  build DuckDB expression objects. The slice needs those its steps use; more
  come with the steps that need them. `sq.avg` is the compensated mean
  (DuckDB's `favg`). `sq.median` is an exact median computed by sorting, so it
  spills to disk: DuckDB's own `median` does not
  ([issue #27](https://github.com/glaucis/sqlearn/issues/27) tracks the sort's
  reach).
- Steps that change rows (filters, sampling) are not in the slice; the contract
  leaves room for them ([ADR 0012](../adr/0012-static-and-dynamic-steps.md)).

### 3.2 What a step declares

Every step declares, as data, so the run planner (§4) and later the node editor
can read it without special cases:

- **its settings:** from the `__init__` signature;
- **its inputs:** the columns it reads (`cols=`, §6);
- **its outputs:** the columns it writes. A replacing step writes its inputs; a
  step with `keep=True` writes `<column>_<step>`; a dynamic step declares the
  **types** of the columns it will create (OneHot: integers), even before their
  names are known
  ([ADR 0018](../adr/0018-runs-follow-the-chains-between-steps.md));
- **static or dynamic:** built-in steps declare it, per settings where it
  depends on them; a user's step may (`static = True` or `dynamic = True` as a
  class attribute) or may leave it out (§3.4).

### 3.3 Replace or keep

A step replaces its columns by default (`keep=False`). `keep=True` keeps the
original and adds `<column>_<step>` (`age_log`). A name that already exists
stops the run with a message naming it; `suffix="..."` chooses another. Nothing
is overwritten silently.

### 3.4 A user's own step

Per [ADR 0019](../adr/0019-custom-steps-and-failure-feedback.md):

1. A declared class is trusted.
2. An undeclared one is inspected before the first run: its `apply` is called
   with placeholders. If it builds an expression, it is static; if it needs a
   real value (iterating, comparing, converting a placeholder), the placeholder
   raises sqlearn's own signal and the step is dynamic; any other exception
   also means dynamic.
3. The answer is kept in memory for the session, per step class and settings,
   beside the learning store.

### 3.5 Steps in the slice

| step | class | learns | applies |
|---|---|---|---|
| `Impute(strategy="median" \| "mean")` | static | median or mean | `coalesce(x, value)` |
| `Scale()` | static | mean, population standard deviation | `(x - mean) / sd` |
| `OneHot()` | dynamic | the sorted distinct values | one integer column per value, `<column>_<value>` |
| `Ordinal()` | dynamic | the sorted distinct values | each value's position, as an integer |

Edge cases each step specifies and tests, against scikit-learn's behaviour
where it has one: NULL and NaN (NaN is not NULL in DuckDB), an all-NULL column,
a constant column (`sd = 0`), a value at `apply` that was not seen at `learn`
(OneHot: all zeros, as scikit-learn's `handle_unknown="ignore"`; Ordinal: -1,
as `handle_unknown="use_encoded_value", unknown_value=-1`; never NULL, so
`predict` on new data does not hand the model a NaN; spec's call), reserved
words and spaces in column names.

## 4. Runs

Per [ADR 0018](../adr/0018-runs-follow-the-chains-between-steps.md):

- The pipeline is planned as a graph of columns. Each step goes in the
  **earliest run its own inputs allow**. A step must wait for a dynamic step
  when it reads a column whose existence or shape depends on that step's
  learned values; a selector waits when it could match the types the dynamic
  step declared (§6).
- Within a run, everything is one query: a chain of `WITH` stages, each step
  reading the stage before it, learn stages beside the data stages. Learned
  values of static steps are referenced, never written in as numbers, during
  learning.
- **A run** is one chained SQL tree. When a run must both learn values and
  produce data (the run that feeds the model learns `Scale`), it executes as
  two statements: one `WITH` query returns every learn stage of the run as one
  row, which is fetched, then the data query is built with those values as
  constants. DuckDB reads the data as often as it would inside one `WITH`
  query, which also reads it once to learn and once to apply, and the learned
  values are in hand for the store. A run that only learns is one statement
  (spec's call).
- The model counts as a reader: the data handed to it is produced by the run
  after the last dynamic step it depends on.
- A step whose columns are not known (all columns, or an undeclared user step)
  depends on everything before it.
- `apply` and `predict` with every value known are always one run.
- The compositor is the one place that turns pieces into SQL text. It names
  each stage after its step, so a DuckDB error can be traced to a step. Learn
  stages are left to DuckDB's default materialisation or marked
  `MATERIALIZED`, never `NOT MATERIALIZED`, and never built by chaining lazy
  relation objects (ADR 0012).
- How a one-row learn stage reaches the data stage (a cross join, or a scalar
  subquery) is left to the builder; the test of every expression form's
  printed SQL covers it (ADR 0015).

The number of runs is observable: each `learn`, `train` and `apply` records
its runs and their statements (`pipe.runs_` holds the last call's; spec's
call), so tests assert both.

## 5. The learning store

Per [ADR 0014](../adr/0014-learning-store.md) and
[ADR 0021](../adr/0021-inputs-and-how-the-store-knows-them.md):

- One store per Python process, in memory. An entry holds a step's learned
  values, the columns its selector matched, and its `apply` SQL.
- Key: the data, the fold, the step's settings, and the settings of the steps
  whose output it reads, followed back through the graph of columns; a step
  that changes rows is read by every step after it; a step whose selector
  could have matched a column an earlier dynamic step took away depends on
  that step; and the columns the step's selector resolved to
  ([ADR 0024](../adr/0024-store-keys-follow-what-a-step-reads.md)).
- The data part, by kind of input:

  | input | key | in the slice |
  |---|---|---|
  | file or glob | path(s), size, modification time | yes |
  | DuckDB table or relation | connection, name (or the relation's SQL), row count | yes |
  | pandas DataFrame | fingerprint of values and row order, computed by DuckDB | yes |
  | Polars, Arrow | the object, through a weak reference | after the slice (spec's call) |

- The fingerprint is computed once per call to `learn`, `train` or a search,
  never per fold.
- The store never keeps the user's data alive and never holds data, only keys,
  values and SQL text.
- The static/dynamic answers for user steps (§3.4) live beside it.
- Size limits and `sq.store.clear()` wait for
  [issue #23](https://github.com/glaucis/sqlearn/issues/23).

## 6. Selectors

Per [ADR 0020](../adr/0020-column-selectors.md):

- `cols=` takes a list of names or a selector. The slice has `sq.cols(...)`,
  `sq.numeric()` and `sq.string()`, combined with `|`, `&`, `-` and `~`.
- A selector is resolved in Python against the schema at that point in the
  pipeline (names and types, read without reading rows), then the SQL gets
  plain names.
- For planning, a selector is resolved against declared output types where
  names are not yet known: `sq.numeric()` after `OneHot` waits for it,
  `sq.string()` does not.
- What a selector matched is fixed at `learn` and stored, so `apply` on other
  data uses the training columns.
- A selector that matches nothing is an error naming the step (spec's call).

## 7. Inputs and the target

- `learn`, `apply`, `train`, `predict` and a search take a file path or glob
  (Parquet, CSV, JSON), a DuckDB table name or relation, or a pandas DataFrame.
  Polars and Arrow come after the slice. DuckDB reads them all; sqlearn depends
  only on `duckdb`.
- `train(data, target="churned")` takes the target by column name. The target
  is set aside before the steps run: no step and no selector sees it (spec's
  call), so `sq.numeric()` never scales the target.
- Every sqlearn object works on one DuckDB connection: the user's, if given
  (`sq.set_config(connection=con)`), otherwise one sqlearn opens in memory
  (spec's call).

## 8. Results: `out=` and `feed=`

Per [ADR 0023](../adr/0023-lazy-results-out-and-feed.md):

- `apply` and `predict` return a DuckDB relation by default: lazy, with column
  names.
- `out=` turns it into what the user wants: `"pandas"`, `"polars"`,
  `"numpy"`, `"arrow"`, or `sq.out_parquet(path)`, `sq.out_csv(path)`,
  `sq.out_json(path)`, which DuckDB writes straight to disk.
  `sq.set_config(out=...)` sets a session default.
- `feed=` is the form handed to the model: numpy by default for every model.
  `sq.Model(estimator, feed=...)` carries it with the model; `train(...,
  feed=...)` overrides it for one call. The slice builds numpy only; Arrow and
  batches are [issue #21](https://github.com/glaucis/sqlearn/issues/21).
- After `learn`, `pipe.columns_out_` lists the output columns, without running
  anything.

## 9. Pipelines and models

- `sq.Pipeline([("name", step), ...])` as in scikit-learn; `sq.make_pipeline`
  names steps after their class.
- A pipeline without a model has `learn` and `apply`; one that ends in a model
  has `train` and `predict`
  ([ADR 0013](../adr/0013-learn-apply-train-predict.md)). `learn` and `apply`
  refuse a pipeline that ends in a model, and say to use `train` and
  `predict`.
- The model is any object with scikit-learn's `fit` and `predict`
  ([ADR 0017](../adr/0017-models-from-other-libraries.md)). `train` learns the
  preparation (or finds it in the store), applies it, hands the result with the
  target to `fit`. `predict` applies with the stored values, hands the result
  to the model's `predict`, and returns the predictions as a relation of one
  column, `prediction`, one row per input row in the input's order, by the
  same `out=` rule (as scikit-learn returns one array; spec's call).
- Row order is the one internal row identity: the query that feeds the model
  numbers the rows in a fixed order, so predictions line up with the input and
  with the target (§11). It is not a user-facing column.
- `sq.Model(estimator, feed=...)` wraps a model with sqlearn's settings for
  it; a plain model is wrapped as `sq.Model(model)` silently.
- `sq.FeatureUnion` is not in the slice; it comes with the library's breadth
  (overview 3.3).

## 10. The search

Per [ADR 0022](../adr/0022-one-search-with-pluggable-methods.md):

- `sq.Search(pipe, params=None, metric=..., method=..., folds=...)` with
  `train` and `predict`; `method` defaults to `sq.Grid()`, `folds` to
  `sq.KFold(5, seed=0)`. The slice builds `sq.Grid()` only; `sq.Random`,
  `sq.Optuna` and other methods come after it, as adapters over ask and tell.
  The method interface (ask for settings, tell a score, say when to stop) is
  defined in the slice so they plug in without changes.
- `params` as lists, keyed `step__setting` as in scikit-learn, including
  `"model"` to try several models. Settings that only some models have are
  written as scikit-learn's list of grids, one per model, as in
  [ADR 0023](../adr/0023-lazy-results-out-and-feed.md)'s example. A setting a
  model does not have is refused with a message naming both.
- The search works on copies and never changes the user's `pipe`. sqlearn
  steps are copied from their settings; an outside model with scikit-learn's
  `get_params` is copied the way scikit-learn's `clone` does (by its class and
  `get_params`), any other with `copy.deepcopy`. No new dependency
  (spec's call). `sq.range(...)` is defined with the method
  interface; given to grid, it is refused with a message.
- **Folds:** `sq.KFold(k, seed)` gives each row a fold number from a hash of
  its values and the seed, so it is the same in every query, needs no stored
  column, and puts identical rows in the same fold (spec's call; ADR 0014 asks
  only that folds be fixed and seeded, never `RANDOM()`).
- Grid loops **fold first** (ADR 0024): for each fold, and each distinct
  preparation among the settings, it learns the preparation on the other folds
  (or finds it in the store), applies it to all the fold's rows once, then
  trains every model setting on the training rows, predicts the held-out rows
  and computes the metric in SQL, before dropping that data. The method
  interface lets a method say whether it knows its settings up front (grid,
  random) or picks them one at a time (Optuna), which loops setting first.
- At the end the best setting is trained on all the data (as `refit=True`),
  as `search.best_pipeline_`, which `search.predict` uses.
- **Defaults:** with no `params`, the default search space for a known model
  is used; the slice knows only `LogisticRegression` (`C` from 0.001 to 100,
  log scale, as a grid of 7 values for `sq.Grid`; spec's call). An unknown
  model is evaluated with its own settings over the folds (one trial). Either
  way a `sq.DefaultsUsedWarning` says what stood in and how to choose.
- **Record:** `best_params_`, `best_score_`, `results_` (a relation: one row
  per setting and fold, with the score) and `used_` (what was given and what
  was defaulted).

## 11. Metrics

- A metric takes the target and the predictions as columns of one relation and
  computes its value in SQL. The slice has `sq.accuracy`.
- Predictions come back from the model as an array, aligned with the rows the
  model was fed; they are joined to the target by row position in the order the
  query produced them (the builder ensures that order is fixed for the query).
- Validated per ADR 0016 like any other formula.

## 12. Errors and messages

- Every failure in a user's step says which step (name and position), what
  went wrong, why, and the fix, in the form of ADR 0019's example.
- A failure inside a built-in step is reported as an internal error, saying it
  is sqlearn's bug and how to report it, with what reproduces it.
- Errors derive from one `sq.SqlearnError`; warnings from one
  `sq.SqlearnWarning` (`DefaultsUsedWarning` among them). Names beyond these are
  the builder's.
- Diagnosis code (inspecting declarations again, tracing a DuckDB error to a
  stage) runs only after a failure.

## 13. Tests and validation

- **Against scikit-learn:** the slice's pipeline and each step alone give
  scikit-learn's answer (its `Pipeline`, `ColumnTransformer`,
  `SimpleImputer`, `StandardScaler`, `OneHotEncoder`, `OrdinalEncoder`,
  `GridSearchCV`), within bounds set from measurement.
- **Against the mathematics:** each step's formula and `accuracy` per
  [ADR 0016](../adr/0016-validation-method.md): a canonical value at 50 digits,
  DuckDB's own function alone and at one thread, numpy, scikit-learn and pandas
  compared with it.
- **Results stored as data**
  ([ADR 0025](../adr/0025-results-stored-as-data-in-mirrored-folders.md)): every
  validation case, every test outcome and the environment are written as
  committed JSON with fixed names, in folders that mirror the package
  (`validation/sqlearn/preprocessing/scale.results.json`). `just validate`
  writes them; `just verify` runs it. The pages that publish them come with
  overview 3.8; the results are complete from the slice on. Each case records
  what a page needs: worst absolute, relative and ULP error per dataset, type
  and reference, the bound, the result (pass, fail, anomaly), and known
  divergences with their reason.
- **The mirror is enforced:** `just check` fails when a module has no test
  file or a step has no validation runner.
- **Runs:** for every combination that can be built from the slice's steps and
  selectors (static only; independent dynamic steps; a chain that forces a
  split; a step reading everything; an undeclared user step), the test asserts
  the results and the number of runs.
- **Store:** reuse and relearning as ADR 0014 lists them; an edited pandas
  DataFrame relearns; a search learns the preparation once per fold and
  imputer setting; the store's size is reported.
- **Broken user steps:** a suite of deliberately wrong steps (a wrong
  declaration, bad SQL, a missing column, a selector that matches nothing),
  each checked for its exact message.
- **Larger than memory:** a `slow` test runs the slice's preparation on
  generated data under a DuckDB memory limit smaller than the data, as
  `tests/test_environment.py` does.
- Data is bundled or generated with a fixed seed, never downloaded.
- scikit-learn, numpy, pandas and mpmath join the test dependencies; none is a
  runtime dependency.
- Coverage: 95% of branches in `src/sqlearn`, enforced from the slice on
  (spec's call; the foundation left the floor to this spec).

## 14. Documentation

- Every public object has a numpydoc docstring.
- A user guide page, "Writing a step", covers §3 and §12: the two-part
  contract, placeholders, declaring static or dynamic, and the messages.
- One gallery example runs the slice's script on generated data.

## 15. Done when

- The slice's script runs end to end.
- §13's tests and validations pass in `just verify`, the slow tier included,
  and their results are committed under `validation/`.
- The documentation in §14 builds.

## 16. Not in the core

Each has its own place:

- saving a pipeline to a file, exporting a trained pipeline as code:
  [issue #24](https://github.com/glaucis/sqlearn/issues/24);
- keeping prepared fold data on disk for repeated searches:
  [issue #25](https://github.com/glaucis/sqlearn/issues/25);
- saving the learning store:
  [issue #20](https://github.com/glaucis/sqlearn/issues/20);
- Arrow and batches for `feed=`:
  [issue #21](https://github.com/glaucis/sqlearn/issues/21);
- OneHot as a list column:
  [issue #22](https://github.com/glaucis/sqlearn/issues/22);
- store limits and `clear()`:
  [issue #23](https://github.com/glaucis/sqlearn/issues/23);
- `sq.Random`, `sq.Optuna` and other methods, `FeatureUnion`, more selectors,
  more steps, more metrics, Polars and Arrow inputs: the library's breadth
  (overview 3.3);
- `get_params`, `set_params`, `clone` and scikit-learn aliases: later, made
  easy by §3.1.

## 17. Left to the builder

- The module layout inside `src/sqlearn/`.
- How a one-row learn stage joins the data stage (§4).
- How the fingerprint hashes (any DuckDB hash that covers values and order).
- Internal names, and the text of messages beyond the form ADR 0019 sets.

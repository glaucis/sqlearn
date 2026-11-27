---
type: spec
tags: [model-selection, search, folds, hand-over, feed, batches, optuna, metrics, library-breadth]
summary: "Spec for the model-selection area of sqlearn's library breadth (overview 3.3): handing prepared data to models from other libraries without running out of memory, keeping prepared folds for repeated searches, more search methods and kinds of folds, a few metrics, and a grouped home for the search's names."
related: [docs/architecture/overview.md, docs/specs/archived/library-core.md, docs/specs/archived/library-preprocessing.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/0022-one-search-with-pluggable-methods.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/adr/0034-a-grouped-api.md, docs/adr/0014-learning-store.md]
---
# Library breadth: model selection

The second area of part 3.3 of [the overview](../../architecture/overview.md).

Status: approved by Tomas on 2026-11-07. Written from the design talk of
2026-11-07. It rests on
[ADR 0017](../../adr/0017-models-from-other-libraries.md) (models come from
other libraries),
[ADR 0022](../../adr/0022-one-search-with-pluggable-methods.md) (one search with
pluggable methods) and [ADR 0034](../../adr/0034-a-grouped-api.md) (a grouped
API), and absorbs [#21](https://github.com/glaucis/sqlearn/issues/21) and
[#25](https://github.com/glaucis/sqlearn/issues/25). Where this spec makes a
call of its own, it says "(spec's call)".

Tracked in [issue #33](https://github.com/glaucis/sqlearn/issues/33).

## 1. Purpose

sqlearn does everything up to the model: it reads the data, prepares it in
DuckDB and hands it to a model the user imported (scikit-learn, CatBoost,
XGBoost, LightGBM, any object with `fit` and `predict`). sqlearn never trains
a model itself; models in SQL stay a later idea (ADR 0017).

Tuning a model today hurts in three ways, and this area exists to end them:

1. **Data that does not fit in memory.** The preparation already runs in
   DuckDB, which spills to disk in a planned way. But the hand-over loads each
   fold's training rows into one numpy array, so a fold larger than memory
   makes the operating system swap and everything crawls.
2. **Work done again.** scikit-learn re-fits and re-transforms the whole
   preparation for every setting and fold. The core's grid search already
   prepares each fold once and trains every setting on it; a method that picks
   settings one at a time (Optuna) and a user running several searches still
   prepare the data again.
3. **Results that depend on how they were computed.** Eager and lazy Polars
   can give different answers. In sqlearn every number comes from one SQL
   engine, the same way every time; nothing here may break that.

Model selection means choosing a model's settings by trying them over folds
and keeping the best. It is not about building models.

## 2. The script this area must run

The area is done when this runs end to end, the streamed pipeline on data
larger than the machine's memory with memory use staying bounded. This is
the script as it runs (Ruling R18 of the build): the text columns (here
`city` and `plan`) hold no NULL, since CatBoost refuses a missing category,
and CatBoost is told which columns are text with `cat_features=`, as it
would be without sqlearn; the stream takes numbers only, so its pipeline
one-hot encodes the text first. The validation runner
(`validation/pipelines/validate_model_selection.py`, `run_the_script`) runs
this code, scaled down.

```python
import sqlearn as sq
from catboost import CatBoostClassifier
from sklearn.linear_model import SGDClassifier

pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.Model(
            CatBoostClassifier(verbose=0, cat_features=["city", "plan"]),
            feed="pandas",
        ),  # text reaches it as categories
    ]
)

search = sq.search(
    pipe,
    params={
        "model__depth": sq.search.range(4, 10),
        "model__learning_rate": sq.search.range(0.01, 0.3, log=True),
    },
    method=sq.search.optuna(trials=40, seed=0),
    folds=sq.folds.stratified(5, seed=0),
    metric=sq.metrics.log_loss,
    keep_prepared="churn.duckdb",
)
search.train("data/train/*.parquet", target="churned")
search.best_params_, search.best_score_
search.predict("data/new/*.parquet", out=sq.out.parquet("scored.parquet"))

# A model that learns in pieces trains on data larger than memory.
stream = sq.Pipeline(
    [
        sq.impute.median(),
        sq.scale.standard(),
        sq.encode.onehot(),  # the stream takes numbers only
        sq.Model(SGDClassifier(loss="log_loss"), feed="stream", rows=100_000),
    ]
)
stream.train("data/train/*.parquet", target="churned")
```

## 3. The hand-over: `feed`

How prepared data reaches the model is its **feed**: a form DuckDB produces,
chosen by the user on `sq.Model` (ADR 0023). sqlearn knows nothing about any
model library; any model that takes the form works, and one that does not
fails with its own error.

### 3.1 The forms

```python
sq.Model(model)  # numpy, the default
sq.Model(model, feed="pandas")
sq.Model(model, feed="polars")
sq.Model(model, feed="arrow")
sq.Model(model, feed="stream")  # batches of about 100 MB
sq.Model(model, feed="stream", rows=100_000)  # batches of 100,000 rows
sq.Model(model, feed="stream", megabytes=256)  # batches of about 256 MB
```

| `feed=` | `fit(X, y)` gets | text columns |
|---|---|---|
| `"numpy"` (default) | a 2-D float64 array, as today | refused, as today |
| `"pandas"` | a DataFrame | `category` dtype |
| `"polars"` | a DataFrame | `Enum` (the build's change, [ADR 0041](../../adr/0041-the-hand-over.md)) |
| `"arrow"` | a `pyarrow.Table` | dictionary-encoded |
| `"stream"` | one batch at a time, as numpy, through `partial_fit` | refused |

- **The default stays `"numpy"`**, as the core has it.
- **Text columns reach the model as categories** with pandas, Polars and
  Arrow (decided 2026-11-07 with the plan): CatBoost, LightGBM, XGBoost
  (`enable_categorical`) and scikit-learn's histogram boosting
  (`categorical_features="from_dtype"`) all read that form, and CatBoost
  still takes `cat_features=` as it would without sqlearn. A NULL stays
  missing, never a category. Only `"numpy"` and `"stream"` keep today's
  refusal and its fix.
- **The target** goes over in the same form as the features (a Series, an
  Arrow array, a numpy array).
- Each form's library is imported only when used (ADR 0005); none becomes a
  runtime dependency.
- Further forms DuckDB produces (PyTorch tensors, say) can be added the same
  way later.

### 3.2 `"stream"`: models that learn in pieces

sqlearn streams the prepared relation from DuckDB (Arrow record batches) and
calls `partial_fit(X, y)` once per batch, scikit-learn's convention for
learning in pieces. Memory holds one batch, never the fold.

- **Batch size:** `rows=` or `megabytes=`, not both. With neither, about
  100 MB per batch, the row count worked out from the row's width in the plan
  (spec's call).
- **`epochs=1`:** the number of passes over the data.
- **The first call** is given `classes=` when the model needs it, computed in
  SQL.
- **Order** (spec's call): `shuffle=True` by default, with `seed=0`: rows
  come in the order of a hash of the row number with the seed and the epoch,
  so each epoch is a new order and the same seed gives the same orders. Data
  sorted by date or by class would otherwise train badly. `shuffle=False`
  keeps the input's order.
- A model without `partial_fit` is refused with a message suggesting another
  form.

### 3.3 Never swap

Before a form other than `"stream"` loads a fold into memory, sqlearn
estimates its size (rows × columns × bytes per value, from the plan) and
compares it with the memory it may use.

- **One budget for the process** (spec's call): `sq.set_config(memory=...)`,
  by default 80% of the machine's physical memory, found without a new
  dependency. On its own shared connection sqlearn sets DuckDB's
  `memory_limit` to half the budget, leaving the other half for the
  hand-over. A connection the user passed is never changed: sqlearn reads its
  `memory_limit` and allows the hand-over the budget minus that.
- When the fold will not fit, the train stops **before** fetching, with a
  message in ADR 0019's form naming the fold's size and the limit, and
  suggesting `feed="stream"` for a model with `partial_fit`. Swapping is
  never the fallback.

### 3.4 Predictions are always streamed

`predict` (in `Pipeline.predict`, in a search's scoring of each held-out fold,
and in `search.predict`) hands the model one batch at a time, whatever the
feed, and writes the predictions back to DuckDB as they come, aligned by row
number. A metric is then computed in SQL over the whole fold. Prediction never
needs the fold in memory (spec's call).

## 4. Keeping prepared folds: `keep_prepared`

As [#25](https://github.com/glaucis/sqlearn/issues/25) describes:

```python
search = sq.search(pipe, ..., keep_prepared="project.duckdb")
```

```
project.duckdb
└── schema sqlearn_prepared
    ├── _index                      # data, steps, settings, fold of each table
    ├── fold_0_7f3a91               # fold 0's prepared rows, with the fold column
    ├── fold_1_7f3a91
    └── ...
```

- Off by default. Given a path, each fold's prepared data is written once to a
  DuckDB file and read back for every trial; training reads the fold's
  training rows, scoring its held-out rows.
- **It works across sessions** (spec's call): the point is a second search
  tomorrow reusing today's preparation. The in-process store's keys do not
  survive a restart (connection tokens, step classes), so these tables get a
  key of their own, stable across processes: a file input by path, size and
  modification time; a pandas or Polars frame by the store's content hash; a
  DuckDB table in a database file by file, name and row count; each step by
  its qualified class name and settings; the fold scheme; and sqlearn's
  version. A change to the code of a user's own step is not seen; the guide
  says so, and `sq.store.clear(prepared=path)` is the fix. Inputs with no
  stable identity (a relation from an in-memory connection) are refused for
  `keep_prepared` with a message.
- A table's name carries that key in short, so a stale table is never reused
  for the inputs above. `_index` lists them;
  `sq.store.prepared(path)` shows them and `sq.store.clear(prepared=path)`
  removes them (spec's call).
- This is what makes Optuna (settings one at a time) and repeated searches
  avoid re-preparing; with grid, it lets a second search reuse the first's
  preparation.

## 5. Methods: how settings are picked

As ADR 0022 decided, over ask and tell:

- `sq.search.grid()`: every combination of lists, as today.
- `sq.search.random(trials=50, seed=0)`: draws from lists and ranges.
- `sq.search.optuna(trials=100, sampler=None, seed=0)`: Optuna's study through
  `ask(fixed_distributions=...)` and `tell(trial, score)`; lists become
  categorical distributions, `sq.search.range` becomes
  `FloatDistribution`/`IntDistribution` (integer bounds give integers, spec's
  call). Optuna is imported only when used.
- A range given to grid is refused, as today.
- Every method is seeded; the same seed gives the same trials and the same
  `results_`.

## 6. Folds: `sq.folds`

A fold scheme says, for each fold, which rows train and which are held out,
as SQL over the rows. No column is stored and the answer is the same in every
query.

| scheme | rows of fold k | for |
|---|---|---|
| `sq.folds.kfold(n=5, seed=0)` | today's `KFold`: a hash of the row's values and the seed | the default |
| `sq.folds.stratified(n=5, seed=0)` | each class of the target dealt evenly across the folds | classification |
| `sq.folds.group(by, n=5, seed=0)` | every row of a group (a customer) in the same fold, by a hash of the group | rows that are not independent |
| `sq.folds.time(by, n=5, gap=0)` | held out: the k-th of n consecutive periods of `by`; trained on everything before it | data ordered in time |
| `sq.folds.holdout(test=0.2, seed=0)` | one split | a quick check |

- The scheme is an object with a small interface (training rows and held-out
  rows of fold k, as expressions), so others plug in (spec's call).
- `stratified` needs the target, which the search already has.
- **`time`** (spec's call, as scikit-learn's `TimeSeriesSplit`): the rows,
  ordered by `by`, are cut into n + 1 chunks of equal row counts; fold k holds
  out chunk k + 1 and trains on chunks 0 to k, so early folds train on fewer
  rows. `gap` is a number of rows dropped between the training rows and the
  held-out ones. Rows sharing a value of `by` always fall in the same chunk:
  a boundary moves to the end of its tie.
- Folds dealt by value (`kfold`, `stratified`, `group`) keep the core's rule
  that identical rows share a fold; ADR 0038's row-position folds stay inside
  the target encoder.

## 7. Metrics

A search needs a metric for each kind of model, so this area adds the few a
search cannot do without (spec's call; the metrics area adds the rest):

- Regression: `rmse`, `mae`, `r2`.
- Classification: `accuracy` (today), `log_loss` and `roc_auc`, which read the
  model's `predict_proba`, streamed as in §3.4.
- **Two classes or more** (spec's call): probabilities come back as one
  column per class, in the order of the model's `classes_`. `log_loss` takes
  them all; `roc_auc` with more than two classes is one-vs-rest, averaged
  over the classes (scikit-learn's `multi_class="ovr"`, `average="macro"`).
  The metric interface grows from one prediction column to these.
- Each is computed in SQL and validated per ADR 0016.

## 8. Names: the groups

The search's names move into groups, as ADR 0034 does for the steps (spec's
call; needs an ADR, §11):

| today | becomes |
|---|---|
| `sq.Search(pipe, ...)` | `sq.search(pipe, ...)`: the group is callable, as `sq.impute` is |
| `sq.Grid()` | `sq.search.grid()` |
| `sq.range(...)` | `sq.search.range(...)` |
| — | `sq.search.random(...)`, `sq.search.optuna(...)` |
| `sq.KFold(5, seed=0)` | `sq.folds.kfold(5, seed=0)` |
| `sq.Model(...)` | unchanged: it stays at the top level, as `sq.Learned` and `sq.Output` do (ruling F5 of the preprocessing build); `feed=` is a string, as today |

The old names are removed, not kept as aliases: nothing is released yet.

## 9. Tests and validation

- **Against scikit-learn:** a grid and a random search give
  `GridSearchCV`'s scores and best settings when scikit-learn is given
  sqlearn's folds (`PredefinedSplit`) and, for random, the settings sqlearn
  drew, as a fixed list; `random` does not copy scikit-learn's sampler
  (spec's call). Each fold scheme
  against its scikit-learn twin (`StratifiedKFold`, `GroupKFold`,
  `TimeSeriesSplit`) on the properties that define it (class balance, groups
  kept together, order kept), since the assignment of rows differs.
- **Each form:** the same model trained through every form it takes gives the
  same predictions within bounds set from measurement; text columns reach a
  model through pandas, Polars and Arrow as categories (CatBoost and LightGBM as
  the test models, test-only).
- **Larger than memory:** §2's streamed pipeline under a memory limit several
  times smaller than the data, as the core's slow test: peak memory stays under
  a bound set from measurement, and the never-swap refusal (§3.3) fires for a
  form other than `"stream"`.
- **Reuse:** with `keep_prepared`, an Optuna search prepares each fold once
  (`transforms_`), and a second search on the same data and steps prepares
  nothing.
- **Metrics:** each against the mathematics and scikit-learn (ADR 0016).
- **Repeatable:** the same seeds give the same `results_`, byte for byte.
  Changed by [ADR 0043](../../adr/0043-repeatable-within-rounding.md): the same
  settings and best, each score within a measured bound of ULPs.

Test-only dependencies (catboost, lightgbm, optuna, pyarrow, polars) are
development dependencies with permissive licences, recorded as ADR 0005 asks.

## 10. Documentation

- A reference page per group (`sq.search`, `sq.folds`) and for `sq.Model` from
  the docstrings.
- Guide pages: tuning a model (methods, folds, metrics, `keep_prepared`), and
  handing data to models (each form, text columns, streaming, the memory limit).
- The scikit-learn name map gains the search's names.
- The core's guide pages, gallery example and docstrings rewritten in the new
  names.

## 11. Decisions to record

ADRs, written with the plan:

- The hand-over: the forms, text reaching the model as categories, streaming
  through `partial_fit`, never swap (§3).
- The search's names as groups (§8).
- Fold schemes as SQL over rows, including the time split (§6).

## 12. Done when

- §2's script runs end to end, and on data larger than memory within the
  bound of §9.
- §9's tests and validations pass in `just verify`, the slow tier included,
  with results committed under `validation/`.
- §10's documentation builds.

## 13. Not in this spec

- Models in SQL (ADR 0017).
- Pruning and early stopping of trials, parallel trials, multi-objective
  search, nested cross-validation.
- GPU training and distributed training.
- The rest of the metrics (the metrics area).
- Saving a search or a pipeline:
  [#20](https://github.com/glaucis/sqlearn/issues/20) and
  [#24](https://github.com/glaucis/sqlearn/issues/24).

## 14. Left to the builder

- The default batch size, and how the memory share is found on each platform.
- The size estimate's method, provided it errs towards refusing.
- Module layout, internal names and message text beyond ADR 0019's form.
- The order of the build; the renames (§8) come first.

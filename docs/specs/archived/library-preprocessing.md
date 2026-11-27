---
type: spec
tags: [preprocessing, library-breadth, api, aggregates, impute, scale, encode, transform, bin, features]
summary: "Spec for the first area of sqlearn's library breadth (overview 3.3): the grouped API, the aggregates group, and the first preprocessing steps chosen to exercise every part of the step contract, validated against scikit-learn."
related: [docs/architecture/overview.md, docs/specs/archived/library-core.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md, docs/adr/0016-validation-method.md, docs/adr/0032-the-median-is-exact-by-sorting.md, docs/adr/0033-the-mean-is-summed-with-compensation.md]
---
# Library breadth: preprocessing

The first area of part 3.3 of [the overview](../../architecture/overview.md).

Status: approved by Tomas on 2026-11-06. Written from the design talk of
2026-11-05; the decisions it rests on are
[ADR 0034](../../adr/0034-a-grouped-api.md) (a grouped API) and
[ADR 0035](../../adr/0035-names-of-generated-columns.md) (names of generated
columns). Where this spec makes a call of its own, it says "(spec's call)".

Built: see [the plan](../../plans/archived/2026-11-06-library-preprocessing.md)
and [issue #30](https://github.com/glaucis/sqlearn/issues/30), which tracks this
area.

## 1. Purpose

sqlearn will in time cover everything scikit-learn's preprocessing covers.
Users combine tested, verified steps rather than writing their own; the API
must make that easy to learn, easy to remember and short to type.

This spec does three things:

1. moves the core's public names into groups (ADR 0034), before any release;
2. adds `sq.agg`, the aggregates every step learns with, each validated once;
3. adds a first set of steps, a few from each family, chosen so that together
   they exercise every part of the step contract. When these work, the rest of
   scikit-learn's preprocessing is more of the same.

**Goals:** every step gives scikit-learn's answer (within bounds set from
measurement) and the exact mathematics' (ADR 0016); one way of writing each
thing; most steps need no arguments.

**Non-goals:** every scikit-learn step now; new kinds of preprocessing that
scikit-learn has not; a column-chain style (`sq.col("x").log()`), which does
not fit steps that learn and would be a second style to learn.

**Anti-goals:** a class hierarchy users must know (scikit-learn's
`TransformerMixin`, `BaseEstimator`); two names for the same behaviour that
behave differently; anything silently wrong.

## 2. The script this area must run

```python
import sqlearn as sq
from sklearn.linear_model import LogisticRegression

pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.impute("city", value="mode"),
        sq.transform.log1p("income"),
        sq.scale.robust(),
        sq.encode.onehot("city"),
        sq.encode.target("plan"),
        sq.bin.quantile("age", n=5),
        sq.features.polynomial("age", "income"),
        LogisticRegression(),
    ]
)

search = sq.Search(
    pipe,
    params={"robust__center": [sq.agg.median, sq.agg.mean], "model__C": [0.1, 1]},
    metric=sq.metrics.accuracy,
)
search.train("data/train/*.parquet", target="churned")
search.predict("data/new.parquet", out="pandas")
```

The core's slice (spec `library-core.md` §2) is rewritten in the new names and
must still pass.

## 3. The grouped API

Per [ADR 0034](../../adr/0034-a-grouped-api.md).

### 3.1 The map

| where | holds | from the core |
|---|---|---|
| `sq.` | `Pipeline`, `Step`, `Search`, `set_config`, `get_config` | the same |
| `sq.impute` | imputing steps (§5.1) | `sq.Impute` |
| `sq.scale` | scaling steps (§5.2) | `sq.Scale` |
| `sq.encode` | encoders (§5.3) | `sq.OneHot`, `sq.Ordinal` |
| `sq.bin` | discretisers (§5.4) | |
| `sq.transform` | transformations that learn nothing (§5.5) | |
| `sq.features` | feature makers (§5.6) | |
| `sq.agg` | aggregates (§4) | `sq.avg`, `sq.median`, `sq.stddev_pop`, `sq.count`, `sq.distinct_values` |
| `sq.cols` | selectors: `sq.cols("a", "b")`, `sq.cols.numeric()`, `sq.cols.string()` | `sq.cols`, `sq.numeric`, `sq.string` |
| `sq.fn` | SQL functions for one's own steps (§3.5) | `sq.const`, `sq.is_missing` |
| `sq.out` | `csv`, `json`, `parquet` | `sq.out_csv`, `sq.out_json`, `sq.out_parquet` |
| `sq.metrics` | `accuracy`, `Metric` | `sq.accuracy`, `sq.Metric` |
| `sq.errors` | `SqlearnError`, `StepError`, `InternalError`, `SqlearnWarning`, `DefaultsUsedWarning` | top level |
| `sq.store` | `clear()` ([#29](https://github.com/glaucis/sqlearn/issues/29)) | |

`Grid`, `KFold`, `range` and `Model` stay where they are until the
model-selection spec groups them (spec's call). The old names are removed, not
aliased: nothing is released (spec's call). Selectors keep `|`, `&`, `-`, `~`:
`cols=sq.cols.numeric() - sq.cols("id")`.

### 3.2 A step group

- A step group is callable for the general form,
  `sq.<group>(cols, method=..., **settings)`, and holds one shortcut per
  method: `sq.scale.robust(...)` is `sq.scale(..., method="robust")`. A
  shortcut builds exactly the step the general form builds with those
  settings: equal settings, equal store key, equal output, equal `repr`.
- A shortcut's own keywords are sugar for the general form's settings, never
  extra state: `sq.scale.robust(quantile_range=(25, 75))` is
  `sq.scale(method="robust", spread=sq.agg.iqr(q=(0.25, 0.75)))` (spec's
  call).
- `impute` has no `method=`: its general form is `value=` (§5.1), and each
  shortcut is a preset of it.
- Tab completion and `help()` on a group list its shortcuts with one line
  each.
- The step's `repr` is the shortest form that rebuilds it
  (`sq.scale.robust(cols=['age'])`), and its settings are its `__init__`
  arguments under their own names, as the core requires (core §3.1).

### 3.3 Columns first

Every step group takes the columns first, positionally:

```python
sq.scale.robust()  # the group's default columns
sq.scale.robust("age")  # one
sq.scale.robust("age", "income")  # several
sq.scale.robust(["age", "income"])  # a list
sq.scale.robust(cols=sq.cols.numeric() - sq.cols("id"))  # a selector
sq.impute({"age": "median", "income": "mean", "city": "unknown"})  # a dict
```

- Positional names and `cols=` together are refused with a message.
- **Defaults:** numeric steps (impute by an aggregate, scale, bin, numeric
  transforms, feature makers) default to `sq.cols.numeric()`; encoders to
  `sq.cols.string()`; text transforms (`lower`, `upper`) to
  `sq.cols.string()`; `sq.impute(value=<constant or "mode">)` to every
  column its value suits (spec's call).
- **A dict** gives each column its own setting, for `sq.impute` (`value=`)
  and `sq.scale` (`method=`) only, where every choice is the same kind of
  step: static, learning per column, never from the target. It is one step:
  it learns in one stage and has one name. Other groups refuse a dict, since
  mixing, say, `onehot` and `target` would make one step both dynamic and
  target-learning. A search over a dict step's per-column setting is refused
  with a message saying to use one step per column (spec's call).

### 3.4 Pipelines

- `sq.Pipeline([step, step, ..., model])` takes a plain list; `(name, step)`
  pairs still work and may be mixed with plain steps.
- **Names:** a step is named after the shortcut its settings match
  (`robust`, `median`, `onehot`), else after its group (`impute`, `scale`);
  a model `model`. A shortcut and the general form build equal steps, so
  `sq.scale(method="robust")` is named `robust` too (spec's call). Clashes
  are numbered from 1 (`median-1`, `median-2`). These names key `params`
  (`robust__center`) and `pipe["robust"]` (spec's call).
- `sq.make_pipeline` is removed: a plain list does its job (spec's call).

### 3.5 One's own step

The one way to write a step without a subclass is `sq.Step` with callables:

```python
sq.Step(apply=lambda x: sq.fn.ln(x + 1), cols=["income"])
sq.Step(
    learn=lambda x: {"top": sq.agg.max(x)},
    apply=lambda x, learned: x / learned.top,
)
```

- The callables follow the core's contract (core §3.1); a subclass still works
  and is the form for a step with settings of its own.
- Its name in a pipeline is `step` (numbered on a clash); its store key uses
  the callables' identity, so redefining a lambda relearns (as ADR 0024's
  class identity; spec's call).
- `sq.fn` holds the SQL functions such steps need: at least `const`,
  `is_missing`, `ln`, `log10`, `exp`, `sqrt`, `abs`, `least`, `greatest`,
  `lower`, `upper`, `coalesce`, and every function a built-in step of this
  spec uses. Each builds a DuckDB expression object (ADR 0015).

## 4. Aggregates: `sq.agg`

### 4.1 The set

| aggregate | is | scikit-learn / numpy counterpart |
|---|---|---|
| `mean` | compensated mean, `favg` (ADR 0033) | `np.mean` |
| `median` | exact, by sorting (ADR 0032) | `np.median` |
| `quantile(q, method="linear")` | exact, by sorting | `np.quantile(method=...)` |
| `approx_quantile(q)` | DuckDB's `approx_quantile` | none: approximate by name |
| `iqr(q=(0.25, 0.75))` | `quantile(q[1]) - quantile(q[0])` | RobustScaler's `quantile_range` |
| `mode` | most frequent value; ties to the smallest | SimpleImputer `most_frequent` |
| `min`, `max` | | |
| `range` | `max - min` | MinMaxScaler's spread |
| `maxabs` | `max(abs(x))` | MaxAbsScaler's spread |
| `std`, `var` | population (`ddof=0`) | StandardScaler's |
| `count` | non-missing values | |
| `distinct` | sorted distinct values, without NULL and NaN | the encoders' categories |

- **Missing values** (NULL, and NaN in a float column) are left out of every
  aggregate, as scikit-learn's imputers and scalers leave them out. With no
  value left, the result is NULL; the step using it decides (Impute refuses an
  all-missing column, as the core does).
- **Quantile methods:** `method=` takes numpy's names. This spec builds
  `"linear"` (numpy's default, used by `robust` and `spline`) and the method
  the pinned scikit-learn's `KBinsDiscretizer` uses by default, which
  `bin.quantile` learns with; each is validated (§4.3). Others come when a
  step needs them (spec's call).
- **Exact means exact:** `median`, `quantile` and `iqr` sort, as ADR 0032
  does, and share one sort per learn stage. `approx_quantile` is never chosen
  for the user; there is no `approx_median` (Tomas, 2026-11-05):
  `approx_quantile(0.5)` is the approximate median.
- `std` is two compensated passes since
  [#28](https://github.com/glaucis/sqlearn/issues/28)
  ([ADR 0044](../../adr/0044-the-standard-deviation-in-two-staged-passes.md)),
  and every step using it improved at once; `var` has been the same two staged
  passes since [#42](https://github.com/glaucis/sqlearn/issues/42), not DuckDB's
  `var_pop`.

### 4.2 Two uses, one name

```python
sq.impute("age", value=sq.agg.median)  # as a value given to a step
sq.impute("age", value=sq.agg.quantile(q=0.9))  # a parameterised value
learn = lambda x: {"m": sq.agg.median(x)}  # on a column, in one's own step
learn = lambda x: {"p": sq.agg.quantile(x, q=0.9)}
```

- An aggregate given a column builds the expression; without one it is a
  value a step takes. A parameterised aggregate takes its parameter by
  keyword (spec's call).
- An aggregate's `repr` is stable and rebuilds it (`sq.agg.quantile(q=0.9)`),
  so it can be a setting in a store key and in a search.
- **Strings:** a string naming an aggregate is that aggregate (`"median"` is
  `sq.agg.median`). Any other string is a constant. `sq.fn.const("median")` is
  the literal text (Tomas, 2026-11-05).

### 4.3 Validated once

Each aggregate is validated per ADR 0016 on its own (a value at 50 digits,
DuckDB alone and at one thread, numpy, scikit-learn and pandas where they have
it), with its results under `validation/sqlearn/agg/`. `approx_quantile` has
no bound to pass: its error against the exact quantile is measured and
recorded per dataset, so it is a known number.

## 5. The steps

Each step: its general form and shortcuts, what it learns, what it applies,
its scikit-learn counterpart, and the edge cases it specifies and tests
(NULL, NaN, an all-missing column, a constant column, a value at `apply` not
seen at `learn`, reserved words and spaces in names; core §3.5). Defaults
follow scikit-learn's unless this spec says otherwise.

### 5.1 `sq.impute`

General form: `sq.impute(cols, value=..., indicator=False)`. `value` is an
aggregate, an aggregate's name, a constant, or None (no filling).
`indicator=True` adds `<column>_missing` (0/1) beside the filled column, as
scikit-learn's `add_indicator=True`.

| shortcut | value | scikit-learn |
|---|---|---|
| `mean`, `median` | `sq.agg.mean`, `sq.agg.median` | `SimpleImputer(strategy=...)` |
| `mode` | `sq.agg.mode`, text columns too | `strategy="most_frequent"` |
| `constant(v)` | the constant `v` | `strategy="constant", fill_value=v` |
| `indicator` | `value=None, indicator=True` | `MissingIndicator` |

- `indicator=True` makes the step dynamic: as scikit-learn's default
  `features="missing-only"`, it creates a column only for the columns that had a
  missing value at `learn` (ADR 0035 names it). It keeps the input columns.
- A constant whose type does not suit the column (text into a number) is
  refused at `learn`, naming both.
- `mode` on an all-missing column is refused, as `mean` and `median` are.

### 5.2 `sq.scale`

General form: `sq.scale(cols, method="standard", center=..., spread=...,
feature_range=None, norm="l2")`. For every method but `normalize` it applies
`(x - center) / spread`, then, with `feature_range=(a, b)`, `* (b - a) + a`.
`method` gives `center` and `spread` their defaults (the table); given ones
replace them, so `sq.scale.robust(center=sq.agg.mean)` is still `robust`.
`center=None` means 0; `spread=None` means 1.

| shortcut | center | spread | scikit-learn |
|---|---|---|---|
| `standard` | `mean` | `std` | `StandardScaler` |
| `robust` | `median` | `iqr` | `RobustScaler` |
| `minmax` | `min` | `range` | `MinMaxScaler` (range 0 to 1) |
| `maxabs` | None | `maxabs` | `MaxAbsScaler` |
| `normalize(norm="l2")` | across the row | | `Normalizer` |

- A spread of 0 is treated as 1, as scikit-learn does; infinity is refused
  (ADR 0030).
- `minmax` defaults `feature_range` to `(0, 1)`, as scikit-learn's; the
  other methods default it to None.
- `normalize` takes `norm=` and refuses `center`, `spread` and
  `feature_range`.
- `normalize` divides each row's selected values by that row's norm (`l1`,
  `l2`, `max`); it learns nothing. It is the first step whose output for one
  column reads the other columns of the row (§6.1). A row of zeros stays zeros,
  as scikit-learn's.
- `robust`'s quantile range is `(25, 75)` by default and settable, as
  scikit-learn's `quantile_range`.

### 5.3 `sq.encode`

General form: `sq.encode(cols, method="onehot", **settings)`.

| shortcut | scikit-learn | note |
|---|---|---|
| `onehot` | `OneHotEncoder(handle_unknown="ignore")` | the core's `OneHot`, renamed |
| `ordinal` | `OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)` | the core's `Ordinal`, renamed |
| `target` | `TargetEncoder` | learns from the target (§6.2) |

- `target` covers a binary and a continuous target in this spec; a
  multiclass target (one column per class) comes later (spec's call). Its
  smoothing (`smooth="auto"`) and its cross-fitting follow scikit-learn's
  formulae.
- Encoders have no `suffix=` and no case option (ADR 0035).

### 5.4 `sq.bin`

General form: `sq.bin(cols, method="quantile", **settings)`.

| shortcut | learns | scikit-learn |
|---|---|---|
| `uniform(n=5)` | `min`, `max` | `KBinsDiscretizer(strategy="uniform", encode="ordinal")` |
| `quantile(n=5)` | the `n - 1` inner quantiles, exact | `KBinsDiscretizer(strategy="quantile", encode="ordinal")` |
| `binarize(threshold=0.0)` | nothing | `Binarizer` |

- A bin is written as its index, an integer from 0 (scikit-learn's
  `encode="ordinal"`; spec's call: one-hot bins are `sq.encode.onehot` after
  it, not an option here).
- Quantile edges follow the quantile method of the pinned scikit-learn's
  default (scikit-learn 1.9 changed it); the builder records which. Duplicate
  edges are merged, as scikit-learn does, and so is the warning.
- `binarize` writes 1 where `x > threshold`, else 0; NULL stays NULL.

### 5.5 `sq.transform`

General form: `sq.transform(cols, method=..., **settings)`; `method` has no
default. None of these learns; each is static and chains into the stage
around it.

| shortcut | SQL | note |
|---|---|---|
| `log` | `ln(x)` | |
| `log1p` | `ln(1 + x)` | numpy's `log1p` |
| `sqrt` | `sqrt(x)` | |
| `clip(lower=None, upper=None)` | `least(greatest(x, lower), upper)` | numpy's `clip` |
| `lower`, `upper` | `lower(x)`, `upper(x)` | text columns |

- **Bad input is refused, not passed on:** numpy gives `-inf` or `nan` with a
  warning for `log(0)`, `log(-1)`, `sqrt(-1)`; these steps stop with a message
  naming the step, the column and the fix (for example `clip` first, or
  `log1p`), raised by DuckDB's `error()` inside the expression when the value
  is met (spec's call, as ADR 0030 refuses infinity). NULL stays NULL.
- Any other transformation is `sq.Step(apply=...)` (§3.5); there is no
  `sq.transform.custom`.

### 5.6 `sq.features`

General form: `sq.features(cols, method=..., **settings)`; `method` has no
default.

| shortcut | creates | scikit-learn |
|---|---|---|
| `polynomial(degree=2, interaction_only=False)` | `a`, `b`, `a^2`, `a*b`, `b^2` | `PolynomialFeatures` |
| `spline(n_knots=5, degree=3)` | `x_sp_0` ... `x_sp_6` | `SplineTransformer` |

- `polynomial` learns nothing and its names are known from its inputs: a
  static step returning several columns, declared static. `include_bias`
  defaults to False, unlike scikit-learn, since every model sqlearn feeds
  fits its own intercept (spec's call).
- `spline` learns the knots (uniform between `min` and `max`, or at
  quantiles with `knots="quantile"`), writes the B-spline basis as SQL, and is
  static: the number of columns follows from its settings.
  `extrapolation="constant"` is scikit-learn's default and the only one in
  this spec (spec's call).
- `polynomial` reads several input columns to write each output, a
  whole-row step (§6.1); `spline` works per column, one input making several
  outputs.

## 6. What these steps add to the contract

The core's contract is one column in, one expression (or a mapping) out
(core §3.1). The steps above need three things it does not have. Each is
declared as data, so the planner and later the node editor read it.

### 6.1 Steps that read the whole row

`normalize` and `polynomial` write an output from several input columns of
the same row. The contract gains a form whose `apply` receives
every selected column at once and returns the output columns; the planner
treats each output as reading every selected input. The name and signature
are the builder's; one's own step can use it too.

### 6.2 Steps that learn from the target

`encode.target` learns the target's mean per category. The core sets the
target aside so no step sees it (core §7); this spec lets a step declare that
it uses the target:

- only that step's `learn` sees it. `train` and a search give the target as
  they do now; `Pipeline.learn` gains `target=` (as scikit-learn's
  `TargetEncoder.fit(X, y)`), needed only when a step uses it. `learn`
  without `target=` refuses such a step with a message; `apply` needs no
  target;
- the target is never in a step's output and never matched by a selector;
- **cross-fitting:** in `train`, the rows the model trains on are encoded with
  values learned without their own fold, as scikit-learn's `fit_transform`
  does; `predict`, and `apply` after `learn(..., target=)`, use the values
  learned on all rows (`learn` then `apply` is scikit-learn's `fit` then
  `transform`: no cross-fitting). The inner folds are sqlearn's own hash
  folds (core §10), and inside a search they are taken within the outer
  fold's training rows;
- **steps after it learn from the cross-fitted output** in `train`, as in
  scikit-learn's `Pipeline.fit`, so a scaler after `encode.target` gives
  scikit-learn's answer. A target-learning step therefore ends a run, like a
  dynamic step; its store entry holds the values learned on all rows and on
  each inner fold's complement, and the data reaching later learn stages
  takes each row's values from its own fold (spec's call);
- the store key holds the target column's name, and its data key the same
  data.

scikit-learn's inner folds are random by default, but `TargetEncoder(cv=...)`
takes a list of splits. Validation hands scikit-learn sqlearn's own folds, as
splits, so the cross-fitted values, the values learned on all rows, and the
whole pipeline are compared row for row (spec's call).

### 6.3 Steps that create columns only for some inputs

`impute.indicator` creates a column for an input only when that input had a
missing value at `learn`. It is dynamic, declaring its created type
(integers), as OneHot is.

## 7. Column names

Per [ADR 0035](../../adr/0035-names-of-generated-columns.md): one shared piece
of code names every created column (`<column>_<label>`, clashes numbered
without regard to case, `<column>_NULL` for missing, `keep=True` as
`<column>_<step name>`, scikit-learn's labels for feature makers), and every
step that creates columns uses it.

## 8. Measure, then decide: OneHot as a list column

[Issue #22](https://github.com/glaucis/sqlearn/issues/22): before deciding
whether OneHot should write one list column to save a run, the build measures
what the second run costs. It records, on generated data at the sizes ADR 0016
uses and on one dataset larger than the memory limit, the time and the reads
of the core's slice with OneHot as it is. The decision is Tomas's, after the
numbers.

## 9. Tests and validation

As the core's (core §13), for every step and aggregate here:

- **Against scikit-learn:** each step alone and the §2 script give
  scikit-learn's answer within bounds set from measurement, with scikit-learn
  given sqlearn's folds as splits (`GridSearchCV(cv=...)`,
  `TargetEncoder(cv=...)`), including
  `get_feature_names_out` against `columns_out_` where names follow
  scikit-learn (feature makers), and recorded divergences where they do not
  (ADR 0035's NULL).
- **Against the mathematics:** each aggregate (§4.3) and each formula a step
  adds (spline basis, target smoothing, norms).
- **Shortcuts are the general form:** for every shortcut, the step it builds
  equals the general form's in settings, store key and output.
- **The contract additions** (§6): runs and store reuse for whole-row steps,
  target-learning steps in `train`, a search and a refused `learn`, and
  column-creating steps that create none.
- **Names:** the clash cases of ADR 0035 (case, `'NULL'` beside NULL, a
  created name equal to an input name).
- **Larger than memory:** the §2 script's preparation under a memory limit
  smaller than the data, as the core's slow test.
- The mirror stays enforced: each step has a test file and a validation
  runner.

## 10. Documentation

- A reference page per group, from the docstrings, every shortcut with an
  example.
- A user guide page per family (imputing, scaling, encoding, binning,
  transforming, making features), and one on column names (ADR 0035).
- A page mapping every scikit-learn name to sqlearn's
  (`SimpleImputer(strategy="median")` → `sq.impute.median()`), growing with each
  area.
- The core's guide pages, gallery example and docstrings rewritten in the new
  names.

## 11. Done when

- §2's script and the core's slice, in the new names, run end to end.
- §9's tests and validations pass in `just verify`, the slow tier included,
  with their results committed under `validation/`.
- §8's numbers are recorded and handed to Tomas.
- §10's documentation builds.

## 12. Not in this spec

- `KNNImputer` (nearest neighbours in SQL), `IterativeImputer` (a model per
  column), `PowerTransformer` (an optimisation to fit), `QuantileTransformer`
  (the same sorting as `robust`, added later), k-means bins: later areas of
  preprocessing.
- A multiclass target for `encode.target`.
- Grouping the search's names (`Grid`, `KFold`, `range`, `Model`): the
  model-selection spec, with [#21](https://github.com/glaucis/sqlearn/issues/21)
  and [#25](https://github.com/glaucis/sqlearn/issues/25).
- Saving: [#20](https://github.com/glaucis/sqlearn/issues/20) and
  [#24](https://github.com/glaucis/sqlearn/issues/24).

## 13. Left to the builder

- How a group is made callable with shortcuts, provided tab completion,
  `help()` and the type checker all see the shortcuts.
- The form of the whole-row contract (§6.1) and of a step's target
  declaration (§6.2).
- Module layout, internal names, and message text beyond ADR 0019's form.
- The order in which the steps are built; the renames (§3.1) come first.

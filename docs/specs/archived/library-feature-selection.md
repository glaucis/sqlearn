---
type: spec
tags: [feature-selection, library-breadth, select, variance-threshold, select-k-best, target]
summary: "Spec for feature selection in sqlearn (overview 3.3): sq.select.variance, sq.select.best and sq.select.percentile with the f_classif, f_regression and chi2 scores, as scikit-learn 1.9.1's VarianceThreshold, SelectKBest and SelectPercentile, computed in SQL, with a target step that does not cross-fit (ADR 0055)."
related: [docs/architecture/overview.md, docs/specs/archived/library-preprocessing.md, docs/adr/0055-a-target-step-need-not-cross-fit.md, docs/adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0034-a-grouped-api.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0016-validation-method.md]
---
# Library breadth: feature selection

The ninth area of part 3.3 of [the overview](../../architecture/overview.md),
after the [regression metrics](library-regression-metrics.md).

Status: approved by Tomas on 2026-11-19.
The decisions it rests on are
[ADR 0055](../../adr/0055-a-target-step-need-not-cross-fit.md) and
[ADR 0056](../../adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md).
The cross-fitted alternatives are kept as an idea in
[#64](https://github.com/glaucis/sqlearn/issues/64).

## 1. Purpose

Wide data carries columns that tell a model nothing: a column that never
changes, or one with no relation to the target. Dropping them before the model
makes training cheaper and the model simpler. In sqlearn the scores are
computed where the data is, in DuckDB, so selection works on data larger than
memory, and the model receives only the columns kept.

## 2. What it looks like

```python
pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.select.variance(),  # drop constant columns
        sq.select.best(k=10, score="f_classif"),  # the 10 best by ANOVA F
        LogisticRegression(),
    ]
)
pipe.train("data/train/*.parquet", target="churned")
pipe.predict("data/new.parquet")

sq.select.percentile(percentile=20, score="f_regression")  # the best 20%
sq.select.best(k=5, score="chi2")  # counts, frequencies

sq.search(pipe, params={"best__k": [5, 10, 20]}, metric=sq.metrics.f1)
```

`learn(data, target=...)` then `apply` works as for `sq.encode.target`.

## 3. Rules

1. **They behave as scikit-learn 1.9.1's** `VarianceThreshold`,
   `SelectKBest`, `SelectPercentile`, `f_classif`, `f_regression` and `chi2`:
   the same columns kept, the same scores, defaults and edge rules. Where this
   text and scikit-learn disagree, scikit-learn is built and this spec is
   corrected.
2. **Everything is computed in SQL** by DuckDB: what comes back to Python is a
   few numbers per column (and per class). The ranking of those numbers may be
   done in Python.
3. **sqlearn warns and the user chooses** (ADR 0046): where scikit-learn warns,
   sqlearn warns too, with a `Fix:` line.

## 4. The group: `sq.select`

A step group (ADR 0034) with three shortcuts, and callable for its general form:
`sq.select(*names, method="variance", ...)` builds the same step each shortcut
builds, and refuses a setting that does not belong to `method`. A positional is
a column name, one list of names or a column selector (`sq.cols.numeric()`,
as the other groups take; #65): anything else (`sq.select.percentile(20)`)
is refused at the call, with a `Fix:` line naming the setting
(`percentile=20`), rather than taken as a column. Each selector is
a dynamic step: the columns it outputs depend on what it learned. A column kept
passes through unchanged (its name, type and values); a column dropped is gone.
Its `cols` default to the numeric columns, and it refuses a chosen column that
is not numeric, with a `Fix:` line naming an encoder. The learned values
readable after `learn` follow scikit-learn's: `variances_` for `variance`,
`scores_` (and for the F scores `pvalues_`, see §6) for the others, keyed by
column as other steps' learned values are, and `columns_out_` names what was
kept.

### 4.1 `sq.select.variance(threshold=0.0)`

As `VarianceThreshold`: learns each column's population variance and keeps a
column whose variance is above `threshold`. Missing values (NULL, NaN) are
ignored, as scikit-learn's `nanvar` ignores NaN. At `threshold=0.0`
scikit-learn takes the smaller of the variance and the column's range (peak
to peak), so a constant column is dropped whatever the rounding of its
variance: so does sqlearn. A column with a missing value has no range there
(numpy's `ptp` is NaN, and `nanmin` takes the variance), so its variance
alone decides: so it does in sqlearn, whose learned `low` and `high` are NULL
for such a column. An infinite value is refused at learn, naming the column,
as scikit-learn's input check refuses it and as the scores refuse one (§4.4):
the step learns a count of infinite values, as the scores do, since the
variance would otherwise be infinite or NaN and keep the column at one
threshold and drop it at another (ruling of 2026-11-20, after the final
review). A negative threshold is refused at the call, as
scikit-learn's parameter check refuses it. If no column passes, the step
raises, as scikit-learn raises, naming the threshold and the largest variance
learned. It does not read the target.

### 4.2 `sq.select.best(k=10, score="f_classif")`

As `SelectKBest`: learns each column's score against the target and keeps the
`k` highest. A NaN score ranks lowest. Ties are broken as scikit-learn's
stable sort breaks them: among equal scores the later column is kept. `k`
greater than the number of columns keeps them all and warns, as scikit-learn
warns; `k=0` keeps none and warns, as scikit-learn warns; `k="all"` keeps all.
A negative or non-whole `k` is refused at the call, and so are `True` and
`False`, which scikit-learn takes as 1 and 0 (as `variance` refuses a boolean
threshold).

**When nothing would remain (spec's call, 2026-11-19).** A feature selector
that keeps none of its columns (`k=0`, `percentile=0`) keeps none and warns,
as scikit-learn, as long as other columns pass beside it. When it would leave
no column at all, `learn` raises with a `Fix:` line, as `variance` raises
when nothing passes: a table with no column cannot exist in DuckDB (the core
refuses a stage with none), and scikit-learn's model would refuse it next.
In a search, that setting fails the search with the setting and the fold
named, as a model that fails to fit does today.

### 4.3 `sq.select.percentile(percentile=10, score="f_classif")`

As `SelectPercentile`: keeps the columns whose score is above the
`100 - percentile` percentile of the scores (numpy's linear interpolation),
then, among the columns whose score equals that percentile, the earliest ones
until `int(n * percentile / 100)` columns are kept. 100 keeps all and 0 keeps
none (with scikit-learn's warning). A NaN score ranks lowest, as for `best`.
A percentile outside 0 to 100 is refused at the call.

### 4.4 The scores

`score=` is a name, so a saved pipeline stays plain data (ADR 0047):

| `score=` | Target | Per column it learns | scikit-learn |
|---|---|---|---|
| `"f_classif"` | classes (any type) | per class: count, sum, sum of squares | `f_classif`: the ANOVA F |
| `"f_regression"` | a number | count, the variances of the column and the target, their covariance | `f_regression(center=True, force_finite=True)`: the F of the correlation |
| `"chi2"` | classes | per class: the sum of the column; the class counts | `chi2`: observed against expected sums |

- `f_classif` of a constant column is NaN (it ranks lowest), as scikit-learn's,
  which also warns that the column is constant: so does sqlearn, once per step
  and naming the constant columns. scikit-learn's wider condition (it also
  names a column constant within each class, whenever some column's
  between-class spread is 0) is not copied: it is a warning, not a result.
- `f_regression` with `force_finite=True`: a constant column or a constant
  target scores 0, at two rows every column scores 0, and an F that comes out
  infinite (a correlation of 1 or -1 in the variances and the covariance
  learned) scores the largest double.
- **The exact score (Tomas, 2026-11-19).** sqlearn combines what it learned
  exactly (the per-class sums of the column less its minimum; the variances and
  the covariance), so its score departs from the exact one only by the rounding
  of those sums. Where scikit-learn's own rounding departs from it, sqlearn
  gives the exact score, and the columns kept can then differ: a constant 0.1
  scores NaN for `f_classif` (scikit-learn's sums leave -0.0); a column far from
  zero, such as 1e6 plus noise, scores within rounding of the exact value for
  `f_classif` and `chi2`, where scikit-learn's cancellation is about 1% off
  (`f_classif` 0.37616 exact against 0.38044); for `f_regression` it keeps about
  9 significant digits there (1.5e-9 relative, from DuckDB's covariance and
  variance, §6), against scikit-learn's 0.15% (2.41271 exact against 2.41348).
  An exactly linear column scores the largest double for `f_regression` when the
  learned variances and covariance come out consistent, and otherwise a large
  finite F (2y + 1 over 60 rows: about 4e17), far above any column that is not
  linear; scikit-learn's r² can round just below 1 (a large finite F) or above
  it (a negative F, which ranks lowest).
- `chi2` refuses a negative value in a scored column, as scikit-learn refuses
  it, with a `Fix:` line (`sq.scale.minmax`, or `f_classif`).
- A missing value (NULL, NaN) in a scored column is refused for all three, as
  scikit-learn refuses NaN, with a `Fix:` line (`sq.impute` before the step).
  So is an infinite value, as scikit-learn's input check refuses infinity,
  and a missing or infinite target value.
- Other scores (`mutual_info_*`, `r_regression`) are not in this spec (§9).

## 5. The contract: a target step that does not cross-fit

[ADR 0055](../../adr/0055-a-target-step-need-not-cross-fit.md): today a step
that learns from the target (`uses_target`) is cross-fitted, as
`sq.encode.target` is: it has `cv` and `seed`, ends its run, and its `apply`
returns one DOUBLE. This area splits "learns from the target" from
"cross-fits":

- a step can learn from the target and not cross-fit. It has no `cv` or
  `seed`, it learns once on the rows given (in a search, on each outer fold's
  training rows, as `GridSearchCV` refits `SelectKBest` per fold), and its
  `apply` is any output a step may give, a dynamic one included;
- `sq.encode.target` keeps cross-fitting, unchanged in behaviour, store keys
  and saved files;
- everything else §6.2 of the preprocessing spec says of target steps holds
  for both: only the step's `learn` sees the target, `learn` without
  `target=` refuses the step, the target is never in an output and never
  matched by a selector, and the store key holds the target's name;
- `best` and `percentile` need what was learned for every column at once to
  rank them: they use the whole-row form (preprocessing §6.1), whose
  `apply_row` receives every selected column's learned values.

The form of the declaration is the builder's (§10).

### 5.1 Statistics per class

`f_classif` and `chi2` need, for each column, sums taken per class of the
target, in the one learn statement. The core's learn stage computes
aggregates over all rows (and `sq.encode.target`'s grouped marker groups by
category and inner fold). How the per-class sums are computed (a grouped
marker keyed by the target, a filtered aggregate per class learned first, or
another form) is the builder's, provided the data is read once per run, the
number of classes is not fixed in advance, and a run's SQL text grows with
the number of columns, not with columns times classes (spec's call,
2026-11-19): so not one filtered aggregate per class and column.

### 5.2 Learned once per fold

[ADR 0056](../../adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md)
(Tomas, 2026-11-19): `k`, `percentile` and `threshold` change only which
columns are kept, never what is learned, so they stay out of the key of what
the step learns. A search over `best__k` with five folds learns each fold's
scores once and keeps 5, 10 or 20 columns from them; preparing each setting's
data for the model still happens per setting, as for any step. `score`
changes what is learned and stays in the key. The answer is scikit-learn's,
which refits for each `k` and gets the same scores.

## 6. Numbers and p-values

- `f_classif` and `chi2` are computed from compensated sums (`fsum`, ADR
  0033) of the column less its minimum, combined exactly. `f_regression` uses
  DuckDB's covariance and variance (`covar_pop`, `var_pop`: a running update
  about the mean, as `r2`'s total sum of squares). Both are held within
  bounds set by the validation runner's measurement against exact values
  (ADR 0016).
- scikit-learn's `pvalues_` need the F and chi² distributions. They select
  nothing in this spec (selection by p-value is §9), so sqlearn does not
  compute them: the step has no `pvalues_`, and its reference page says so.
  If they are wanted later, they come with the p-value selectors.

## 7. Tests and validation

- **Against scikit-learn:** each selector with each score, on generated data
  (classes of several types, numbers, counts), keeps the same columns in the
  same order, and its learned scores match `scores_` within bounds; the edge
  rules of §4 (ties, NaN scores, `k` above the count, `k=0`, percentile ties,
  `threshold=0` on a constant column, no column passing) one test each.
- **Against the mathematics:** each score against exact fractions, in a
  validation runner `validate_select` (ADR 0016).
- **In a pipeline and a search:** `train` then `predict` gives scikit-learn's
  `Pipeline` its predictions; a search over `k` picks scikit-learn's
  `GridSearchCV` setting on sqlearn's folds; the store reuses a learned
  feature selector; a later step's column selector sees only the kept
  columns.
- **Learned once per fold (§5.2):** a search over `k` (and over `percentile`,
  `threshold`) runs one learn statement per fold, counted as the core's tests
  count runs; a search over `score` learns per setting; a later step reading
  the kept columns is keyed with `k`.
- **The contract (§5):** a target step that does not cross-fit learns on all
  rows in `train`; `sq.encode.target`'s behaviour and store keys unchanged.
- **Saving:** `sq.save` then `sq.load` of a pipeline with each selector gives
  the same output.
- **Larger than memory:** one selector learned on data larger than the memory
  limit, as the earlier areas' slow tests.

## 8. Documentation

- A reference page per selector, from the docstrings, with examples.
- A user guide page, "Selecting features", in the guide's order after
  "Making features".
- The scikit-learn mapping page: `VarianceThreshold` → `sq.select.variance`,
  `SelectKBest(f_classif, k=10)` → `sq.select.best(k=10, score="f_classif")`.
- `GLOSSARY.md`: "selector" is already a column selector (`sq.cols`), so a
  step of `sq.select` is a **feature selector** in prose, never a "selector".

## 9. Not in this spec

- Mutual information (`mutual_info_classif`, `mutual_info_regression`): it
  rests on nearest neighbours, which do not fit SQL.
- Selection by a model (`SelectFromModel`, `RFE`, `RFECV`,
  `SequentialFeatureSelector`): models come from other libraries (ADR 0017).
- Selection by p-value (`SelectFpr`, `SelectFdr`, `SelectFwe`,
  `GenericUnivariateSelect`) and `pvalues_`: they need the F and chi²
  distributions in Python; a later area.
- `r_regression` as a score.
- A cross-fitted feature selector: kept as an idea in #64.
- Multi-output targets.

## 10. Left to the builder

- The form of a target step's declaration that it does not cross-fit (§5),
  and of the per-class statistics (§5.1).
- Whether `variance` uses the whole-row form or the per-column one.
- The form of the declaration of settings that stay out of the learn key
  (§5.2), and how the store holds the learned values apart from the output.
- Module layout, internal names, and message text beyond ADR 0019's form.
- The order of the work; the contract change (§5) comes first.

## 11. Done when

- §2's examples run end to end.
- §7's tests and validations pass in `just verify`, the slow tier included,
  with their results committed under `validation/`.
- §8's documentation builds.

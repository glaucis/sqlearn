---
type: task
tags: [metrics, precision, recall, f1, averaging, search, validation, library-breadth]
summary: "Implementation plan for the metrics area of sqlearn's library breadth: precision, recall and F1 with scikit-learn's average, pos_label and zero_division, counted per class in DuckDB, NaN scores in the search, validation against scikit-learn, and the docs, in 6 tasks."
related: [docs/specs/library-metrics.md, docs/adr/0042-a-metrics-settings-are-a-call.md, docs/adr/0016-validation-method.md, docs/adr/0019-custom-steps-and-failure-feedback.md]
---
# Library Breadth: Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `sq.metrics.precision`, `recall` and `f1`, behaving as
scikit-learn 1.9.1's `precision_score`, `recall_score` and `f1_score` (the
same `average`, `pos_label` and `zero_division`, defaults and refusals), with
every count computed in DuckDB, usable on their own and in a search.

**Architecture:** A new module `metrics/classification.py` holds
`ClassificationMetric`, a subclass of `Metric` whose `compute` runs two
queries: an aggregate of label checks, then one grouped query giving each
class's rows in the target, in the prediction and in both. The scores and
their averages are arithmetic on those rows in Python. Calling a metric
returns a configured copy (ADR 0042). The search learns to rank a NaN mean
last.

**Tech Stack:** Python 3.12+, duckdb 2.0 (the one runtime dependency); tests
and validation: pytest, scikit-learn 1.9.1, numpy, optuna.

**Spec:** [`docs/specs/library-metrics.md`](../specs/library-metrics.md).
"§N" below is a section of it; "ADR N" is `docs/adr/00NN-*.md`. Read the
spec, ADR 0042, `src/sqlearn/metrics/accuracy.py` and
`src/sqlearn/model_selection/search.py` (`train`, lines ~480–525) before
starting.

## Global Constraints

- Work on the branch `library-metrics` in the worktree
  `.claude/worktrees/library-metrics` (`superpowers:using-git-worktrees`).
  Merge only on Tomas's word.
- **scikit-learn 1.9.1 wins** (spec §1): where this plan, the spec and
  scikit-learn disagree on a score, refusal or warning, build scikit-learn's
  behaviour and record the ruling in the build's ledger.
- Runtime dependency: `duckdb>=2.0.0` only; `src/` imports no numpy.
- uv only (`uv run`); every task through `just`. Before every commit:
  `just fmt`, `just check`, `just test`, each checked by its own exit code
  (never piped through `tail` before `&&`). Never `--no-verify`.
  Conventional commits, no AI attribution anywhere.
- Every module `src/sqlearn/metrics/Y.py` has
  `tests/src/sqlearn/metrics/test_Y.py` and
  `validation/sqlearn/metrics/validate_Y.py`, listed in
  `validation/__main__.py`'s `RUNNERS` (`just check-mirror`).
- British English in prose and docstrings, American spelling in identifiers.
  Public objects have numpydoc docstrings with an example
  (`just check-docstrings`).
- SQL is built from DuckDB expression objects, as `accuracy.py` does.
- Messages for a user's mistake follow ADR 0019: what went wrong, why, the
  fix.
- Defaults, verbatim from the spec: `average="binary"`, `pos_label=1`,
  `zero_division="warn"`. `average` takes `"binary"`, `"macro"`, `"micro"`,
  `"weighted"`; `zero_division` takes `"warn"`, `0.0`, `1.0`, `nan`.
- The six existing metrics keep their behaviour and their tests unchanged.
- No `GLOSSARY.md` exists at the root; name tests by the behaviour, in the
  spec's words.

## Review Focus

1. **Labels that are integers in one column and floats in the other**
   (`y` INTEGER, `prediction` DOUBLE holding 1.0): the same classes, as
   scikit-learn and `accuracy` treat them. Test in Task 3.
2. **Text labels with the default `pos_label=1`** and two classes: refused,
   naming `pos_label=` and the labels found. Test in Task 3.
3. **A fold holding one class in a search** with the binary default: scores
   0 with a warning, never stops the search. Test in Task 5.
4. **A label present only in the prediction** (a model predicting a class
   the held-out target lacks): it is a class, counted in macro's mean with
   recall undefined. Test in Task 2.
5. **Odd column names** (quotes, spaces) for target and prediction, as
   `accuracy` takes them. Test in Task 1.

---

### Task 1: Per-class counts and the binary scores

**Files:**
- Create: `src/sqlearn/metrics/classification.py`
- Modify: `src/sqlearn/metrics/__init__.py` (export `precision`, `recall`,
  `f1`, `ClassificationMetric`)
- Test: `tests/src/sqlearn/metrics/test_classification.py`
- Create: `validation/sqlearn/metrics/validate_classification.py` with
  `cases()` returning `[]` for now, listed in `RUNNERS` (the mirror check
  needs it from the first commit; Task 4 fills it)

**Interfaces:**
- Produces:
  - `class ClassificationMetric(Metric)`, a frozen dataclass adding
    `score: Literal["precision", "recall", "f1"]`,
    `average: str = "binary"`, `pos_label: object = 1`,
    `zero_division: str | float = "warn"`. `greater_is_better=True`,
    `needs="predict"`. `compute(rel, target, prediction="prediction",
    classes=None) -> float`, the same signature as `Metric.compute`;
    `classes` is ignored. Its `expression` field is not used: give it a
    private function that raises `InternalError` naming `compute`.
  - `precision`, `recall`, `f1`: `ClassificationMetric` instances named
    `"precision"`, `"recall"`, `"f1"`.
  - `_counts(rel, target, prediction) -> list[tuple[object, int, int, int]]`:
    per class, sorted by label, `(label, n_target, n_prediction, n_both)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_binary_scores_match_sklearn():
    y = [0, 1, 1, 0, 1, 1, 0, 0]
    p = [0, 1, 0, 0, 1, 1, 1, 0]
    frame = pd.DataFrame({"y": y, "prediction": p})
    for metric, sk in [(sq.metrics.precision, precision_score),
                       (sq.metrics.recall, recall_score),
                       (sq.metrics.f1, f1_score)]:
        assert metric.compute(rel(frame), "y") == pytest.approx(sk(y, p), abs=0)

def test_counts_come_from_one_grouped_query():
    # _counts on the frame above
    assert _counts(rel(frame), "y", "prediction") == [(0, 4, 4, 3), (1, 4, 4, 3)]

def test_odd_column_names_are_quoted():
    frame = pd.DataFrame({'my "y"': [0, 1, 1], "pred ict": [0, 1, 0]})
    assert sq.metrics.recall.compute(rel(frame), 'my "y"', "pred ict") == 0.5

def test_empty_null_and_nan_labels_are_refused_as_accuracy_refuses():
    # each raises SqlearnError with the same message accuracy gives,
    # with "precision" in place of "accuracy"
```

- [ ] **Step 2: Run them; they fail on the missing names**

Run: `uv run pytest tests/src/sqlearn/metrics/test_classification.py -q`
Expected: FAIL, `AttributeError: module 'sqlearn.metrics' has no attribute
'precision'`.

- [ ] **Step 3: Implement**

- `_counts`: project target and prediction, `UNION ALL` the two label
  columns with flags (`(label, 1, 0, target = prediction)` and
  `(label, 0, 1, 0)`), aggregate `sum`s grouped by label. DuckDB coerces an
  INTEGER and a DOUBLE label to one type, so `1` and `1.0` are one class.
- The checks of Step 1's last test run first in one aggregate, before
  `_counts`; share their messages with `Metric.compute` by moving them into a
  module-level helper in `accuracy.py`, leaving `Metric.compute`'s output and
  tests unchanged.
- From each class's counts: `tp = n_both`, `fp = n_prediction - n_both`,
  `fn = n_target - n_both`; precision `tp / (tp + fp)`, recall
  `tp / (tp + fn)`, F1 `2 tp / (2 tp + fp + fn)` (scikit-learn's form). Under
  `"binary"` the score is `pos_label`'s class's.

- [ ] **Step 4: Run the file, then the whole suite**

Run: `uv run pytest tests/src/sqlearn/metrics -q` then `just test`.
Expected: all pass; name every failure if not.

- [ ] **Step 5: Commit** —
      `feat: add precision, recall and f1, counted per class in SQL`

### Task 2: Settings by call, and the averages

**Files:**
- Modify: `src/sqlearn/metrics/accuracy.py` (`Metric.__call__`)
- Modify: `src/sqlearn/metrics/classification.py`
- Test: `tests/src/sqlearn/metrics/test_classification.py`,
  `tests/src/sqlearn/metrics/test_accuracy.py`

**Interfaces:**
- Consumes: Task 1's `ClassificationMetric`, `_counts`.
- Produces:
  - `Metric.__call__(self, **settings: object) -> Metric`: refuses with
    `SqlearnError`: "accuracy takes no settings, and was given average=.
    ...", naming the metrics that do take them.
  - `ClassificationMetric.__call__(self, *, average=..., pos_label=...,
    zero_division=...) -> ClassificationMetric`: a copy
    (`dataclasses.replace`) with the given settings, others kept. An unknown
    `average` or `zero_division` value refuses, listing the allowed values.
  - `repr(sq.metrics.f1(average="macro"))` is `f1(average='macro')`;
    defaults are left out, so `repr(sq.metrics.f1)` is `f1`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("average", ["macro", "micro", "weighted"])
@pytest.mark.parametrize("name", ["precision", "recall", "f1"])
def test_averages_match_sklearn_on_three_classes(name, average):
    # 300 rows, labels 0..2, seed 3; and the same on text labels "a".."c"
    metric = getattr(sq.metrics, name)(average=average)
    assert metric.compute(rel(frame), "y") == pytest.approx(sk(..., average=average))


def test_a_label_only_in_the_prediction_is_a_class():
    y, p = [0, 0, 1, 1], [0, 2, 1, 1]
    # f1 macro over classes 0, 1, 2 equals sklearn's, with zero_division=0.0


def test_calling_returns_a_copy_and_leaves_the_default():
    macro = sq.metrics.f1(average="macro")
    assert macro.average == "macro" and sq.metrics.f1.average == "binary"
    assert macro(zero_division=1.0).average == "macro"


def test_unknown_average_is_refused():
    with pytest.raises(SqlearnError, match="'binary', 'macro', 'micro', 'weighted'"):
        sq.metrics.f1(average="samples")


def test_a_metric_without_settings_refuses_a_call():
    with pytest.raises(SqlearnError, match="accuracy takes no settings"):
        sq.metrics.accuracy(average="macro")
```

- [ ] **Step 2: Run them; they fail** on `TypeError: 'ClassificationMetric'
  object is not callable`.

- [ ] **Step 3: Implement** the two `__call__`s and the averages:
  `macro` the mean of the per-class scores, `micro` the score from the
  summed `tp`, `fp`, `fn`, `weighted` the mean weighted by `n_target`. NaN
  per-class scores (from `zero_division=nan`) are left out of the average,
  as scikit-learn's `_nanaverage` does; all NaN gives NaN.

- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`, then
  `just test`. Expected: all pass.

- [ ] **Step 5: Commit** — `feat: set a metric's average by calling it`

### Task 3: scikit-learn's refusals and the zero-division warning

**Files:**
- Modify: `src/sqlearn/_errors.py`, `src/sqlearn/errors.py` (add
  `UndefinedMetricWarning(SqlearnWarning)`, exported)
- Modify: `src/sqlearn/metrics/classification.py`
- Test: `tests/src/sqlearn/metrics/test_classification.py`

**Interfaces:**
- Produces: `sqlearn.errors.UndefinedMetricWarning`, raised with
  `warnings.warn(..., stacklevel=2)` from `compute`; its message names the
  metric and the classes whose score was undefined, as scikit-learn's does.

- [ ] **Step 1: Write the failing tests**, each checked against
  scikit-learn's own result or exception on the same data:

```python
def test_binary_on_three_classes_is_refused_naming_the_averages():
    with pytest.raises(SqlearnError, match="average="):  # names macro, micro, weighted
        sq.metrics.f1.compute(rel(three_classes), "y")

def test_text_labels_with_the_default_pos_label_are_refused():
    frame = pd.DataFrame({"y": ["a", "b"], "prediction": ["a", "b"]})
    with pytest.raises(SqlearnError, match="pos_label="):  # and names 'a', 'b'
        sq.metrics.precision.compute(rel(frame), "y")

def test_one_label_only_scores_pos_label_as_absent():
    # y = p = [0, 0]: f1 is 0.0 with UndefinedMetricWarning, as sklearn

def test_int_target_and_float_prediction_are_the_same_classes():
    # y INTEGER [0, 1, 1], prediction DOUBLE [0.0, 1.0, 0.0]: equals sklearn

def test_a_non_whole_number_label_is_refused_as_continuous():
    # prediction DOUBLE [0, 1.5]: SqlearnError naming the column and "continuous"

def test_text_against_numbers_is_refused():
    # y VARCHAR, prediction INTEGER: SqlearnError naming both types

@pytest.mark.parametrize("zero_division", ["warn", 0.0, 1.0, math.nan])
@pytest.mark.parametrize("average", ["binary", "macro", "micro", "weighted"])
@pytest.mark.parametrize("name", ["precision", "recall", "f1"])
def test_zero_division_matches_sklearn(name, average, zero_division):
    # y = [0, 0, 1, 1], p = [0, 0, 0, 0] (class 1 never predicted), and for
    # "binary" also y = p = [0, 0]; same value (NaN as NaN) and the warning
    # raised exactly when sklearn raises UndefinedMetricWarning
```

- [ ] **Step 2: Run them; they fail** for the missing checks and warning.

- [ ] **Step 3: Implement**, following scikit-learn 1.9.1 (`type_of_target`,
  `_check_set_wise_labels`, `_prf_divide`):
  - Text against numbers: from `rel.types`, before any query.
  - Continuous: in the check aggregate, count rows of each DOUBLE/FLOAT
    label column where `col != floor(col)`; any is refused.
  - `"binary"` with more than two classes in `_counts`: refused.
  - `"binary"` with two classes and `pos_label` not among them: refused,
    naming the labels; with one class, no refusal (spec §4).
  - Zero division: an undefined score takes `zero_division`'s value, `0.0`
    for `"warn"`, which also warns.

- [ ] **Step 4: Run** the metrics tests, then `just test`. Expected: all pass.

- [ ] **Step 5: Commit** —
      `feat: refuse and warn as scikit-learn's classification metrics`

### Task 4: Validation against exact arithmetic and scikit-learn

**Files:**
- Modify: `validation/sqlearn/metrics/validate_classification.py`
- Create: `validation/sqlearn/metrics/classification.results.json` (written
  by the runner)

**Interfaces:**
- Consumes: the three metrics and their settings.
- Produces: `cases() -> list[dict]` in `validate_accuracy.py`'s form, through
  `_cases.measure_all`.

- [ ] **Step 1: Write `cases()`.** For each metric × average in the 12
  combinations, on `_cases.SIZES` with two classes (binary) or three (the
  rest), integer and text labels (`_cases.WORDS`): `exact` is the score in
  `Fraction` from the per-class counts in pure Python; answers are
  `"sqlearn"` and `"scikit-learn"`; NULL labels and no rows are cases
  sqlearn must refuse, as in `validate_accuracy.py`. `BOUND` starts at 0.
- [ ] **Step 2: Run** `just validate`; read each failed case's distance.
- [ ] **Step 3: Set `BOUND` from the first measurement** (ADR 0016), with a
  comment giving the measured worst ULPs; a bound above 0 needs its written
  reason in the module.
- [ ] **Step 4: Run** `just verify`. Expected: pass.
- [ ] **Step 5: Commit** —
      `test: validate precision, recall and f1 against scikit-learn`

### Task 5: NaN scores in the search

**Files:**
- Modify: `src/sqlearn/model_selection/search.py` (the pick of the best,
  ~line 508)
- Modify: `src/sqlearn/model_selection/methods.py` (the Optuna `tell`)
- Test: `tests/src/sqlearn/model_selection/test_search.py`,
  `tests/src/sqlearn/model_selection/test_methods.py`

**Interfaces:**
- Consumes: `sq.metrics.precision(zero_division=math.nan)`.
- Produces: the search's best is picked among non-NaN means; all NaN refuses
  with `SqlearnError` naming `zero_division`. The Optuna method tells a NaN
  score as `TrialState.FAIL` (`study.tell(trial, state=FAIL)`), without
  Optuna's "The value nan is not acceptable" warning.

- [ ] **Step 1: Write the failing tests.** A test model `Constant(label)`
  with `get_params`, predicting `label` for every row:

```python
def test_a_nan_mean_ranks_last_as_gridsearchcv():
    # binary target, params {"model__label": [0, 1]},
    # metric=sq.metrics.precision(zero_division=math.nan): label 0 never
    # predicts 1, so its precision is NaN; best_params_ is label 1 and
    # best_score_ equals GridSearchCV(scoring=make_scorer(precision_score,
    # zero_division=np.nan), cv=PredefinedSplit(sqlearn's folds))'s

def test_every_setting_nan_is_refused_naming_zero_division():
    # params {"model__label": [0]}: SqlearnError matching "zero_division"

def test_f1_macro_matches_gridsearchcv():
    # as test_grid_matches_gridsearchcv, with metric=sq.metrics.f1(average="macro")
    # and scoring="f1_macro"

def test_a_fold_of_one_class_scores_and_does_not_stop_the_search():
    # folds whose held-out rows hold one class, binary f1: the search runs,
    # warning UndefinedMetricWarning

def test_optuna_fails_a_nan_trial_quietly():  # in test_methods.py
    # tell(params, nan): study_.trials[-1].state is FAIL; no UserWarning
```

- [ ] **Step 2: Run them; they fail** (the NaN pick is order-dependent; the
  all-NaN case does not raise).
- [ ] **Step 3: Implement** the pick and the Optuna `tell`.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/model_selection -q`,
  then `just test`. Expected: all pass.
- [ ] **Step 5: Commit** — `feat: rank a NaN score last in a search`

### Task 6: Documentation, the issue, and the handoff

**Files:**
- Modify: `docs/reference/index.md` (after `sqlearn.metrics.roc_auc`:
  `ClassificationMetric`, `precision`, `recall`, `f1`; and
  `sqlearn.errors.UndefinedMetricWarning` beside the other errors)
- Modify: `docs/guide/tuning-a-model.md` (the metrics table, ~line 131:
  the three rows, and a call with `average=`)
- Modify: `docs/guide/from-scikit-learn.md` (~line 56: `precision_score`,
  `recall_score`, `f1_score`, and `"f1_macro"`, `"precision_weighted"` and
  the other scorer strings beside `sq.metrics.f1(average="macro")`)
- Modify: `CLAUDE.md` (the "Done" line: the metrics area built), `HANDOFF.md`

- [ ] **Step 1:** Write the doc changes; each new public object's docstring
  has a running example.
- [ ] **Step 2:** Run
  `rm -rf docs/reference/generated docs/_build && just build-docs`, and
  `just check-docstrings`. Expected: both pass, the doctests run.
- [ ] **Step 3:** File the issue (github-pm): "accuracy does not refuse
  continuous or mixed-kind labels, as scikit-learn does" (spec §4), and the
  area's tracking issue with the summary, as #33 has.
- [ ] **Step 4:** Run `just verify`. Expected: pass.
- [ ] **Step 5: Commit** — `docs: document precision, recall and f1`

---
type: plan
tags: [metrics, fbeta, confusion-matrix, classification-report, roc-curve, precision-recall-curve, average-precision]
summary: "Implementation plan for the second metrics slice (#58): fbeta and average_precision as scores, confusion_matrix, classification_report, roc_curve and precision_recall_curve as relations, each validated against scikit-learn 1.9.1."
related: [docs/specs/library-more-metrics.md, docs/adr/0042-a-metrics-settings-are-a-call.md]
---
# More metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `fbeta` and `average_precision` as scores, and
`confusion_matrix`, `classification_report`, `roc_curve` and
`precision_recall_curve` as functions handing back DuckDB relations, all
behaving as scikit-learn 1.9.1 and computed in SQL.

**Architecture:** `fbeta` extends `ClassificationMetric` (one more setting);
`average_precision` is a `Metric` subclass with `pos_label`, a window stage
like `roc_auc`'s. The four tables live in two new modules,
`metrics/tables.py` (matrix, report: grouped counts per label) and
`metrics/curves.py` (one grouped count per distinct score, then running sums
in a window), each returning a lazy relation passed through `to_output`.

**Tech Stack:** Python 3.12, DuckDB 2.0 relational API, scikit-learn 1.9.1
(tests and validation only), pytest, `uv`, `just`.

**Spec:** `docs/specs/library-more-metrics.md`. Issue #58.

## Global Constraints

- scikit-learn 1.9.1 wins: where the spec and 1.9.1 disagree, build 1.9.1
  and correct the spec in the same commit.
- Computation is SQL in DuckDB; Python only on a few rows per class (ADR
  0002). Nothing pulls every row into Python.
- The only runtime dependency is `duckdb` (ADR 0004): scikit-learn and numpy
  in tests and `validation/` only.
- Messages in ADR 0019's form: what went wrong, `Why:`, `Fix:`.
- British English in prose and docstrings, American spelling in identifiers
  (ADR 0010).
- Every public function and class: a numpy-style docstring with an example
  that runs as a doctest.
- Tests named in `GLOSSARY.md` terms, through public seams
  (`sq.metrics.*`).
- Validation per ADR 0016: an exact `Fraction` answer beside sqlearn,
  scikit-learn and numpy; bounds set from the first measurement and never
  loosened without a written reason in the script.
- Before each commit: `just fmt`, `just check`, `just test`; commit
  `validation/tests.json` when tests were added. No AI attribution in
  commits. Each commit subject names `(#58)`.
- Work on branch `library-more-metrics` in a worktree.

## Review Focus

1. **Labels that are not plain identifiers** (`"it's"`, `"a b"`, `""`,
   `True`/`False`) as confusion-matrix column names: each column named
   exactly by the label's text, quoted in SQL. Pinned in Task 2.
2. **Integer and float labels meeting** (target `INTEGER` 1, prediction
   `DOUBLE` 1.0): one class, as `precision` already treats it; the column
   name is the unified type's text. Pinned in Task 2.
3. **Every score tied** in a curve (all rows the same score): two points
   (threshold `inf` and that score) for ROC, as scikit-learn. Pinned in
   Task 4.
4. **Integer or negative scores** (decision values, not probabilities):
   accepted by the curves, thresholds `DOUBLE`. Pinned in Task 4.
5. **A large relation**: a curve and the matrix come back as a
   `DuckDBPyRelation` without reading every row into Python (one test on
   `range(2_000_000)` checking the type and that `.count("*")` works).
   Pinned in Task 4.

---

### Task 1: fbeta, and the search's metric checks

**Files:**
- Modify: `src/sqlearn/metrics/classification.py`
- Modify: `src/sqlearn/metrics/accuracy.py` (`Metric.__call__` message;
  new `Metric._ready`)
- Modify: `src/sqlearn/metrics/__init__.py`
- Modify: `src/sqlearn/model_selection/search.py` (`Search.__init__`,
  `train`)
- Test: `tests/src/sqlearn/metrics/test_classification.py`,
  `tests/src/sqlearn/model_selection/test_search.py`
- Validation: `validation/sqlearn/metrics/validate_classification.py`
- Docs: `docs/reference/index.md`, `docs/guide/from-scikit-learn.md`,
  `docs/guide/tuning-a-model.md`

**Interfaces:**
- Produces: `sq.metrics.fbeta: ClassificationMetric` (score `"fbeta"`,
  `beta=None`); `ClassificationMetric.beta: float | None` (`f1` has
  `beta=1.0`, score `"f1"`, name and repr unchanged);
  `Metric._ready(self) -> None` (no-op; raises `SqlearnError` when the
  metric cannot be computed as configured). `Search` refuses a `metric=`
  that is not a `Metric`.

- [ ] **Step 1: Write the failing tests** (in `test_classification.py`)

```python
@pytest.mark.parametrize("beta", [0.0, 0.5, 1.0, 2.0, math.inf, True])
@pytest.mark.parametrize("average", ["binary", "macro", "micro", "weighted"])
def test_fbeta_matches_sklearn(beta, average): ...
    # y = [0, 1, 2, 1, 0, 2, 2] / p = [0, 2, 2, 1, 0, 0, 1] for macro/micro/
    # weighted, two classes for binary; assert sq == fbeta_score(...) exactly.

def test_fbeta_without_beta_refuses():
    # sq.metrics.fbeta.compute(rel, "y") raises SqlearnError matching
    # r"beta=.*Why:.*Fix:.*fbeta\(beta=2"

@pytest.mark.parametrize("beta", [-1.0, math.nan, "2"])
def test_fbeta_refuses_a_beta_scikit_learn_refuses(beta): ...
    # sq.metrics.fbeta(beta=beta) raises SqlearnError naming beta

def test_fbeta_zero_division_matches_sklearn(): ...
    # a class never predicted nor in the target region; every zero_division,
    # warning class UndefinedMetricWarning when "warn"

def test_f1_is_fbeta_at_one():
    # sq.metrics.f1 and sq.metrics.fbeta(beta=1) give the same score;
    # repr(sq.metrics.f1) == "f1"; repr(sq.metrics.fbeta(beta=2)) == "fbeta(beta=2)"
```

In `test_search.py`:

```python
def test_a_search_refuses_fbeta_without_beta_before_any_work(): ...
    # sq.search(pipe, params, metric=sq.metrics.fbeta).train(...) raises
    # SqlearnError before a fold is trained (no model fit: use a model whose
    # fit raises, as the existing early-refusal tests do).

def test_a_search_refuses_a_metric_that_is_not_a_metric():
    # sq.search(pipe, metric=sq.metrics.confusion_matrix) is Task 2's name;
    # here use a plain function `lambda *a: 0.0`: SqlearnError matching
    # r"metric=.*Why:.*Fix:"

def test_fbeta_scores_as_grid_search_cv(): ...
    # fbeta(beta=2) over sqlearn's folds equals
    # GridSearchCV(scoring=make_scorer(fbeta_score, beta=2)) given the same
    # folds, as the existing f1 search test checks.
```

- [ ] **Step 2: Run them to see them fail**

Run:

```bash
uv run pytest tests/src/sqlearn/metrics/test_classification.py \
  tests/src/sqlearn/model_selection/test_search.py -k "fbeta or not_a_metric" -q
```

Expected: FAIL,
`AttributeError: module 'sqlearn.metrics' has no attribute 'fbeta'`.

- [ ] **Step 3: Implement**

- `ClassificationMetric`: `score` gains `"fbeta"`; field `beta: float |
  None = None`; `_DEFAULTS` gains `beta` for an fbeta metric only (a call
  with `beta=` on `precision`, `recall` or `f1` refuses as an unknown
  setting). `beta` is checked as 1.9.1 checks it: a real number (bool
  included) in `[0, inf]`, else refused naming the range.
- The score from counts, exactly: with `b2 = Fraction(beta) ** 2`,
  `(1 + b2) * tp / ((1 + b2) * tp + b2 * fn + fp)`; `beta=inf` is recall.
  Zero division follows 1.9.1's `_prf_divide` / F-beta rule (check it in
  `sklearn/metrics/_classification.py`): the same warning text as `f1`
  ("F-score is ill-defined ...").
- `compute` and `_ready` refuse `beta is None` for `"fbeta"`:
  `"fbeta needs beta=, the weight of recall against precision. Why: ...
  Fix: pass it, as sq.metrics.fbeta(beta=2.0)."`
- `Metric.__call__`'s message names the metrics with settings:
  precision, recall, f1, fbeta, average_precision.
- `Search.__init__` refuses a `metric` that is not a `Metric`, saying the
  table functions (`confusion_matrix`, `classification_report`,
  `roc_curve`, `precision_recall_curve`) give tables, not a score. `train`
  calls `self.metric._ready()` before `_check_method`.

- [ ] **Step 4: Validation.** Add `"fbeta"` at `beta` 0.5 and 2 to
  `validate_classification.py`, exact answer from the formula above as a
  `Fraction`, `BOUND = 0` kept.

- [ ] **Step 5: Docs.** Reference autosummary gains
  `sqlearn.metrics.fbeta`; the name map gains `fbeta_score(y, p, beta=2)` →
  `sq.metrics.fbeta(beta=2).compute(rel, "y", "p")` and
  `make_scorer(fbeta_score, beta=2)` → `metric=sq.metrics.fbeta(beta=2)`;
  the tuning guide's table gains the row.

- [ ] **Step 6: Run** `just fmt && just check && just test`; all pass.

- [ ] **Step 7: Commit** `feat(metrics): fbeta, and the search refuses a
  table or an unready metric (#58)`.

### Task 2: confusion_matrix, and the ADR on table metrics

**Files:**
- Create: `src/sqlearn/metrics/tables.py`
- Modify: `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_tables.py`
- Validation: `validation/sqlearn/metrics/validate_tables.py`
- Docs: `docs/adr/0049-table-metrics-are-relations.md`,
  `docs/adr/index.md` (Models and search), `docs/reference/index.md`,
  `docs/guide/from-scikit-learn.md`

**Interfaces:**
- Consumes: `check_labels(name, rel, target, prediction)` from
  `metrics/_labels.py`; `to_output(rel, out)` from `sqlearn._output`.
- Produces: `confusion_matrix(rel: duckdb.DuckDBPyRelation, target: str,
  prediction: str = "prediction", *, normalize: str | None = None, out:
  str | Output | None = None) -> Any`; private
  `_labels_of(rel, target, prediction) -> list[object]` (the sorted labels
  of both columns, one query) for Task 3.

- [ ] **Step 1: Write the failing tests**

```python
def test_confusion_matrix_matches_sklearn_on_three_classes():
    # y=[0,1,2,2,1,0,2], p=[0,2,2,1,1,0,0]; out="numpy" gives columns
    # {"y", "0", "1", "2"}; the stacked label columns equal
    # confusion_matrix(y, p) row for row.

@pytest.mark.parametrize("normalize", ["true", "pred", "all"])
def test_a_normalised_confusion_matrix_matches_sklearn(normalize): ...
    # include a predicted label with no target rows: its "true" row is 0s.

def test_confusion_matrix_names_columns_by_the_labels_text():
    # labels ["it's", "a b", "", "z"] -> columns ["y", "", "a b", "it's", "z"]
    # (sorted); booleans -> ["y", "False", "True"]

def test_integer_and_float_labels_are_one_class():
    # target INTEGER [1, 0], prediction DOUBLE [1.0, 0.0]: two label columns

def test_a_label_named_as_the_target_refuses():
    # target column "y" with a label "y": SqlearnError naming the clash

def test_one_label_warns_as_sklearn():
    # every row label 3: UserWarning "A single label was found", 1x1 matrix

def test_confusion_matrix_refuses_what_precision_refuses(): ...
    # no rows, NULL, NaN, a continuous label: same messages as precision

def test_confusion_matrix_is_a_relation_unless_out_is_given():
    # isinstance(result, duckdb.DuckDBPyRelation); out="pandas" a DataFrame

def test_an_unknown_normalize_refuses(): ...
```

- [ ] **Step 2: Run them to see them fail** — `uv run pytest
  tests/src/sqlearn/metrics/test_tables.py -q`: ImportError on
  `confusion_matrix`.

- [ ] **Step 3: Implement** in `tables.py`: `check_labels`, then
  `_labels_of` (the distinct labels of the two columns stacked, sorted, as
  `_counts` stacks them), then one grouped count over (target, prediction)
  turned into one column per label with conditional sums (`sum(CASE WHEN p
  = <label> THEN 1 ELSE 0 END)`, each aliased to the quoted label text),
  grouped by target, joined to the full label list so a label never in the
  target still gets a row of 0s; sorted by label. `normalize` divides in
  SQL by the row total, column total or grand total (`DOUBLE`), 0 where
  the total is 0. Warn with `UserWarning` when one label in all, as 1.9.1.

- [ ] **Step 4: ADR 0049** "Table metrics are relations": the four
  functions hand back a lazy relation with `out=`, not arrays or a string,
  and are not `Metric`s; consequences: no `classification_report` text,
  `.show()` instead; a search refuses them (Task 1). Add it to the index
  under "Models and search".

- [ ] **Step 5: Validation** `validate_tables.py`: the matrix against
  `sklearn.metrics.confusion_matrix` and a pure-Python count, on the
  `_cases` label datasets and every `normalize`; counts exact, normalised
  cells against `Fraction` with `BOUND = 0` (one division).

- [ ] **Step 6: Docs** — reference gains `sqlearn.metrics.confusion_matrix`;
  name map gains `confusion_matrix(y, p)` and `normalize=`.

- [ ] **Step 7: Run** `just fmt && just check && just test`; all pass.

- [ ] **Step 8: Commit** `feat(metrics): confusion_matrix as a relation
  (#58)`.

### Task 3: classification_report

**Files:**
- Modify: `src/sqlearn/metrics/tables.py`, `src/sqlearn/metrics/__init__.py`
- Modify: `src/sqlearn/metrics/classification.py` (expose the per-class
  scores for the report without a second query)
- Test: `tests/src/sqlearn/metrics/test_tables.py`
- Validation: `validation/sqlearn/metrics/validate_tables.py`
- Docs: `docs/reference/index.md`, `docs/guide/from-scikit-learn.md`

**Interfaces:**
- Consumes: `_counts(rel, target, prediction) -> Counts` and the
  `ClassificationMetric` score arithmetic from `classification.py`.
- Produces: `classification_report(rel, target, prediction="prediction", *,
  zero_division="warn", out=None) -> Any`; columns `label` VARCHAR,
  `precision`, `recall`, `f1_score` DOUBLE, `support` BIGINT.

- [ ] **Step 1: Write the failing tests**

```python
def test_classification_report_matches_sklearns_output_dict():
    # three classes; rows: "0", "1", "2", "accuracy", "macro avg",
    # "weighted avg"; each value == classification_report(...,
    # output_dict=True)[row][key] ("f1-score" -> f1_score); accuracy row:
    # precision and recall None, f1_score the accuracy, support every row.

@pytest.mark.parametrize("zero_division", ["warn", 0.0, 1.0, math.nan])
def test_the_reports_zero_division_matches_sklearn(zero_division): ...
    # a class never predicted; nan leaves it out of the macro average

def test_the_report_warns_once_naming_the_classes(): ...
    # UndefinedMetricWarning text names the labels, as precision's

def test_the_report_takes_text_labels(): ...
```

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement**: one `check_labels`, one `_counts`; per-class
  precision, recall, F1 by `ClassificationMetric`'s exact arithmetic with
  the given `zero_division`; macro and weighted by `_nanmean`; the result
  built as a `VALUES` relation on the connection of `rel` (a few rows),
  in the order above. Warnings as 1.9.1's report raises them (one per
  undefined score kind; check `classification_report` in 1.9.1).

- [ ] **Step 4: Validation** against `classification_report(...,
  output_dict=True)` and `Fraction`, `BOUND = 0`.

- [ ] **Step 5: Docs**: reference gains it; name map gains
  `classification_report(y, p)` → `.show()`, `output_dict=True` →
  `out="pandas"`, and `precision_recall_fscore_support` → the report's
  class rows.

- [ ] **Step 6: Run** `just fmt && just check && just test`.

- [ ] **Step 7: Commit** `feat(metrics): classification_report as a
  relation (#58)`.

### Task 4: roc_curve

**Files:**
- Create: `src/sqlearn/metrics/curves.py`
- Modify: `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_curves.py`
- Validation: `validation/sqlearn/metrics/validate_curves.py`
- Docs: `docs/reference/index.md`, `docs/guide/from-scikit-learn.md`

**Interfaces:**
- Produces: `roc_curve(rel, target: str, score: str, *, pos_label: object =
  None, drop_intermediate: bool = True, out=None) -> Any`, columns `fpr`,
  `tpr`, `threshold` DOUBLE; private `_steps(name, rel, target, score,
  pos_label) -> tuple[duckdb.DuckDBPyRelation, int, int]`: one row per
  distinct score, descending, with cumulative `tps` and `fps` (HUGEINT),
  and the totals of positives and negatives, after the label and score
  checks. Task 5 uses `_steps`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("drop_intermediate", [True, False])
def test_roc_curve_matches_sklearn(drop_intermediate):
    # y=[0,0,1,1,0,1,1,0], s=[.1,.4,.35,.8,.4,.8,.9,.2]; every column equal
    # to roc_curve(...) exactly, threshold[0] == inf

def test_roc_curve_drops_only_equal_steps():
    # y=[1,1,1,1,0,0], s=[.9,.8,.8,.7,.2,.1]: tpr keeps 0.25, 0.75, 1.0 at
    # fpr 0, as 1.9.1

def test_every_score_tied_gives_two_points(): ...
def test_integer_and_negative_scores_are_thresholds(): ...

@pytest.mark.parametrize("labels", [[0, 1], [-1, 1], [0], [1], [-1],
                                    [False, True], [0.0, 1.0]])
def test_pos_label_left_out_takes_sklearns_labels(labels): ...
def test_other_labels_need_pos_label(): ...  # ["a", "b"] refuses; pos_label="b" works

def test_no_negative_rows_warn_and_give_nan_fpr(): ...  # UndefinedMetricWarning
def test_a_curve_refuses_a_missing_or_infinite_score(): ...  # NULL, NaN, inf
def test_a_curve_refuses_more_than_two_classes(): ...

def test_a_curve_over_many_rows_is_a_relation():
    # rel = duckdb.sql("SELECT i % 2 AS y, hash(i) % 1000 AS s FROM range(2000000) t(i)")
    # isinstance(roc_curve(rel, "y", "s"), duckdb.DuckDBPyRelation) and its
    # count("*") is at most 1001
```

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement** `_steps` (the label checks of `check_labels`
  on the target, a score check refusing NULL, NaN and infinity; positive
  = `pos_label`, or 1 when the labels are among 1.9.1's accepted sets;
  grouped by score: positives and negatives at each score; window sums
  ordered by score descending), then `roc_curve`: prepend the `inf` row
  with counts 0, keep a row when `drop_intermediate` is false or either
  second difference (`lag`/`lead` of `fps` and `tps`) is non-zero, and the
  first and last rows; `fpr = fps / negatives`, `tpr = tps / positives`
  (one division each; NaN with the warning when the total is 0).

- [ ] **Step 4: Validation** `validate_curves.py` against `roc_curve`, with
  ties, on the `_cases` binary datasets: thresholds and counts exact, rates
  `BOUND = 0` against `Fraction`.

- [ ] **Step 5: Docs**: reference, name map (`roc_curve(y, s)`).

- [ ] **Step 6: Run** `just fmt && just check && just test`.

- [ ] **Step 7: Commit** `feat(metrics): roc_curve as a relation (#58)`.

### Task 5: precision_recall_curve

**Files:**
- Modify: `src/sqlearn/metrics/curves.py`, `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_curves.py`
- Validation: `validation/sqlearn/metrics/validate_curves.py`
- Docs: `docs/reference/index.md`, `docs/guide/from-scikit-learn.md`

**Interfaces:**
- Consumes: `_steps` from Task 4.
- Produces: `precision_recall_curve(rel, target, score, *, pos_label=None,
  drop_intermediate=False, out=None) -> Any`, columns `precision`,
  `recall`, `threshold` DOUBLE, ordered by threshold ascending, then the
  final row (1, 0, NULL).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("drop_intermediate", [False, True])
def test_precision_recall_curve_matches_sklearn(drop_intermediate):
    ...
    # the same y, s as Task 4; precision, recall equal; thresholds equal
    # to sklearn's (one fewer), the last row's threshold None


def test_no_positive_rows_warn_and_give_recall_one():
    ...
    # UserWarning "No positive class found in y_true"; recall 1, precision
    # 0 then 1 at the final row


def test_no_negative_rows_give_precision_one_without_a_warning(): ...
def test_the_curve_takes_text_labels_with_pos_label(): ...
```

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement** from `_steps`: `precision = tps / (tps + fps)`,
  `recall = tps / positives` (1 when positives is 0), ascending threshold,
  then the final row; `drop_intermediate` as 1.9.1's (check
  `precision_recall_curve` for its rule).

- [ ] **Step 4: Validation** against `precision_recall_curve`, `BOUND = 0`.

- [ ] **Step 5: Docs**: reference, name map.

- [ ] **Step 6: Run** `just fmt && just check && just test`.

- [ ] **Step 7: Commit** `feat(metrics): precision_recall_curve as a
  relation (#58)`.

### Task 6: average_precision

**Files:**
- Modify: `src/sqlearn/metrics/probability.py`,
  `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_probability.py`,
  `tests/src/sqlearn/model_selection/test_search.py`
- Validation: `validation/sqlearn/metrics/validate_probability.py`
- Docs: `docs/reference/index.md`, `docs/guide/from-scikit-learn.md`,
  `docs/guide/tuning-a-model.md`

**Interfaces:**
- Produces: `class AveragePrecision(Metric)` (frozen; `pos_label: object =
  1`; `needs="predict_proba"`; `__call__(**settings)` takes `pos_label`
  only); `sq.metrics.average_precision: AveragePrecision`;
  `compute(rel, target, prediction="prediction", classes=...) -> float`
  as `Metric.compute`.

- [ ] **Step 1: Write the failing tests**

```python
def test_average_precision_matches_sklearn_on_two_classes():
    # classes [0, 1]; == average_precision_score(y, proba[:, 1]) within
    # the validation's bound

def test_average_precision_scores_pos_label_on_labels_one_and_two():
    # classes [1, 2]: == average_precision_score(y, proba[:, 0]) (pos_label 1)

def test_average_precision_needs_pos_label_for_text_labels(): ...
    # refuses; average_precision(pos_label="b") scores proba of "b"

def test_average_precision_matches_sklearn_on_three_classes(): ...  # macro
def test_average_precision_refuses_pos_label_on_more_classes(): ...
def test_no_positive_rows_give_zero_with_sklearns_warning(): ...
def test_no_negative_rows_give_one(): ...
def test_a_class_missing_on_more_classes_is_a_missing_class_error(): ...
```

In `test_search.py`:

```python
def test_average_precision_scores_each_fold_as_sklearn():
    ...
    # {0,1} labels, LogisticRegression: each fold's score equals
    # average_precision_score of that fold's predict_proba, as the roc_auc
    # search test checks it
```

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement**: per scored class `c` (binary: `pos_label`'s
  column; more: each class), group the rows by its probability, positives
  and rows at each distinct score, running sums descending (window stage,
  as `roc_auc`'s `windows`), then `AP = Σ (Δtp_k / P) * (tp_k / n_k)`
  summed with `fsum` (compensated, ADR 0033), one value per class,
  macro mean for more. Refusals and warnings as the spec's §3.

- [ ] **Step 4: Validation**: `validate_probability.py` gains
  `average_precision` against `average_precision_score` and an exact
  `Fraction` sum; set its `BOUNDS` entry from the first measurement, with
  the reason written beside it.

- [ ] **Step 5: Docs**: reference, name map
  (`average_precision_score(y, proba[:, 1])`,
  `scoring="average_precision"` with the `decision_function` note), tuning
  table row.

- [ ] **Step 6: Run** `just fmt && just check && just test`.

- [ ] **Step 7: Commit** `feat(metrics): average_precision (#58)`.

### Task 7: the guide page, and closing the slice

**Files:**
- Create: `docs/guide/evaluating-a-model.md`
- Modify: `docs/guide/index.md` (toctree, after `tuning-a-model`),
  `GLOSSARY.md` (only terms the build settled), `HANDOFF.md`,
  `CLAUDE.md` (the area's line under part 3.3)

- [ ] **Step 1: Write the guide page** as a MyST notebook like
  `docs/guide/tuning-a-model.md`: train a model on
  `sq.datasets.breast_cancer`, then `fbeta(beta=2)`, `average_precision`,
  `confusion_matrix(...).show()`, `classification_report(...).show()`,
  `roc_curve(..., out="pandas")`, and a short note on plotting it with the
  user's own library (no plot in the page: no plotting dependency).

- [ ] **Step 2: Build the docs** `rm -rf docs/reference/generated
  docs/_build && just build-docs`; no warnings.

- [ ] **Step 3: `just verify`** passes; commit the changed
  `validation/**/*.results.json` and `tests.json`.

- [ ] **Step 4: Update** `CLAUDE.md` (the sixth area built: spec, plan, ADR
  0049, issue #58), `HANDOFF.md` (In progress → Just finished).

- [ ] **Step 5: Commit** `docs: the evaluating-a-model guide; the second
  metrics slice is built (#58)`.

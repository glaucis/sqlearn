---
type: plan
tags: [metrics, balanced-accuracy, mcc, brier, plan]
summary: "Implementation plan for balanced_accuracy, mcc and brier in sq.metrics: a counts-based metric class in a new balanced module, a Brier class beside log_loss, validation runners, and the guide."
related: [docs/specs/archived/library-balanced-scores.md, docs/adr/0042-a-metrics-settings-are-a-call.md]
---
# Balanced scores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** add `sq.metrics.balanced_accuracy`, `sq.metrics.mcc` and
`sq.metrics.brier`, matching scikit-learn 1.9.1, computed in DuckDB, usable as
a search's `metric=`.

**Architecture:** `balanced_accuracy` and `mcc` are arithmetic on each class's
counts, which `classification._counts` already gets in one grouped query; they
share a new frozen dataclass `CountMetric(Metric)` in a new module
`metrics/balanced.py`. `brier` is one aggregate over the probability columns,
a frozen dataclass `BrierScore(Metric)` in `metrics/probability.py` built like
`AveragePrecision`.

**Tech Stack:** Python 3.12, DuckDB expressions, pytest, scikit-learn 1.9.1 as
the reference.

**Spec:** `docs/specs/library-balanced-scores.md` (issue #62).

## Global Constraints

- Same numbers, defaults and settings as scikit-learn 1.9.1; where it and the
  spec disagree, scikit-learn wins and the spec is corrected.
- Computation in SQL by DuckDB; Python only does arithmetic on a few counts.
- Settings are a call (ADR 0042); every warning and refusal has a `Fix:` line
  (ADR 0046); British prose, American identifiers (ADR 0010).
- Every new module under `src/sqlearn/metrics/` has
  `tests/src/sqlearn/metrics/test_<name>.py` and
  `validation/sqlearn/metrics/validate_<name>.py` (`just check-tests`).
- Commit with `(#62)` in the subject; `just check` and `just test` pass first.

## Review Focus

1. **Text and boolean labels** (`"churned"`, `True`): the counts scores take
   them as `precision` does. Task 1 and Task 2 test text labels.
2. **An INTEGER 1 and a DOUBLE 1.0 as one class:** `_counts` stacks them into
   one type. Task 2 tests `mcc` over an INTEGER target and a DOUBLE prediction.
3. **NULL, NaN, a missing column, no rows:** refused by `check_labels` (counts)
   and `Metric.compute` (brier), with sqlearn's messages. Task 1 and Task 3
   test one each.
4. **A class of the model with no scored row** (a fold of one class): `brier`
   scores it from the model's classes, as scikit-learn does with `labels=`.
   Task 3 tests it.
5. **Ranking direction in a search:** `brier` is lower-better, the other two
   higher-better. Task 3 tests a search picks by `min` for `brier`.

---

### Task 1: balanced_accuracy

**Files:**
- Create: `src/sqlearn/metrics/balanced.py`
- Modify: `src/sqlearn/metrics/__init__.py` (export `CountMetric`,
  `balanced_accuracy`), `src/sqlearn/metrics/accuracy.py` (`Metric.__call__`
  message names `balanced_accuracy` and `brier` among the metrics with
  settings)
- Test: `tests/src/sqlearn/metrics/test_balanced.py`

**Interfaces:**
- Consumes:
  `classification._counts(rel, target, prediction)`, a list of
  `(label, n_target, n_prediction, n_both)`,
  `_labels.check_labels(name, rel, target, prediction)`.
- Produces: `@dataclass(frozen=True) class CountMetric(Metric)` with fields
  `score: Literal["balanced_accuracy", "mcc"]`, `adjusted: bool = False`;
  `__call__(**settings) -> CountMetric` (only `adjusted`, only for
  `balanced_accuracy`; `mcc` keeps `Metric.__call__`'s refusal);
  `compute(rel, target, prediction="prediction", classes=None) -> float`;
  `__repr__` shows `balanced_accuracy(adjusted=True)` when set.
  `balanced_accuracy` is a `CountMetric` named `"balanced_accuracy"`, with
  `_not_an_expression`, higher-better, `score="balanced_accuracy"`.

- [ ] **Step 1: Write the failing tests** in `test_balanced.py`:
  `test_balanced_accuracy_matches_scikit_learn` (parametrised over the probe's
  cases: 95 zeros and 5 ones against all zeros → 0.5, adjusted → 0.0;
  `["a","b","b"]` against `["a","a","b"]` → 0.75; a three-class case), each
  compared with `balanced_accuracy_score` with `==`;
  `test_a_predicted_class_outside_the_target_is_warned` (`[0,0,1,1]` against
  `[0,2,1,1]` → 0.75 and one `SqlearnWarning` whose text has `Fix:`);
  `test_adjusted_on_one_class_is_minus_infinity_with_a_warning`
  (`[1,1,1]` against `[1,0,1]` → `-math.inf`, a `SqlearnWarning` with `Fix:`);
  `test_balanced_accuracy_takes_only_adjusted` (`balanced_accuracy(beta=1)`
  raises `SqlearnError`; `repr(balanced_accuracy(adjusted=True))` is
  `"balanced_accuracy(adjusted=True)"`);
  `test_counts_scores_refuse_no_rows_and_missing_values` (empty relation and a
  NULL prediction raise `SqlearnError`).
- [ ] **Step 2: Run**
      `uv run pytest tests/src/sqlearn/metrics/test_balanced.py -q`. Expected:
      FAIL, `balanced_accuracy` not in `sqlearn.metrics`.
- [ ] **Step 3: Implement** `CountMetric` and `balanced_accuracy`. The score is
  the exact `Fraction` mean of `n_both / n_target` over labels with
  `n_target > 0`, then `adjusted`: `chance = 1 / k` for the `k` target classes,
  `(score - chance) / (1 - chance)`, giving `-inf` (or NaN for 0/0) as numpy
  does when `k == 1`. Round to a double once.
- [ ] **Step 4: Run** the test file. Expected: PASS. Then
  `uv run pytest tests/src/sqlearn/metrics -q`: PASS.
- [ ] **Step 5: Commit** `feat: balanced accuracy in sq.metrics (#62)`.

### Task 2: mcc

**Files:**
- Modify: `src/sqlearn/metrics/balanced.py`, `src/sqlearn/metrics/__init__.py`
  (export `mcc`)
- Test: `tests/src/sqlearn/metrics/test_balanced.py`

**Interfaces:**
- Consumes: `CountMetric` from Task 1.
- Produces: `mcc = CountMetric("mcc", _not_an_expression, True, score="mcc")`.

- [ ] **Step 1: Write the failing tests:** `test_mcc_matches_scikit_learn`
  (95/5 against all zeros → 0.0; `[0,1]` against `[0,1]` → 1.0;
  `[0,1,2,2,1]` against `[0,2,2,1,1]` → 0.375; text labels), compared with
  `matthews_corrcoef` within 2 ULPs; `test_mcc_of_one_label_is_zero`
  (`[1,1]` against `[1,1]` → 0.0, no warning: scikit-learn's warning about
  the confusion matrix's shape is not copied);
  `test_mcc_counts_an_integer_and_a_double_one_as_one_class`;
  `test_mcc_takes_no_settings` (`mcc(adjusted=True)` raises `SqlearnError`).
- [ ] **Step 2: Run** them. Expected: FAIL, `mcc` not defined.
- [ ] **Step 3: Implement** the `mcc` branch. With `c` = sum of `n_both`, `s` =
      rows, `t_k` = `n_target`, `p_k` = `n_prediction`: numerator
      `c*s - sum(t_k*p_k)`, denominator
      `sqrt((s*s - sum(p_k²)) * (s*s - sum(t_k²)))`, integers until the one
      square root; 0.0 when the denominator is 0.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS.
- [ ] **Step 5: Commit** `feat: Matthews correlation in sq.metrics (#62)`.

### Task 3: brier

**Files:**
- Modify: `src/sqlearn/metrics/probability.py`,
  `src/sqlearn/metrics/__init__.py` (export `BrierScore`, `brier`)
- Test: `tests/src/sqlearn/metrics/test_probability.py`

**Interfaces:**
- Consumes: `Metric.compute`'s probability path (checks, classes, `[0, 1]`
  refusal).
- Produces: `@dataclass(frozen=True) class Brier(Metric)` with field
  `scale_by_half: bool | str = "auto"`; `__post_init__` sets `expression`;
  `__call__(**settings) -> Brier` (only `scale_by_half`, refusing any value but
  `True`, `False`, `"auto"`); `__repr__` shows a changed setting.
  `brier = Brier("brier", _unused, False, needs="predict_proba")`.

- [ ] **Step 1: Write the failing tests:**
  `test_brier_matches_scikit_learn_binary_and_multiclass` (the probe's
  matrices: two classes → 0.02, three → 0.14666…, `scale_by_half=True` on
  three → 0.07333…, `False` on two → 0.04), compared with `brier_score_loss`
  given the matrix and `labels=classes`, within 2 ULPs;
  `test_brier_scores_a_class_with_no_row` (target all 1 with classes `[0, 1]`
  → 0.28666…); `test_brier_takes_only_scale_by_half`
  (`brier(pos_label=1)` and `brier(scale_by_half="x")` raise `SqlearnError`);
  `test_brier_refuses_a_probability_above_one`;
  add `brier` to `test_the_direction_and_method_of_each_metric`
  (`greater_is_better` False, `needs` `"predict_proba"`); and in
  `tests/src/sqlearn/model_selection/test_search.py`,
  `test_a_search_by_brier_picks_the_lowest`.
- [ ] **Step 2: Run** them. Expected: FAIL, `brier` not defined.
- [ ] **Step 3: Implement** the aggregate: `favg` over rows of the sum over
  classes of `(p_k - CASE WHEN y = c_k THEN 1.0 ELSE 0.0 END)²`, times 0.5
  when halved (ADR 0033's compensated mean).
- [ ] **Step 4: Run**
      `uv run pytest tests/src/sqlearn/metrics` and
      `tests/src/sqlearn/model_selection`, `-q`.
      Expected: PASS.
- [ ] **Step 5: Commit** `feat: Brier score in sq.metrics (#62)`.

### Task 4: validation

**Files:**
- Create: `validation/sqlearn/metrics/validate_balanced.py`
- Modify: `validation/sqlearn/metrics/validate_probability.py`,
  `validation/__main__.py` (add the new runner)

**Interfaces:**
- Consumes: the scores from Tasks 1 to 3; `validation._cases` helpers, as
  `validate_classification.py` uses them.

- [ ] **Step 1: Write `validate_balanced.py`** after
      `validate_classification.py`: the same datasets, each case scored by
      sqlearn, scikit-learn and an exact reference (`Fraction` for balanced
      accuracy, `mpmath` for mcc), the bound stated in a comment with its
      reason.
- [ ] **Step 2: Add brier cases** to `validate_probability.py`, exact reference
  in `Fraction` of the doubles, halved and not.
- [ ] **Step 3: Run** `uv run python -m validation`. Expected: no `fail`; any
  anomaly is scikit-learn's own and is explained in the runner.
- [ ] **Step 4: Commit** `test: validate balanced accuracy, mcc and brier (#62)`
  with the new `.results.json` files.

### Task 5: documentation and project notes

**Files:**
- Modify: `docs/guide/evaluating-a-model.md` (a section "Scores for imbalanced
  classes", on the page's `rows`), `docs/reference/index.md`
  (`sqlearn.metrics.balanced_accuracy`, `.mcc`, `.brier`, `.CountMetric`,
  `.BrierScore`), any page that lists the metrics
  (`git grep -n average_precision docs/guide`), `CLAUDE.md` and `HANDOFF.md`
  (the area is built), `src/sqlearn/_errors.py` only if a warning class is
  added.

- [ ] **Step 1: Write the guide section:** the 95/5 example as a small table
  built in the page, accuracy against `balanced_accuracy` and `mcc`, then
  `brier` on `rows` with `classes=pipe.classes_`.
- [ ] **Step 2: Run**
      `rm -rf docs/reference/generated docs/_build && just build-docs`.
      Expected: build succeeded.
- [ ] **Step 3: Run** `just fmt`, then `just verify`. Expected: passes.
- [ ] **Step 4: Commit** `docs: balanced accuracy, mcc and brier (#62)`, with
  `validation/tests.json`.

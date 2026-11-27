---
type: plan
tags: [metrics, regression, deviance, pinball-loss, d2-score, plan]
summary: "Implementation plan for the regression metrics in sq.metrics: plain one-aggregate scores, range refusals, the Tweedie and pinball families with settings, the D² scores through a window stage for predict metrics, validation runners, and the guide."
related: [docs/specs/archived/library-regression-metrics.md, docs/adr/0054-d2-tweedie-on-a-constant-target.md, docs/adr/0042-a-metrics-settings-are-a-call.md]
---
# Regression metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** add `mse`, `msle`, `rmsle`, `median_absolute_error`, `max_error`,
`mape`, `explained_variance`, `poisson_deviance`, `gamma_deviance`,
`tweedie_deviance(power=)`, `pinball_loss(alpha=)`, `d2_tweedie(power=)`,
`d2_pinball(alpha=)` and `d2_absolute_error` to `sq.metrics`, matching
scikit-learn 1.9.1, computed in DuckDB, usable as a search's `metric=`.

**Architecture:** every score is a `Metric` in
`src/sqlearn/metrics/regression.py` whose aggregate runs in
`Metric.compute`'s one query. `Metric` gains three hooks, each a no-op by
default: `_outside` (range refusals counted in the same aggregate),
`_predict_stages` (window projections before the aggregate, for the D²
baselines) and `_finish` (the one-row NaN of the D² scores). The Tweedie and
pinball families are two frozen dataclasses with settings, built like
`BrierScore`.

**Tech Stack:** Python 3.12, DuckDB expressions, pytest, scikit-learn 1.9.1 as
the reference, `fractions` and mpmath for the validation's exact values.

**Spec:** `docs/specs/library-regression-metrics.md` (issue #63), ADR 0054.

## Global Constraints

- Same numbers, defaults, settings and refusals as scikit-learn 1.9.1; where
  it and the spec disagree, scikit-learn wins and the spec is corrected,
  except ADR 0054's constant target in `d2_tweedie`.
- Computation in SQL by DuckDB, one query, one read of the source; no rows
  fetched into Python.
- Settings are a call (ADR 0042), checked at the call; every warning and
  refusal has a `Fix:` line (ADR 0046); British prose, American identifiers
  (ADR 0010).
- Sums of many rows are compensated: `favg`, `fsum` (ADR 0033).
- No sample weights, no multi-output, no `force_finite=` (spec section 3).
- Commit with `(#63)` in the subject; `just fmt`, `just check` and
  `just test` pass first. Every module under `src/sqlearn/metrics/` keeps its
  `tests/src/sqlearn/metrics/test_<name>.py` and
  `validation/sqlearn/metrics/validate_<name>.py` (`just check-tests`).

## Review Focus

1. **`n * alpha` one rounding away from whole** (10 rows, alpha 0.3:
   `0.3 * 10` is `3.0000000000000004`): the pinball baseline must pick the rows
   scikit-learn's `_weighted_percentile` picks. Task 7 tests 10 rows at alpha
   0.3 and 0.7 against `d2_pinball_score`.
2. **Integer columns** (an INTEGER target, a BIGINT prediction): every score
   casts to DOUBLE, as `_error` does; `msle` and the deviances take them.
   Task 3 and Task 4 test an INTEGER target.
3. **A target far from zero** (mean 1e6, spread 1): `explained_variance` and
   `d2_tweedie` keep their digits as `r2` does. Task 2 and Task 6 test it
   within `rel=1e-9`.
4. **A row outside the range beside a NULL:** the NULL is refused first, as
   every metric refuses gaps before anything else. Task 3 tests it.
5. **A constant target whose mean is not a double** (0.1 a thousand times):
   `d2_tweedie` and `d2_pinball` give 1 or 0, never a huge negative number
   (ADR 0054). Task 6 and Task 7 test it.

---

### Task 1: mse, max_error, median_absolute_error, mape

**Files:**
- Modify: `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py`
  (export the four)
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Consumes: `Metric(name, expression, greater_is_better)`, `_error(y, p)`,
  `_fn(name, *args)`.
- Produces: `mse`, `max_error`, `median_absolute_error`, `mape`, each
  `Metric(..., False)`.

- [ ] **Step 1: Write the failing tests:** extend the parametrised
  `test_regression_metrics_match_scikit_learn` with `(mse,
  mean_squared_error)`, `(max_error, max_error)`, `(median_absolute_error,
  median_absolute_error)`, `(mape, mean_absolute_percentage_error)`; add them
  to `test_the_direction_of_each_metric` (all lower-better) and to
  `test_regression_metrics_refuse_missing_values_and_no_rows`;
  `test_mape_of_a_zero_target_is_scikit_learns_large_number` (`[0.0, 1.0]`
  against `[1.0, 1.0]` → `2251799813685248.0`, `==`);
  `test_median_absolute_error_of_an_even_count_is_the_middle_mean`
  (`[1, 2, 3, 4]` against `[1.5, 2, 2, 5]` → `0.75`).
- [ ] **Step 2: Run**
      `uv run pytest tests/src/sqlearn/metrics/test_regression.py -q`. Expected:
      FAIL, `sqlearn.metrics` has no `mse`.
- [ ] **Step 3: Implement** the four: `favg(e * e)`; `max(abs(e))`;
  `median(abs(e))`; `favg(abs(e) / greatest(abs(y), eps))` with
  `eps = 2.220446049250313e-16` (`np.finfo(float).eps`, written as a DOUBLE
  constant).
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS.
- [ ] **Step 5: Commit**
      `feat: mse, max error, median absolute error and MAPE (#63)`.

### Task 2: explained_variance

**Files:**
- Modify: `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Produces: `explained_variance = Metric("explained_variance", _ev, True)`.

- [ ] **Step 1: Write the failing tests:** add `(explained_variance,
  explained_variance_score)` to the parametrised match and the refusals, and
  higher-better to the direction test;
  `test_explained_variance_of_a_constant_target_follows_scikit_learn`
  (`[2, 2, 2]` against `[2, 2, 2]` → 1.0, against `[3, 3, 3]` → 1.0, against
  `[1, 2, 3]` → 0.0, each `==` `explained_variance_score`);
  `test_explained_variance_survives_a_large_offset` (as
  `test_r2_survives_a_large_offset`, `rel=1e-9`).
- [ ] **Step 2: Run** the file. Expected: FAIL, no `explained_variance`.
- [ ] **Step 3: Implement:** `1 - var_pop(e) / var_pop(y)`; when
  `min(y) = max(y)`, 1.0 if `var_pop(e) = 0` else 0.0 (the spec's corrected
  rule, section 5).
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS.
- [ ] **Step 5: Commit** `feat: explained variance in sq.metrics (#63)`.

### Task 3: range refusals, msle and rmsle

**Files:**
- Modify: `src/sqlearn/metrics/accuracy.py` (`Metric._outside`, used in
  `compute` for `"predict"` metrics), `src/sqlearn/metrics/regression.py`,
  `src/sqlearn/metrics/__init__.py`
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Produces: `Metric._outside(self, y: Expression, p: Expression) ->
  list[tuple[Expression, str]]`, default `[]`: each pair is a row condition
  and the words for those rows (`"a target at or below -1"`). `compute`
  counts each condition in the same aggregate, after the gap counts; after
  `_refuse_gaps`, the first non-zero count raises `SqlearnError` naming the
  metric, the count of rows of the total, the words, why (scikit-learn's
  reason) and a `Fix:` line. A metric whose `_outside` is non-empty is a small
  subclass of `Metric` (or the family classes of Tasks 4 and 5).
  `msle`, `rmsle`: lower-better, refusing a target or a prediction at or
  below -1.

- [ ] **Step 1: Write the failing tests:** add `(msle,
  mean_squared_log_error)`, `(rmsle, root_mean_squared_log_error)` to the
  match (with `y`, `p` drawn from `RNG.uniform(0, 5)`), the direction and the
  refusals; `test_msle_refuses_a_value_at_or_below_minus_one` (target
  `[-1.0, 1.0]` and, separately, prediction `[1.0, -2.0]` raise
  `SqlearnError` matching `"1 of 2 rows"` and `"Fix:"`; target `[-0.5, 1.0]`
  against `[1.0, 1.0]` → `0.9609060278364028` within `rel=1e-12`);
  `test_msle_takes_an_integer_target` (INTEGER `[1, 2, 3]` against DOUBLE
  predictions matches scikit-learn); `test_a_gap_is_refused_before_a_range`
  (target `[-3.0, NULL]` raises the NULL refusal, not the range one).
- [ ] **Step 2: Run** the file. Expected: FAIL, no `msle`.
- [ ] **Step 3: Implement** `_outside` in `Metric.compute` and the two
  scores: `favg((ln(1 + y) - ln(1 + p))²)` and its `sqrt`. DuckDB's `ln` of a
  negative is NaN and of 0 is `-inf`, so the aggregate runs to its end before
  the refusal is raised; the score of refused rows is never returned.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS, the classification and probability metrics unchanged.
- [ ] **Step 5: Commit** `feat: refuse out-of-range rows; msle and rmsle (#63)`.

### Task 4: the Tweedie deviances

**Files:**
- Modify: `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py`
  (export `TweedieDeviance`, `tweedie_deviance`, `poisson_deviance`,
  `gamma_deviance`), `src/sqlearn/metrics/accuracy.py` (`Metric.__call__`'s
  message and docstring name `tweedie_deviance`, `pinball_loss`,
  `d2_tweedie` and `d2_pinball` among the metrics with settings)
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Consumes: `Metric._outside` from Task 3.
- Produces: `@dataclass(frozen=True) class TweedieDeviance(Metric)` with
  fields `power: float = 0.0`, `d2: bool = False` (used in Task 6),
  `settable: bool = True`; `__post_init__` sets `expression`;
  `__call__(**settings) -> TweedieDeviance` (only `power`; refused when
  `settable` is False, with `Metric.__call__`'s message); `__repr__` shows
  `tweedie_deviance(power=1.5)` when set; `_outside` by power.
  `tweedie_deviance = TweedieDeviance("tweedie_deviance", _unused, False)`,
  `poisson_deviance` at power 1 and `gamma_deviance` at power 2, both
  `settable=False`.

- [ ] **Step 1: Write the failing tests:**
  `test_tweedie_deviance_matches_scikit_learn` parametrised over power
  `-1, 0, 1, 1.5, 2, 3` on `y = [1, 2, 3, 4]`, `p = [1.5, 2, 2, 5]` (the
  probe: `1.8333333333333306`, `0.5625`, `0.20917800547974497`,
  `0.13759610261391986`, `0.09490510899043825`, `0.05111111111111111`),
  within `rel=1e-12`; `poisson_deviance` and `gamma_deviance` equal
  `mean_poisson_deviance` and `mean_gamma_deviance` on random positive data;
  `test_tweedie_deviance_refuses_a_power_between_zero_and_one` (`power=0.5`,
  `power=True`, `power="1"` raise `SqlearnError` at the call; any value
  scikit-learn's parameter check refuses, found by probing `nan` and `inf`, is
  refused too); `test_each_deviance_refuses_its_range` (Poisson: target
  `[-1, 1]` and prediction `[0, 1]`; gamma: target `[0, 1]`; power -1:
  prediction `[0, 1]`; each a `SqlearnError` with `"Fix:"`; Poisson on target
  `[0, 1]` against `[1, 1]` → `1.0`); `test_poisson_takes_no_power`
  (`poisson_deviance(power=1)` raises `SqlearnError`);
  `test_a_search_by_a_deviance_with_a_power` (`sq.search(...,
  metric=sq.metrics.tweedie_deviance(power=1.5))` on a positive target picks
  by `min` and runs).
- [ ] **Step 2: Run** the file. Expected: FAIL, no `tweedie_deviance`.
- [ ] **Step 3: Implement** scikit-learn's `_mean_tweedie_deviance` per row,
  inside `favg`: power 0 `(y - μ)²`; power 1 `2 * (xlogy(y, y / μ) - y + μ)`
  with `xlogy(0, ·) = 0`; power 2 `2 * (ln(μ / y) + y / μ - 1)`; any other
  `2 * (max(y, 0)^(2-p) / ((1-p)(2-p)) - y * μ^(1-p) / (1-p) + μ^(2-p) /
  (2-p))` (the `max(y, 0)` only below power 0). Refused rows per the spec's
  table: below 0 `μ <= 0`; 1 up to 2 `y < 0` or `μ <= 0`; 2 and above
  `y <= 0` or `μ <= 0`.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS.
- [ ] **Step 5: Commit** `feat: Poisson, gamma and Tweedie deviances (#63)`.

### Task 5: pinball_loss

**Files:**
- Modify: `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py`
  (export `PinballLoss`, `pinball_loss`)
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class PinballLoss(Metric)` with fields
  `alpha: float = 0.5`, `d2: bool = False` (Task 7), `settable: bool = True`;
  `__call__(**settings) -> PinballLoss` (only `alpha`, a number from 0 to 1,
  not a bool); `__repr__` `pinball_loss(alpha=0.9)` when set.
  `pinball_loss = PinballLoss("pinball_loss", _unused, False)`.

- [ ] **Step 1: Write the failing tests:**
  `test_pinball_loss_matches_scikit_learn` (alpha 0, 0.1, 0.5, 0.9, 1 on
  random data, within `rel=1e-12`; on the probe's data alpha 0.9 →
  `0.26249999999999996`); `test_pinball_loss_takes_only_alpha_in_zero_to_one`
  (`alpha=1.5`, `alpha=-0.1`, `alpha=True`, `power=1` raise `SqlearnError`
  at the call); `test_a_search_by_a_pinball_loss` (`pinball_loss(alpha=0.9)`
  as a search's metric runs and picks by `min`).
- [ ] **Step 2: Run** the file. Expected: FAIL, no `pinball_loss`.
- [ ] **Step 3: Implement** `favg(alpha * greatest(y - p, 0) + (1 - alpha) *
  greatest(p - y, 0))`.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics -q`. Expected:
      PASS.
- [ ] **Step 5: Commit** `feat: pinball loss in sq.metrics (#63)`.

### Task 6: the window stage for predict metrics, and d2_tweedie

**Files:**
- Modify: `src/sqlearn/metrics/accuracy.py` (`Metric._predict_stages`,
  `Metric._finish`, both used in `compute`),
  `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py` (export
  `d2_tweedie`), `docs/adr/0054-*` only if the build finds the ADR wrong
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Consumes: `TweedieDeviance` from Task 4.
- Produces:
  `Metric._predict_stages(self, y: Expression, p: Expression) ->
  list[dict[str, Expression]]`, default `[]`: each dict is one projection
  over the rows, in order, its keys column names starting `__sqlearn_stage_`
  that a later dict may read by `ColumnExpression`. `compute` projects them
  in turn over the target and prediction columns, then calls
  `self.expression(y, p, *columns of the last dict)` in the one aggregate.
  `Metric._finish(self, value: object, total: int) -> float`, default
  `float(value)`. The probability path keeps `_stage` and `windows` as they
  are.
  `d2_tweedie = TweedieDeviance("d2_tweedie", _unused, True, d2=True)`; its
  stage is `{"__sqlearn_stage_mean": favg(y) OVER ()}`; its `_finish` warns
  (`SqlearnWarning`, why and `Fix:`) and returns `math.nan` when `total < 2`.

- [ ] **Step 1: Write the failing tests:**
  `test_d2_tweedie_matches_scikit_learn` over the powers of Task 4 on the
  probe's data (`0.413333333333334`, `0.55`, `0.606956520832571`,
  `0.6141248271175761`, `0.6103332516433315`, `0.5770114942528733`), within
  `rel=1e-12`; `test_d2_tweedie_of_one_row_is_nan_with_a_warning`;
  `test_d2_tweedie_of_a_constant_target_is_one_or_zero` (ADR 0054: `[2, 2]`
  against `[2, 2]` → 1.0, against `[1, 3]` → 0.0; a thousand `0.1` against
  themselves → 1.0, against `0.2` → 0.0);
  `test_d2_tweedie_survives_a_large_offset` (power 0 on a target of mean 1e6
  equals `r2_score` within `rel=1e-9`); `test_d2_tweedie_reads_the_source_once`
  (score a relation over a table, with DuckDB's profiling on
  (`PRAGMA enable_profiling = 'json'`, output to a file in `tmp_path`), and
  assert the profile holds one scan of that table).
- [ ] **Step 2: Run** the file. Expected: FAIL, no `d2_tweedie`.
- [ ] **Step 3: Implement** the two hooks in `Metric.compute` and
  `d2_tweedie`: `1 - fsum(dev(y, p)) / fsum(dev(y, mean))`, with the constant
  rule `min(y) = max(y)` → 1.0 when `fsum(dev(y, p)) = 0` else 0.0, in the
  same aggregate. The refused ranges are `tweedie_deviance`'s.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics
      tests/src/sqlearn/model_selection -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: D² Tweedie through a window stage (#63)`.

### Task 7: d2_pinball and d2_absolute_error

**Files:**
- Modify: `src/sqlearn/metrics/regression.py`, `src/sqlearn/metrics/__init__.py`
  (export `d2_pinball`, `d2_absolute_error`)
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Consumes: `PinballLoss` (Task 5), `_predict_stages` and `_finish` (Task 6).
- Produces: `d2_pinball = PinballLoss("d2_pinball", _unused, True, d2=True)`,
  `d2_absolute_error` the same at alpha 0.5 with `settable=False`.

- [ ] **Step 1: Write the failing tests:**
      `test_d2_pinball_matches_scikit_learn` (the probe: alpha 0.5 → `0.375`,
      alpha 0.9 → `-0.75`; random data at 4, 5, 7 and 10 rows and alpha 0.1,
      0.25, 0.3, 0.5, 0.7, 0.9, within `rel=1e-12`);
      `test_d2_pinball_picks_scikit_learns_rows_when_n_alpha_is_nearly_whole`
      (10 rows of distinct integers, alpha 0.3 and 0.7, `==`
      `d2_pinball_score`); `test_d2_absolute_error_is_d2_pinball_at_a_half` and
      takes no settings; `test_d2_pinball_of_a_constant_target_is_one_or_zero`
      (as Task 6); `test_d2_pinball_of_one_row_is_nan_with_a_warning`.
- [ ] **Step 2: Run** the file. Expected: FAIL, no `d2_pinball`.
- [ ] **Step 3: Implement** two stages: first `row_number() OVER (ORDER BY y)`
  and `count(*) OVER ()`; then the baseline `avg(y) FILTER (WHERE r = lo OR r
  = hi) OVER ()` with `lo`, `hi` the rows `_weighted_percentile(...,
  average=True)` averages. Read its source in scikit-learn 1.9.1 and compute
  `lo` and `hi` with the same double arithmetic (it scales `alpha * 100` and
  compares against a cumulative weight), so a nearly whole `n * alpha` picks
  its rows. Then `1 - fsum(pin(y, p)) / fsum(pin(y, q))` with the constant
  rule of Task 6.
- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/metrics
      tests/src/sqlearn/model_selection -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: D² pinball and absolute error (#63)`.

### Task 8: validation

**Files:**
- Modify: `validation/sqlearn/metrics/validate_regression.py` (its datasets,
  `BOUNDS`, `_exact`, `_SQL`, `_SKLEARN`, `_numpy`)

**Interfaces:**
- Consumes: every score of Tasks 1 to 7; `validation._cases` helpers as the
  runner already uses them.

- [ ] **Step 1: Add the scores** with exact references: `Fraction` over the
  doubles for `mse`, `max_error`, `median_absolute_error`, `mape`,
  `explained_variance`, `pinball_loss` and `d2_pinball` (alpha 0.1, 0.5,
  0.9), mpmath at `_cases.DIGITS` for `msle`, `rmsle`, the deviances (powers
  -1, 0, 1, 1.5, 2, 3) and `d2_tweedie`. Add a positive dataset for the
  deviances and the logs, an out-of-range dataset that sqlearn must refuse,
  and the constant datasets ADR 0054 names, whose reference is the ADR's
  rule, not scikit-learn. Each bound is set from the first measurement and
  stated with its reason in the comment above `BOUNDS`, as `r2`'s is.
- [ ] **Step 2: Run** `uv run python -m validation`. Expected: no `fail`; an
  anomaly is scikit-learn's own and explained in the runner's docstring.
- [ ] **Step 3: Commit** `test: validate the regression metrics (#63)` with
  the `.results.json` files.

### Task 9: documentation and project notes

**Files:**
- Modify: `docs/guide/evaluating-a-model.md` (a section "Choosing a
  regression score": when each fits, a small table built in the page, a
  search by `pinball_loss(alpha=0.9)`), `docs/reference/index.md` (each new
  name and `TweedieDeviance`, `PinballLoss`), any page listing the metrics
  (`git grep -n "metrics.r2" docs`), `CLAUDE.md` and `HANDOFF.md` (the eighth
  area is built, issue #63), `validation/tests.json`.

- [ ] **Step 1: Write the guide section and the reference entries.**
  `d2_tweedie`'s reference page names the ADR 0054 departure.
- [ ] **Step 2: Run**
      `rm -rf docs/reference/generated docs/_build && just build-docs`.
      Expected: build succeeded.
- [ ] **Step 3: Run** `just fmt`, then `just verify`. Expected: passes.
- [ ] **Step 4: Commit** `docs: the regression metrics (#63)`, with
  `validation/tests.json`; then a summary comment on #63 with deferred minors.

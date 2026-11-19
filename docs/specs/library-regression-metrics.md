---
type: spec
tags: [metrics, regression, deviance, pinball-loss, d2-score, library-breadth]
summary: "Spec for the regression metrics in sq.metrics: mse, msle, rmsle, median absolute error, max error, MAPE, explained variance, the Poisson, gamma and Tweedie deviances, the pinball loss and the D² scores, computed in SQL and matching scikit-learn 1.9.1, usable in a search."
related: [docs/specs/library-metrics.md, docs/specs/library-balanced-scores.md, docs/adr/0042-a-metrics-settings-are-a-call.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0033-the-mean-is-summed-with-compensation.md, docs/adr/0016-validation-method.md, docs/adr/0054-d2-tweedie-on-a-constant-target.md]
---
# Library breadth: regression metrics

The eighth area of part 3.3 of [the overview](../architecture/overview.md):
the regression scores after [balanced scores](library-balanced-scores.md).

Status: approved by Tomas on 2026-11-19. Issue #63.

## 1. Purpose

A regression model is scored today by `mae`, `rmse` and `r2` alone. That
covers a symmetric error on a target near normal, and little else. A count
(visits, claims) or a skewed amount (spend, durations) is judged by a
deviance, a quantile model by the pinball loss, a relative error by MAPE, a
worst case by the max error. Each is one number, so a search can rank by it,
and each runs in DuckDB over data larger than memory, as the earlier metrics
do.

## 2. What it looks like

```python
sq.metrics.mse.compute(rows, "target")
sq.metrics.median_absolute_error.compute(rows, "target")
sq.metrics.poisson_deviance.compute(rows, "target")
sq.metrics.tweedie_deviance(power=1.5).compute(rows, "target")
sq.metrics.pinball_loss(alpha=0.9).compute(rows, "target")
sq.metrics.d2_tweedie(power=2).compute(rows, "target")
sq.search(pipe, params=..., metric=sq.metrics.pinball_loss(alpha=0.9))
```

## 3. Goals, non-goals, anti-goals

- **Goals:** the scores listed in section 5, each giving scikit-learn 1.9.1's
  number, refusing what it refuses, and usable as a search's metric.
- **Non-goals:** sample weights and multi-output targets (no sqlearn metric
  has either); the classification D² scores `d2_brier_score` and
  `d2_log_loss_score`, which belong with the probability metrics; settings
  scikit-learn has only for multi-output (`multioutput=`) or weights.
- **`force_finite=` is left out** of `explained_variance` and of the existing
  `r2` (chosen by Tomas). scikit-learn's default, `True`, is what both
  compute; `False` turns a constant target's score into NaN or minus
  infinity, which a search cannot rank.
- **Anti-goals:** a second read of the source (it misaligns rows on a sampled
  or shuffled source, #59); a fetch of the rows into Python; a score that
  differs from scikit-learn's beyond the rounding bounds of ADR 0043 without
  a written reason.

## 4. Rules

The rules of the earlier metrics hold:

1. **They behave as scikit-learn 1.9.1's** functions named in section 5: the
   same numbers, defaults, settings and refusals. Where this text and
   scikit-learn disagree, scikit-learn is built and this spec is corrected,
   except where section 6 departs on purpose.
2. **Everything is computed in SQL** by DuckDB, in one query over the rows;
   what comes back is one number and the counts that check the rows.
3. **Settings are a call**
   ([ADR 0042](../adr/0042-a-metrics-settings-are-a-call.md)), checked when the
   call is made, and the message of `Metric.__call__` that lists the metrics
   with settings names the new ones too.
4. **The checks the earlier metrics make still apply:** an empty relation, a
   missing column, NULL or NaN are refused with a `Fix:` line. A value outside
   a metric's range is refused the same way, with the count of rows outside
   it, in the same query as the score.
5. **Sums are compensated** where a sum of many rows is taken
   ([ADR 0033](../adr/0033-the-mean-is-summed-with-compensation.md)): `favg` and
   `fsum`, as `mae` and `r2` use.

## 5. The scores

Each is a `Metric` in `sq.metrics`, reading the prediction column. "Lower" or
"higher" is its `greater_is_better`.

| Name | scikit-learn | Settings | Better | Refuses |
|---|---|---|---|---|
| `mse` | `mean_squared_error` | none | lower | |
| `msle` | `mean_squared_log_error` | none | lower | a target or prediction at or below -1 |
| `rmsle` | `root_mean_squared_log_error` | none | lower | as `msle` |
| `median_absolute_error` | `median_absolute_error` | none | lower | |
| `max_error` | `max_error` | none | lower | |
| `mape` | `mean_absolute_percentage_error` | none | lower | |
| `explained_variance` | `explained_variance_score` | none | higher | |
| `poisson_deviance` | `mean_poisson_deviance` | none | lower | a negative target, a prediction at or below 0 |
| `gamma_deviance` | `mean_gamma_deviance` | none | lower | a target or prediction at or below 0 |
| `tweedie_deviance` | `mean_tweedie_deviance` | `power=0.0` | lower | by `power`, as scikit-learn |
| `pinball_loss` | `mean_pinball_loss` | `alpha=0.5` | lower | |
| `d2_tweedie` | `d2_tweedie_score` | `power=0.0` | higher | as `tweedie_deviance` |
| `d2_pinball` | `d2_pinball_score` | `alpha=0.5` | higher | |
| `d2_absolute_error` | `d2_absolute_error_score` | none | higher | |

Notes on each, from probing scikit-learn 1.9.1:

- **`mape`** divides by `max(|target|, eps)`, eps the double's machine
  epsilon, so a target of 0 gives a very large score, not an error. sqlearn
  gives the same number.
- **`explained_variance`** is one minus the variance of the error over the
  variance of the target. A constant target scores 1 when predicted exactly
  and 0 otherwise, as `r2` does.
- **`tweedie_deviance(power=)`** takes a power at most 0 or at least 1; a
  power between 0 and 1 is refused at the call. Power 0 is the squared error,
  1 Poisson, 2 gamma. The ranges refused follow scikit-learn's per power: for
  a power below 0 a prediction at or below 0; for 1 to 2 a negative target or
  a prediction at or below 0; for 2 and above a target or prediction at or
  below 0. `poisson_deviance` and `gamma_deviance` are `tweedie_deviance` at
  power 1 and 2, under their own names.
- **`pinball_loss(alpha=)`** takes alpha from 0 to 1; anything else is
  refused at the call.
- **The D² scores** are one minus the model's deviance over the deviance of
  a constant guess taken from the target: its mean for `d2_tweedie`, its
  alpha-quantile for `d2_pinball` (linear interpolation, DuckDB's
  `quantile_cont`), its median for `d2_absolute_error` (`d2_pinball` at
  alpha 0.5).

## 6. Edge cases, and where sqlearn departs

- **A D² score on one row** is not defined: scikit-learn returns NaN with a
  warning. sqlearn returns NaN with a warning that says why and has a `Fix:`
  line ([ADR 0046](../adr/0046-sqlearn-warns-the-user-chooses.md)).
- **A D² score on a constant target:** `d2_pinball` scores 1 when predicted
  exactly and 0 otherwise, as `r2` does. `d2_tweedie` raises a
  `ZeroDivisionError` in scikit-learn 1.9.1 (the baseline's deviance is 0).
  sqlearn gives it the same 1-or-0 as `d2_pinball` and `r2`, a departure
  recorded in [ADR 0054](../adr/0054-d2-tweedie-on-a-constant-target.md). A
  target is constant when its minimum equals its maximum, computed in the same
  aggregate: the window's mean over identical values can be one rounding off,
  which would leave the baseline's deviance tiny but not 0. The same test
  serves `d2_pinball`, `d2_absolute_error` and `explained_variance`.

## 7. How it is built

Chosen by Tomas: **the D² baseline comes from a window stage.** Each row
first gets the constant guess as a window over the whole relation
(`avg(target) OVER ()`, `quantile_cont(target, alpha) OVER ()`), then the one
aggregate scores the model's deviance and the baseline's row by row. This is
the path `roc_auc` already takes for its ranks (`Metric.windows`, `_stage`);
it opens to `"predict"` metrics, which today never stage. One query, one read
of the source, and no cancellation from expanding the baseline's deviance into
sums.

The trade-off accepted with it: a window over the whole relation holds every
row, as `roc_auc`'s ranks already do. `median_absolute_error` and the
quantile in `d2_pinball` are exact quantiles, which DuckDB also computes by
holding the values.

Approaches considered:

1. **Window stage** (chosen): above.
2. **Sums in one pass:** expand the baseline's Tweedie deviance into sums of
   the target (Σy, Σy^(2−p), Σlog y) inside a plain aggregate. No window, but
   it cancels for a target far from zero (the trap `r2` avoids with
   `var_pop`), and the pinball baseline cannot be expanded, so it would still
   need approach 1.
3. **Two queries:** fetch the mean or quantile first, then score with it as a
   constant. Simplest SQL, but it reads the source twice, which misaligns on a
   sampled or shuffled source (#59).

## 8. Checks

- Validation against scikit-learn 1.9.1 and against exact fractions, in the
  validation runner of the regression metrics (ADR 0016), over each setting
  named here and every refusal.
- Tests through the public calls, named in the glossary's terms; a search
  ranking by a metric with a setting.
- A section in the guide's "Evaluating a model" page on choosing a regression
  score, the reference pages, and the docstrings' examples.

## 9. Names

scikit-learn's names without `mean_` and `_score`, as `mae`, `rmse`, `r2` and
`balanced_accuracy` already are: `mse`, `msle`, `rmsle`, `mape` (the short
forms in common use), `median_absolute_error` and `max_error` (no short form
in common use), `explained_variance`, `poisson_deviance`, `gamma_deviance`,
`tweedie_deviance`, `pinball_loss`, `d2_tweedie`, `d2_pinball`,
`d2_absolute_error`. The spec's call.

## 10. Left to the builder

Which modules the scores land in, how the range checks join the query, the
exact warning and refusal texts, and how `Metric.windows` opens to
`"predict"` metrics. Any edge case this text does not name follows
scikit-learn 1.9.1, found by probing it.

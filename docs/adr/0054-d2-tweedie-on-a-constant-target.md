---
type: adr
tags: [metrics, regression, d2-score, scikit-learn, departure]
summary: "Records that sq.metrics.d2_tweedie scores a constant target 1 when predicted exactly and 0 otherwise, where scikit-learn 1.9.1's d2_tweedie_score raises ZeroDivisionError; a target is constant when its minimum equals its maximum."
related: [docs/specs/archived/library-regression-metrics.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# 0054: D² Tweedie on a constant target

Status: accepted (2026-11-19). Issue #63. A departure from scikit-learn, as
[ADR 0003](0003-scikit-learn-style-api.md) requires one to be recorded.

## Context

A D² score is one minus the model's deviance over the deviance of a constant
guess, the target's mean for `d2_tweedie`. On a constant target that guess is
exact, its deviance is 0, and the ratio is undefined. scikit-learn 1.9.1's
`d2_pinball_score` and `r2_score` then score 1 when the model's loss is 0
and 0 otherwise; its `d2_tweedie_score` raises `ZeroDivisionError` (on a
constant zero target at power 1.5 it returns NaN instead, where sqlearn gives
0). A search that meets such a fold would stop.

sqlearn takes the mean as a window over the rows. Over many identical values
that mean can come back one rounding away from the value, leaving the
baseline's deviance tiny but not 0, and the score a large negative number.

## Decision

- **`sq.metrics.d2_tweedie` scores a constant target as `d2_pinball` and
  `r2` do:** 1 when every prediction equals the target, 0 otherwise.
- **A target is constant when its minimum equals its maximum,** computed in
  the same aggregate as the score, not when the baseline's deviance is 0.

## Consequences

- `d2_tweedie` returns a value where scikit-learn raises; its reference page
  says so.
- The validation compares this case against the rule above, not against
  scikit-learn.
- If a later scikit-learn gives this case a value, sqlearn follows it and this
  ADR is replaced.

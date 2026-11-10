---
type: adr
tags: [mean, accuracy, numerics, favg, validation, duckdb]
summary: "Records that sqlearn's mean uses DuckDB's compensated favg, which matched the exact mean where plain avg drifted 119 ULPs, while the standard deviation stays stddev_pop for now; superseded in part by ADR 0044."
related: [docs/adr/0016-validation-method.md, docs/adr/0032-the-median-is-exact-by-sorting.md]
---
# 0033: The mean is summed with compensation

Status: accepted (2026-11-05). Made during the core build, reviewed after it.
Superseded in part by
[ADR 0044](0044-the-standard-deviation-in-two-staged-passes.md): the standard
deviation is now two compensated passes, not `stddev_pop`.

## Context

Validation ([ADR 0016](0016-validation-method.md)) compared sqlearn's mean with
an exact one on 100,000 rows. DuckDB's plain `avg` was 119 ULPs off; `favg`,
which sums with Kahan's compensation, was 0; numpy was 0 to 1. The bounds in
`validation/` are set from measurement, so the weaker sum was a choice, not a
limit.

## Decision

- `sq.avg(x)` builds `favg(x)`, and every mean in sqlearn (Impute's mean,
  Scale's centre) uses it. The validation bounds were measured again and
  tightened.
- The population standard deviation stays DuckDB's `stddev_pop` (12 ULPs off)
  for now. A two-pass compensated variance is issue #28.

## Consequences

- `favg` is slightly slower than `avg`.
- `favg` gives NaN, not infinity, on an infinity or an overflowing sum, and
  prints as `favg`. Infinity is refused anyway
  ([ADR 0030](0030-infinity-is-refused.md)).
- At 1M rows DuckDB's parallel `stddev_pop` is not repeatable (2 to 57 ULPs
  over 40 runs), so the large validation set stays at 100,000 rows until
  #28.

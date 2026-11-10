---
type: adr
tags: [std, accuracy, numerics, favg, compositor, larger-than-memory, validation]
summary: "Records that sq.agg.std is a staged aggregate computed in two compensated passes (favg mean, then sqrt(favg((x - mean)^2))), exactly 0 when every value is the same, about 2.9 times the one-pass cost with no loss of reach under 64 MB, validated within 2 ULPs; it may hold other staged aggregates but not another standard deviation, nor sit inside a quantile or mode."
related: [docs/adr/0033-the-mean-is-summed-with-compensation.md, docs/adr/0036-staged-aggregates-anywhere-in-a-learned-value.md, docs/adr/0032-the-median-is-exact-by-sorting.md, docs/adr/0043-repeatable-within-rounding.md, docs/benchmarks/standard-deviation.md]
---
# 0044: The standard deviation in two staged passes

Status: accepted (2026-11-10). Found as
[#28](https://github.com/glaucis/sqlearn/issues/28). Supersedes the line of
[ADR 0033](0033-the-mean-is-summed-with-compensation.md) that keeps the
standard deviation as DuckDB's `stddev_pop`.

## Context

`sq.agg.std`, StandardScaler's spread, was DuckDB's `stddev_pop`, a one-pass
streaming algorithm. On the validation's 100,000 values near 1,000 it was 12
ULPs from the exact population standard deviation (mpmath at 50 digits); numpy
and scikit-learn, with two passes, were 0 to 1. On 18 million values it was 700
ULPs off on one thread. A second pass needs the mean before the deviations, so
it cannot be one aggregate in the learn stage's row.

## Decision

- **Two staged passes.** `sq.agg.std(x)` is a marker, as the median is
  ([ADR 0032](0032-the-median-is-exact-by-sorting.md)). Per learn stage, the
  compositor writes one stage of every standard deviation's mean, with the
  compensated `favg` (as `sq.agg.mean`), then one row of
  `sqrt(favg((x - mean) ^ 2))`, over the stage's input cross-joined with that
  one row of means. Each pass is one streaming aggregate; nothing per row is
  carried but one scalar mean per column. `ddof=0`; missing values are left
  out as in every aggregate.
- **Exactly 0 when every value is the same** (or there is one), by
  `min(x) = max(x)` beside the second pass: the compensated mean of 100,000
  copies of 1/3 is not 1/3, the deviations from it are not 0, and Scale's
  zero-spread rule needs 0. A column of infinities stays NaN.
- **Bound: 2 ULPs** in the validation, for `sq.agg.std` and Scale's standard
  divisor, down from 16. The worst measured is 1 (small and large sets); the
  large set gave 0 in 2 of 30 runs, because DuckDB's threads finish in another
  order ([ADR 0043](0043-repeatable-within-rounding.md)). The house rule's
  power of two would be 1; 2 leaves that ULP of thread order beside the worst
  case. DuckDB's own `stddev_pop`, still the "duckdb" reference, is then an
  anomaly on the large set (12 ULPs, past four times the bound).
- **Nesting**
  ([ADR 0036](0036-staged-aggregates-anywhere-in-a-learned-value.md)): the
  standard deviation may sit anywhere in a learned value, inside another
  aggregate too, and its argument may hold the other staged aggregates
  (`std(x - median(x))`): their one-row stages read the stage's input and come
  before the passes, which cross-join them. Two cases are refused, because the
  stages cannot be ordered in one learn stage, not because they mean nothing: a
  standard deviation inside another (both are the same two passes), and a
  quantile, mode or target statistic of an expression holding a standard
  deviation (those stages come first). Either can be learned in an earlier step.

## Consequences

- Cost, measured on 20,000,000 rows from Parquet
  ([benchmark](../benchmarks/standard-deviation.md)): under 64 MB on one
  thread, learning it through sqlearn takes 1.15 s against 0.40 s for the one
  pass, about 2.9 times; as SQL alone about 2.5 times. Every form fits 64 MB:
  no loss of reach. It lands 1 ULP from the exact value where `stddev_pop`
  lands 700 (one thread) or 41 to 47 (eight).
- Every step using `sq.agg.std` improves at once; Scale's standard divisor is
  within 1 ULP on the validation's sets.
- An overflowing sum gives NaN, not infinity: on `[1e300, -1e300, 1e300]`
  `favg` overflows to NaN, where `stddev_pop` gave infinity. Infinity in the
  data is refused by the steps anyway ([ADR 0030](0030-infinity-is-refused.md)).
- `sq.agg.var` is still DuckDB's `var_pop` (20 ULPs on the large set), and
  Scale's zero-spread rule judges the standard deviation by it.
- Sums stay order-dependent across threads (ADR 0043); two passes improve
  accuracy, not byte-for-byte repeats.

## Amended by #44

A staged aggregate's argument may hold other staged aggregates, never a plain
DuckDB aggregate. `sq.agg.std(x - sq.agg.mean(x))` (likewise a median or a
mode of it) is refused in the house form, naming the step and saying a plain
aggregate cannot sit inside a staged one: the stage reads its argument per
row, where one value of a whole column has no row. The spread of `x - mean(x)`
is the spread of `x`; staging arbitrary aggregates would cost compositor code
nobody needs.

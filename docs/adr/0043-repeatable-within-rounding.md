---
type: adr
tags: [search, repeatability, rounding, duckdb, threads, ties]
summary: "Records that a seeded search is repeatable within rounding, not byte for byte: the same settings and best, each score within a measured bound of ULPs, because DuckDB's parallel sums of doubles round by thread order; scores within 16 ULPs of the best tie, the first tried winning."
related: [docs/specs/library-model-selection.md, docs/adr/0016-validation-method.md, docs/adr/0022-one-search-with-pluggable-methods.md]
---
# 0043: Repeatable within rounding

Status: accepted (2026-11-09). Changes the model-selection spec's
"Repeatable" line ([spec](../specs/library-model-selection.md) §9). Found
as [#36](https://github.com/glaucis/sqlearn/issues/36).

## Context

The spec promised that the same seeds give the same `results_`, byte for
byte. On a busy machine they did not: a fold's score differed by one ULP
between two runs (`0.5428417959876596` against `…595`), and `just verify`
failed on it.

The cause is DuckDB's parallelism, not sqlearn's SQL. An aggregate that adds
doubles (`favg`, `stddev_pop`, `var_pop`) sums each thread's share, then
combines the shares in the order the threads finish, which the operating
system decides. Addition of doubles rounds at every step, so a different
order can give a different last digit. Learning `impute.median` then
`scale.standard` on 5,000 rows under load gave a different `scale_` in 20
runs of 50; with DuckDB on one thread, none. On data above one row group
(about 120,000 rows) even a plain scan runs on several threads. Aggregates
that pick or count (median, quantiles, min, max, counts) are not affected.

Exactly rounded, order-free sums would restore byte-for-byte repeats, but
DuckDB has none, and building them costs speed on the large data sqlearn is
for, to protect a digit no decision depends on. numpy, scikit-learn and
other libraries that sum on threads make the same trade.

## Decision

- **The promise:** the same seeds try the same settings and pick the same
  best; each score agrees within a bound of ULPs set from measurement
  (ADR 0016), 1 ULP on the validation's search under load.
- **A wobble never changes the best.** Mean scores within
  `TIE_TOLERANCE` (16 machine epsilons, relative) of the best tie, and the
  first setting tried wins, as ties already did. A real difference between
  settings is far larger.
- The validation's run-twice case compares settings, best and scores within
  the bound, not bytes.

## Consequences

- `results_` may differ in a score's last digit or two between runs; the
  guide says so.
- Optuna picks its next setting from the scores so far, so in a rare near-tie
  a one-ULP difference could send it another way. Not seen in the
  measurement (20 runs under load); recorded here rather than prevented.
- [#28](https://github.com/glaucis/sqlearn/issues/28) (a two-pass variance)
  still improves accuracy; it does not make sums order-free.

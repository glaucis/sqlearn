---
type: adr
tags: [aggregates, quantiles, standard-deviation, compensated-sum, sqlearn]
summary: "Consolidates sq.agg learning rules: exact sorted median and quantiles, Kahan-compensated means, two-pass variance, and nested aggregates in levels."
related: [docs/adr/archived/0032-the-median-is-exact-by-sorting.md, docs/adr/archived/0033-the-mean-is-summed-with-compensation.md, docs/adr/archived/0036-staged-aggregates-anywhere-in-a-learned-value.md, docs/adr/archived/0044-the-standard-deviation-in-two-staged-passes.md, docs/adr/archived/0051-aggregates-learn-in-levels.md, docs/adr/0030-infinity-is-refused.md, docs/adr/0043-repeatable-within-rounding.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md]
mdindex: [type=0fc814, tags=c473bf, summary=70cb3f]
---
# 0078: How aggregates learn: exact quantiles by sorting, compensated sums, levels

Status: accepted (2026-11-27). Written on Tomas's decision of 2026-11-27, in the
docs cleanup, to consolidate the records below: it states their rules as they
stand and takes no new decision. Supersedes
[ADR 0032](archived/0032-the-median-is-exact-by-sorting.md),
[ADR 0033](archived/0033-the-mean-is-summed-with-compensation.md),
[ADR 0036](archived/0036-staged-aggregates-anywhere-in-a-learned-value.md),
[ADR 0044](archived/0044-the-standard-deviation-in-two-staged-passes.md) and
[ADR 0051](archived/0051-aggregates-learn-in-levels.md), with their inline
amendments.

## Context

How `sq.agg`'s aggregates learn was spread over five records. ADR 0032 made
the median exact by sorting, since DuckDB's `median` holds every value and
never spills; its 2026-11-10 amendment added `approx=True` and the
out-of-memory error. ADR 0033 summed the mean with compensation and left the
standard deviation as DuckDB's `stddev_pop`. ADR 0036 let the median,
quantiles and mode sit anywhere in a learned value, superseding ADR 0032's
whole-value rule; its #41 amendment changed how their one row is read. ADR
0044 replaced ADR 0033's standard deviation with two compensated passes,
refused two orderings, and was amended by #44 (a plain aggregate inside a
staged one refused) and #42 (the variance in the same passes). ADR 0051 then
learned every nesting in levels, removing the refusals of ADR 0036's and
0044's amendments and ADR 0044's ordering refusals, but for an aggregate
inside a target statistic.

## Decision

- **The median and the quantiles are exact, computed from sorted values**,
  with a sort that spills to disk, so they learn on data larger than memory
  and match scikit-learn (ADR 0032). DuckDB's `median`, `quantile` and `mad`
  hold every value outside the buffer manager and do not spill, so what
  `sq.agg` builds, at every level, is sqlearn's own sort, not them
  (ADR 0051). Missing values (NULL and NaN) are left out; with an even count
  the two middle values are averaged, as DuckDB's `median` does (ADR 0032).
- **`approx=True`** on `sq.agg.median` and `sq.impute.median` gives an
  approximate median in constant memory, close to the exact one but not
  equal to it; the old Python built DuckDB's `approx_quantile(x, 0.5)`. Its
  error against numpy's median is measured in the validation and stated in
  the docstring. It is the user's choice: the default stays exact, and
  sqlearn never switches by itself (ADR 0032 amendment, ADR 0046).
- **When the sort runs out of memory**, the learn raises an `SqlearnError`
  in the house form, not DuckDB's `OutOfMemoryException`. It names the steps
  learning in the failed query (all of them, since DuckDB's text cannot say
  which sorted), or "a step" if none is known, and the fixes: more memory
  (`sq.set_config(memory=...)` on sqlearn's own connection, `SET
  memory_limit` on a connection passed to `sq.set_config(connection=...)`,
  which sqlearn never re-limits), fewer threads (`SET threads = 1` on a
  passed connection), or `approx=True`. The median is blamed and
  `approx=True` offered only when a step learning in the failed query sorts
  for an exact median or quantile; otherwise the Why says DuckDB's
  `memory_limit` is too small for what the step learns (ADR 0032 amendment).
- **Every mean is summed with compensation** (Kahan's): `sq.agg.mean`, the
  imputer's mean, the scaler's centre. The validation's bounds were measured
  with it and tightened (ADR 0033). The old Python built DuckDB's `favg`.
- **The standard deviation is two compensated passes**: the compensated mean,
  then the square root of the compensated mean of `(x - mean) ^ 2`. Nothing
  per row is carried but one mean per column. `ddof=0`; missing values are
  left out, as in every aggregate (ADR 0044).
- **`sq.agg.var` is learned in the same two passes**, and `sq.agg.std` is
  its square root, so `var(x)` and `std(x)` share one pair of passes; the
  scaler's zero-spread rule reads the variance (ADR 0044, amended by #42).
- **Exactly 0 when every value is the same** (or there is one), for both
  the variance and the standard deviation, by a `min(x) = max(x)` check
  beside the second pass: the compensated mean of 100,000 copies of 1/3 is
  not 1/3, and the scaler's zero-spread rule needs 0. A column of infinities
  stays NaN (ADR 0044, amended by #42).
- **Bound: 2 ULPs** in the validation for `sq.agg.std` and the standard
  scaler's divisor: the worst measured is 1, and the bound leaves one ULP of
  thread order beside it (ADR 0043, ADR 0044).
- **Aggregates nest anywhere in a learned value**, inside another aggregate
  too: `sq.agg.mean(sq.fn.abs(x - sq.agg.median(x)))`,
  `sq.agg.iqr(x) / sq.agg.median(x)`, `sq.agg.std(x - sq.agg.mean(x))`, a
  standard deviation inside another, a quantile or mode of an expression
  holding a standard deviation (ADR 0036, ADR 0051).
- **Levels.** An aggregate's level is 1 when its argument holds none, else
  one more than the highest inside it. An inner aggregate is complete before
  the outer one's argument is computed on any row, so each level beyond the
  first is another pass over the data; every aggregate of a level, over all
  the step's columns, shares that level's passes (ADR 0051).
- **Still refused:** an aggregate inside a target statistic's arguments
  (ADR 0051).
- **Missing inner values** are fed to the outer aggregate as NULL; each
  aggregate does with them what its SQL does (`sq.agg`'s give NULL, `count`
  gives 0). sqlearn wraps nothing (ADR 0046, ADR 0051).
- **A user's own DuckDB aggregates** (`median`, `mad`) are learned as
  written; only what sqlearn builds is its spilling sort (ADR 0051).
- **No algebraic rewriting:** `std(x - mean(x))` is computed as written
  (ADR 0051).
- **The old Python implemented this as staged SQL** (now under
  `old_python/`): `sq.agg`'s median, quantiles, mode and standard deviation
  were markers the Python compositor turned into one-row stages; every
  quantile of a learn stage shared one sort (each column tagged and numbered
  by one window, since two sorts in one statement hold memory together and
  do not fit where one does); the standard deviation's mean and second pass
  were stages cross-joined with the input; the levels were CTEs of one
  `WITH` query whose input DuckDB materialized; a learned value that was one
  whole staged aggregate was read once beside the learn stage's row, and
  only the stages a larger value read were cross-joined into the scan (#41:
  the target encoder at 10,000 categories on 1,000,000 rows went from 46.8 s
  to 4.0 s, [benchmark](../benchmarks/archived/category-lookup.md)); and a
  marker `sq.agg` did not build was refused. The C++ group's design decides
  the mechanics (ADR 0070).

## Consequences

- One exact median of 20M rows under 64 MB took 7.9 s and gave the same
  value as DuckDB's `median`; on small data the sort is slower than an
  in-memory median (ADR 0032). The reach is DuckDB's sort, measured by
  memory limit in [the median's reach](../benchmarks/median-reach.md).
- The compensated sum is slightly slower than a plain one, and gives NaN,
  not infinity, on an infinity or an overflowing sum (`[1e300, -1e300,
  1e300]`). Infinity in the data is refused anyway
  ([ADR 0030](0030-infinity-is-refused.md)).
- The two-pass standard deviation, on 20,000,000 rows from Parquet under 64
  MB on one thread, cost about 2.9 times the one pass through sqlearn (1.15 s
  against 0.40 s), with no loss of reach, and landed 1 ULP from the exact
  value where `stddev_pop` landed 700 (one thread) or 41 to 47 (eight)
  ([benchmark](../benchmarks/standard-deviation.md)).
- Sums stay order-dependent across threads
  ([ADR 0043](0043-repeatable-within-rounding.md)): two passes improve
  accuracy, not byte-for-byte repeats.
- Cost per level beyond the first: one pass over the input for its plain
  aggregates, a sort when it holds a quantile, a count when it holds a mode,
  two passes when it holds a standard deviation or variance. Learned values
  without nesting keep their cost (ADR 0051).
- The median absolute deviation learns 85% to 92% of the rows one median
  does under 32, 64 and 128 MB on one thread: the two sorts share the limit
  ([the median's reach](../benchmarks/median-reach.md)). It was validated at
  0 ULPs from the exact value on every dataset (bound 1) (ADR 0051).
- ADRs 0032, 0033, 0036, 0044 and 0051 are archived in `archived/` and keep
  their numbers.

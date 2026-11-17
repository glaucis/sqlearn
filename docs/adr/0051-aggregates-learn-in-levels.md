---
type: adr
tags: [aggregates, nested, compositor, median, std, learn, larger-than-memory]
summary: "Records that an aggregate inside another is learned in levels: each aggregate's level is one more than the deepest inside its argument, each level is the staged machinery over the learn stage's input cross-joined with the levels below, in one WITH query; it amends ADR 0036 and 0044, whose refusals of nesting go."
related: [docs/specs/learn-nested-aggregates.md, docs/adr/0036-staged-aggregates-anywhere-in-a-learned-value.md, docs/adr/0044-the-standard-deviation-in-two-staged-passes.md, docs/adr/0032-the-median-is-exact-by-sorting.md, docs/adr/0012-static-and-dynamic-steps.md]
---
# 0051: Aggregates learn in levels

Status: accepted (2026-11-17). Issue #49,
[spec](../specs/learn-nested-aggregates.md). Amends
[ADR 0036](0036-staged-aggregates-anywhere-in-a-learned-value.md) and
[ADR 0044](0044-the-standard-deviation-in-two-staged-passes.md).

## Context

A learn stage computes its aggregates in a fixed order: quantile sort, mode
count and target statistics, then the standard deviation's passes, then a
plain one-row select. A staged aggregate inside a plain one fits that order
(`mean(abs(x - median(x)))`); every other nesting was refused
(`std(x - mean(x))`, the median absolute deviation, a standard deviation
inside another) or reached DuckDB's raw binder error (`sum(x - mean(x))`).
Tomas ruled on 2026-11-10 that sqlearn learns them.

An inner aggregate must be complete before the outer one's argument can be
computed on any row, so nesting needs a second pass over the data whatever
the engine. DuckDB 2.0 has no rule merging the two.

## Decision

- **Levels.** Each aggregate's level is 1 when its argument holds none, else
  one more than the highest inside it. Level `k` computes all its aggregates
  over the learn stage's input cross-joined with the one-row results of the
  levels below, in the old fixed order. Every aggregate of a level, over all
  the step's columns, shares the level's passes.
- **One query.** The levels are CTEs of the run's `WITH` query. The input,
  referenced by every level, is materialized by DuckDB (by default since 1.4)
  and spills to disk when memory runs short: the source is read once, and
  DuckDB decides RAM or disk.
- **sqlearn's own aggregates, not DuckDB's holistic ones.** The medians and
  quantiles at every level stay sqlearn's sort (ADR 0032), which spills;
  DuckDB's `median`, `quantile` and `mad` hold every value outside the
  buffer manager and do not.
- **Refusals left:** a marker `sq.agg` did not build, and an aggregate
  inside a target statistic's arguments.
- **Missing inner values** are fed to the outer aggregate as NULL; each
  aggregate does with them what its SQL does (`sq.agg`'s give NULL,
  `count` gives 0). sqlearn wraps nothing (ADR 0046).
- **A user's own DuckDB aggregates** (`median`, `mad`) are learned as
  written; only what sqlearn builds stays its spilling sort.

## Considered

- **One fixed extra pass in front:** the two examples on #49, but not a
  standard deviation inside another or deeper nesting; each new shape another
  special case.
- **Window functions** (`median(x) OVER ()`): DuckDB's median there holds the
  column in memory; the reach beyond memory goes.
- **Scalar subqueries** in place of CTEs: DuckDB reads the file once per
  subquery (it shares only subplans ending in an aggregate, a distinct or a
  window, and does not cache local files in 2.0).

## Consequences

- The refusals of ADR 0036's and 0044's amendments go; ADR 0044's two
  ordering refusals go too.
- Cost per level beyond the first: one pass over the materialized input for
  its plain aggregates, a sort when it holds a quantile, a count when it
  holds a mode, two passes when it holds a standard deviation or variance.
  Learned values without nesting keep their cost.
- Measured on 20,000,000 rows from Parquet on one thread, the median of three
  alternating runs, load average 17 to 23
  (`validation/benchmarks/nested_cost.py`): the median absolute deviation
  took 5.58 s against 2.66 s for `median(abs(x))` (its second sort costs
  about what the first does), `std(x - mean(x))` 0.77 s against 0.63 s for
  `std(x)`, `sum(x - mean(x))` 0.25 s against 0.09 s for `sum(x)` (one more
  compensated pass and the input materialized).
- Reach: the median absolute deviation learns 85% to 92% of the rows one
  median does under 32, 64 and 128 MB on one thread (100,000,000 rows under
  128 MB; [the measurement](../benchmarks/median-reach.md)). The two sorts
  share the limit.
- Validated: 0 ULPs from the exact value on every dataset, as DuckDB's `mad`,
  numpy and scipy are (bound 1).
- No algebraic rewriting: `std(x - mean(x))` is computed as written.

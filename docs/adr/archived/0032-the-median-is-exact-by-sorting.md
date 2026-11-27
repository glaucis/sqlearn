---
type: adr
tags: [median, impute, larger-than-memory, sql, numerics, compositor]
summary: "Records that sq.median is computed exactly by sorting in a CTE of its own, which spills to disk, because DuckDB's median aggregate does not, and an approximate one would break the scikit-learn match."
related: [docs/adr/0015-duckdb-expressions-no-sqlglot.md, docs/adr/0016-validation-method.md, docs/adr/0002-sql-on-duckdb-execution-engine.md]
---
# 0032: The median is exact, by sorting

Status: accepted (2026-11-05). Made during the core build, reviewed after it.
Archived (2026-11-27): superseded by
[ADR 0078](../0078-how-aggregates-learn.md), which states how aggregates learn
in full.

## Context

`Impute(strategy="median")` must run on data larger than memory and match
scikit-learn. Checked on DuckDB 2.0: the `median` aggregate holds every value
and never spills (out of memory on 20M rows at a 64 MB limit). The
alternatives were an approximate median (`approx_quantile`), which breaks the
match, or dropping the median from the larger-than-memory promise.

## Decision

`sq.median(x)` returns a marker, and the compositor computes the median from
the values sorted by DuckDB, whose sort spills to disk. For one column the
idea is:

```sql
SELECT avg(x) FROM (
  SELECT x, row_number() OVER (ORDER BY x) AS r, count(*) OVER () AS n
  FROM stage WHERE x IS NOT NULL AND NOT isnan(x)
) WHERE r IN ((n + 1) // 2, (n + 2) // 2)
```

Missing values (NULL and NaN) are left out; with an even count the two middle
values are averaged, as DuckDB's `median` does. Every median of a learn stage
shares one sort: the values of each column are tagged and numbered by one
window ordered by tag, then value, because two sorts in one statement hold
memory together and do not fit where one does. The result joins the learn
stage's one row. The marker must be a whole learned value
(`{"median": sq.median(x)}`); inside a larger expression it is refused.

## Consequences

- One median of 20M rows under 64 MB took 7.9 s and gave the same value as
  `median`.
- One sort per learn stage with medians: slower than an in-memory median on
  small data.
- The reach is DuckDB's sort: under 64 MB a plain `ORDER BY` fails at about
  60M rows, and the medians of two columns reach 20M (issue #27).

## Amended 2026-11-10

The default stays exact by sorting. Two things are added (issue #27, ADR 0046):

- `approx=True` on `sq.agg.median` and `sq.impute.median` builds DuckDB's
  `approx_quantile(x, 0.5)`: constant memory, close to the exact median but
  not equal to it. It is the user's choice; sqlearn never switches by itself.
  Its error against numpy's median is measured in validation and stated in the
  docstring.
- When the sort runs out of memory, the learn raises an `SqlearnError` in the
  house form, not DuckDB's `OutOfMemoryException`. DuckDB's text names no stage,
  so it names the steps learning in the failed statement (all of them: it cannot
  say which sorted), or "a step" if none is known; and the fixes: more memory,
  fewer threads, or `approx=True`. More memory is `sq.set_config(memory=...)`
  on sqlearn's own connection and `SET memory_limit` on a connection passed to
  `sq.set_config(connection=...)`, which sqlearn never re-limits; fewer threads
  is `SET threads = 1` on a passed connection. The median is blamed and
  `approx=True` offered only when a step learning in the failed statement
  sorts for an exact median or quantile (its `_quantile` stage is in the
  statement); otherwise the Why says DuckDB's memory_limit is too small for
  what the step learns.

The reach by memory limit is in `docs/benchmarks/median-reach.md` and the
imputing guide.

---
type: adr
tags: [metrics, precision, recall, f1, averaging, api]
summary: "Records that a metric's settings are given by calling it, which returns a configured copy (sq.metrics.f1(average=\"macro\")), and that the classification metrics count per class in one grouped DuckDB query and average those few counts in Python."
related: [docs/specs/archived/library-metrics.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/archived/0022-one-search-with-pluggable-methods.md]
---
# 0042: A metric's settings are a call

Status: accepted (2026-11-09). Written with the plan for the metrics area
([spec](../specs/archived/library-metrics.md) §3 and §5). Amended by
[ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md): the Python
bindings hold no logic, so the averaging is no longer done in Python.
Amended by [ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md): the metrics are
designed for C++, not translated from the `Metric` and `ClassificationMetric`
classes.

## Context

scikit-learn's `precision_score`, `recall_score` and `f1_score` take
`average=`, `pos_label=` and `zero_division=`. A search takes them through a
scorer: a string such as `"f1_macro"` for the common forms, `make_scorer` for
the rest. sqlearn's search takes a `Metric` object (`metric=`), not a string,
and until now no metric had a setting.

ADR 0003 asks that a departure from scikit-learn's form gets its own ADR.

## Decision

- **Calling a metric returns a configured copy.** `sq.metrics.f1` is
  scikit-learn's default (`average="binary"`, `pos_label=1`,
  `zero_division="warn"`); `sq.metrics.f1(average="macro")` is a new metric
  with that setting, and `f1` itself is unchanged (metrics are frozen). The
  settings are keywords, checked by name, and take scikit-learn's names and
  values; an unknown one is refused.
- **A metric without settings refuses a call** (`accuracy(average=...)`),
  saying it takes none.
- **The classification metrics count per class.** One grouped query over the
  labels brings back, for each class, its rows in the target, in the
  prediction, and in both. The averaging is arithmetic on those few rows,
  done in Python, so nothing the size of the data leaves DuckDB.
- **Label checks run first, in their own aggregate**: no rows, NULL, NaN,
  non-whole numbers. A continuous column would make the grouped query return
  a row per distinct value, so it is refused before that query runs.

## Consequences

- No scorer strings: `"f1_macro"` in scikit-learn is
  `sq.metrics.f1(average="macro")` in sqlearn, as the name map says.
- `Metric` gains `__call__`; the classification metrics are a subclass,
  `ClassificationMetric`, whose `compute` replaces the one-aggregate path. The
  six earlier metrics keep their behaviour.
- A score can now be NaN (`zero_division=nan`), so the search ranks a NaN
  mean last, as `GridSearchCV` does.

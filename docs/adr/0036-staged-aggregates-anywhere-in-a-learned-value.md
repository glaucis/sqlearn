---
type: adr
tags: [aggregates, median, quantile, mode, learn, compositor, larger-than-memory]
summary: "Records that sq.agg's staged aggregates (quantiles, median, mode) may appear anywhere in a learned value, including inside another aggregate, which supersedes the part of ADR 0032 requiring a median marker to be a whole learned value."
related: [docs/adr/0032-the-median-is-exact-by-sorting.md, docs/adr/0033-the-mean-is-summed-with-compensation.md, docs/specs/library-preprocessing.md]
---
# 0036: Staged aggregates anywhere in a learned value

Status: accepted (2026-11-06). Made during the preprocessing build.
Extended by [ADR 0044](0044-the-standard-deviation-in-two-staged-passes.md):
the standard deviation is staged too, with two orderings refused.
Supersedes the part of [ADR 0032](0032-the-median-is-exact-by-sorting.md) that
says a median marker must be a whole learned value.

## Context

ADR 0032 computes the median from sorted values, outside the learn stage's one
row, and so required the marker to be a whole learned value
(`{"median": sq.median(x)}`); inside a larger expression it was refused. The
preprocessing steps need more: the robust scaler's spread is a quantile
difference, and the mean absolute deviation about the median has the median
inside another aggregate.

## Decision

`sq.agg`'s staged aggregates (the quantiles, the median and the mode) may
appear anywhere in a learned value, including inside another aggregate:

```python
{"mad": sq.agg.mean(sq.fn.abs(x - sq.agg.median(x)))}
```

- Every quantile of a learn stage still shares one sort, as ADR 0032 decided,
  however deeply they are nested.
- The reach is still DuckDB's sort, which spills to disk
  ([issue #27](https://github.com/glaucis/sqlearn/issues/27)).

## Consequences

- A step's `learn` may combine staged aggregates freely with the others, as
  `sq.agg.iqr(x) / sq.agg.median(x)`.
- The refusal ADR 0032 described is gone; nothing else in it changes.

## Amended by #44

"Combine staged aggregates freely" stops at a plain DuckDB aggregate inside a
staged one's argument (`sq.agg.std(x - sq.agg.mean(x))`): it is refused, naming
the step. See [ADR 0044](0044-the-standard-deviation-in-two-staged-passes.md).

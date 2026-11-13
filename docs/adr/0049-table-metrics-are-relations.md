---
type: adr
tags: [metrics, confusion-matrix, relation, api, out]
summary: "Records that the table metrics (confusion_matrix, classification_report, roc_curve, precision_recall_curve) are functions that hand back a lazy DuckDB relation, convertible with out=, not arrays or a string, and that they are not Metrics, so a search refuses them."
related: [docs/specs/library-more-metrics.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/adr/0042-a-metrics-settings-are-a-call.md]
---
# 0049: Table metrics are relations

Status: accepted (2026-11-13). Written with the second metrics slice
([spec](../specs/library-more-metrics.md) §4 and §8).

## Context

scikit-learn's `confusion_matrix` and `roc_curve` return NumPy arrays and
`classification_report` returns a string. sqlearn computes in DuckDB, where a
curve over a billion rows is a query, not a billion-element array, and where
a result is a relation (ADR 0023). ADR 0003 asks that a departure from
scikit-learn's form gets its own ADR.

## Decision

- **A table metric is a function** `f(rel, target, ..., out=None)` and hands
  back a lazy DuckDB relation, sorted as scikit-learn orders its output.
  `out=` converts it as `Pipeline.predict`'s does (`"pandas"`, `"polars"`,
  `"numpy"`, `"arrow"`, or a file).
- **It is not a `Metric`.** A table cannot rank a search, so a search given
  one as `metric=` refuses, saying which functions are tables.
- **A matrix is one row per true label and one column per predicted label,** the
  first column named as the target and the others by the label's text as DuckDB
  renders it. A label DuckDB cannot name (empty text), one with the target's
  name, and two that differ only by case (DuckDB names do not) are refused, with
  a `Fix:`.

## Consequences

- No report string: `classification_report(...).show()` prints the table, and
  `out="pandas"` gives it to the user's own plotting or formatting.
- `sq.metrics.confusion_matrix(rel, "y", out="numpy")` is a dict of columns,
  not scikit-learn's single array.
- Scores stay `Metric`s and work in a search; tables are for looking.

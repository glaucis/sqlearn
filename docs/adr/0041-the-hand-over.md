---
type: adr
tags: [models, feed, pandas, polars, arrow, stream, memory]
summary: "Records the forms a model is handed data in (numpy by default, pandas, Polars, Arrow, and a stream through partial_fit), that text columns reach pandas, Polars and Arrow as categories with NULL kept missing, and that a fold too large for memory is refused, never swapped."
related: [docs/adr/0017-models-from-other-libraries.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/specs/library-model-selection.md]
---
# 0041: The hand-over

Status: accepted (2026-11-07). Made during the model-selection build; builds
on [ADR 0023](0023-lazy-results-out-and-feed.md), which put `feed=` on the
model and left every form but numpy for later.

## Context

A model from another library (ADR 0017) is handed the prepared rows. Until
now that was a 2-D float64 numpy array only, so text had to be encoded by a
step, even for models that read categories themselves: CatBoost, LightGBM,
XGBoost and scikit-learn's histogram boosting. And a fold larger than memory
had nowhere to go but swap.

## Decision

`sq.Model(model, feed=...)` names the form (spec section 3):

| `feed=` | `fit(X, y)` gets | text columns |
|---|---|---|
| `"numpy"` (default) | a 2-D float64 array | refused, as before |
| `"pandas"` | a `DataFrame` | `category` dtype |
| `"polars"` | a `DataFrame` | `Categorical` |
| `"arrow"` | a `pyarrow.Table` | dictionary-encoded |
| `"stream"` | one batch at a time, as numpy, through `partial_fit` | refused |

- **numpy stays the default**, as the core has it: a plain scikit-learn model
  needs nothing new.
- **Each form comes from DuckDB's own method** (`fetchnumpy`, `df`, `pl`,
  `to_arrow_table`), and its library is imported only when used; none
  becomes a dependency (ADR 0005). A missing one is an error naming
  `uv add <name>`.
- **Text columns reach the model as categories.** DuckDB hands over plain
  strings, so each `VARCHAR` feature is cast after the fetch. A NULL stays
  missing (NaN, null), never a category of its own. CatBoost still takes
  `cat_features=` as it would without sqlearn.
- **The target goes over in the same form** as the features: a numpy array, a
  pandas or Polars `Series`, a `pyarrow.ChunkedArray`. A missing target is
  refused in every form.
- **Predictions are asked for in the same form**, one batch at a time: each
  Arrow batch is converted as a whole fetch is, text as categories.
- **In a search, each model trains in its own form**: a preparation's
  training rows are fetched once per distinct form among its models, and one
  form's rows are in memory at a time.
- **`"stream"` learns in pieces** through `partial_fit`, with `rows=` or
  `megabytes=` (about 100 MB by default), `epochs=1`, `shuffle=True` and
  `seed=0`; these settings are refused with any other form.
- **Never swap.** Before a form other than `"stream"` loads a fold, its size
  is estimated and compared with the memory budget; a fold that will not fit
  is refused before the fetch, suggesting `feed="stream"`.

## Consequences

- Text no longer needs an encoding step for a model that reads categories.
- A batch's categories are the batch's own values: a model that reads
  categories by code rather than by value would mislead at predict.
  LightGBM, CatBoost and scikit-learn's histogram boosting map by value.
- Further forms DuckDB produces (PyTorch tensors, say) are added the same
  way.

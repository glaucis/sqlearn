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
| `"polars"` | a `DataFrame` | `Enum` |
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
- **Polars gets an `Enum`, not a `Categorical`** (the spec said
  `Categorical`; changed during the build, Ruling R9). An `Enum`'s codes are
  its list's order, kept through `to_physical`, `to_arrow` and `to_pandas`,
  which is how libraries take a Polars frame. A `Categorical`'s codes follow
  a process-wide insertion order, and `to_arrow`/`to_pandas` re-encode it to
  the values present, so no list could fix them.
- **One category list per text column, from training.** Training records
  each text feature's categories, sorted, from its rows (per fold in a
  search); every prediction batch is cast with that list first and any new
  values after it, sorted, so a known value keeps its code and a new one is
  never dropped to missing. The lists travel with the trained pipeline.
- **The target goes over in the same form** as the features: a numpy array, a
  pandas or Polars `Series`, a `pyarrow.ChunkedArray`. A missing target is
  refused in every form, counted as SQL NULLs
  (a NaN target is a value).
- **Predictions are asked for in the same form**, one batch at a time: each
  Arrow batch is converted as a whole fetch is, text as categories.
- **In a search, each model trains in its own form**: a preparation's
  training rows are fetched once per distinct form among its models, and one
  form's rows are in memory at a time.
- **`"stream"` learns in pieces** through `partial_fit`, with `rows=` or
  `megabytes=` (about 100 MB by default), `epochs=1`, `shuffle=True` and
  `seed=0`; these settings are refused with any other form, and `rows=`
  with `megabytes=`. Epoch `e` streams the rows in the order of
  `hash(row, seed, e)` (`shuffle=False`: the input's order), the first call
  is given `classes=` (the sorted distinct targets, computed in SQL) when
  `partial_fit` takes it. A model without `partial_fit`, text, a missing
  target and a missing pyarrow are refused before the first batch: without
  pyarrow the rows cannot be read in batches, and fetching them whole
  would defeat the stream. In a search each stream model streams its fold's
  training rows itself.
- **Never swap.** Before a form other than `"stream"` loads a fold, its size
  is estimated and compared with the memory budget; a fold that will not fit
  is refused before the fetch, suggesting `feed="stream"`. The budget is one
  for the process, `sq.set_config(memory=...)` (bytes or a size such as
  `"8GB"`), by default 80% of physical memory. DuckDB's share is its
  connection's `memory_limit`, counted as at most half the budget, and the
  hand-over may use the rest (Ruling R11). sqlearn's own connection is given
  half the budget as its `memory_limit`, re-applied when the budget changes;
  a connection the user passed is never changed, and its default limit (80%
  of physical memory, the same as the budget) or no limit at all counts as
  half, so a passed connection is not left with nothing. The estimate is
  rows times 8 bytes per number column and 64 bytes plus the average length
  per text column, from one aggregate query. Prediction batches are not
  checked (each is small); prediction's one whole fetch without pyarrow is.

## Consequences

- Text no longer needs an encoding step for a model that reads categories.
- A model that reads category codes rather than values (XGBoost before 3.1,
  code reading `cat.codes`) reads the same code for every value seen in
  training, at train and at predict, in a search's held-out rows as at its
  fit, in every form: pandas codes, Polars `Enum` codes (also after
  `to_arrow` and `to_pandas`), Arrow dictionary indices. A value new at
  predict gets a code after the training list, which the model never saw.
- Further forms DuckDB produces (PyTorch tensors, say) are added the same
  way.

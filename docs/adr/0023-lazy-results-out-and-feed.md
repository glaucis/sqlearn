---
type: adr
tags: [api, apply, output, lazy, numpy, arrow, pandas, models]
summary: "Records that results are lazy by default: apply returns a DuckDB relation, out= turns it into what the user wants to see or save, and feed= sets the form handed to a model, chosen per model by default."
related: [docs/adr/0005-runtime-dependencies.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/0022-one-search-with-pluggable-methods.md]
---
# 0023: Lazy results, `out=` and `feed=`

Status: accepted (2026-11-04). Departs from scikit-learn, whose `transform`
returns a numpy array by default ([ADR 0003](0003-scikit-learn-style-api.md)).

## Context

scikit-learn's `transform` returns numpy, or pandas after `set_output`. For
sqlearn a numpy default would make numpy a runtime dependency (DuckDB offers it
only as an optional extra; [ADR 0005](0005-runtime-dependencies.md)), would load
data larger than memory into memory by default, and would lose the column names
(after OneHot, `city_Vilnius` becomes column 7), scikit-learn's best-known pain
point. Models take data in different forms: scikit-learn wants numpy; LightGBM
takes Arrow tables; some models learn in batches.

## Decision

**Lazy by default.** `apply` returns a DuckDB relation: nothing is computed
until it is used, column names are kept, and in a notebook it shows its first
rows, computing only those.

**`out=`: what the user wants to see or save.** One word, per call:

```python
rel = pipe.apply("big.parquet")  # lazy
df = pipe.apply("big.parquet", out="pandas")  # or "polars", "numpy", "arrow"
pipe.apply(
    "big.parquet", out=sq.out_parquet("prepared.parquet")
)  # or out_csv, out_json
```

Writing to a file streams from DuckDB to disk (`COPY ... TO`), never through
Python's memory. `out="numpy"` and the others need their library installed,
like any outside library. `sq.set_config(out="pandas")` sets a default for the
session, as scikit-learn's `set_config(transform_output=...)` does; `out=` on
a call overrides it.

**`feed=`: what a model is given.** Data becomes eager only when it is handed to
the model. The form is chosen per model, from the same table of known models as
the default search spaces
([ADR 0022](0022-one-search-with-pluggable-methods.md)), and the user can
override it:

```python
pipe.train("big.parquet", target="churned")  # numpy for LogisticRegression
pipe.train("big.parquet", target="churned", feed="arrow")  # the user's choice
```

| `feed` | memory | for |
|---|---|---|
| numpy | all of it, converted | scikit-learn |
| Arrow table | all of it, columnar, no conversion | LightGBM and others that take Arrow |
| Arrow stream | one batch at a time | models that learn piece by piece |

## Consequences

- sqlearn still depends only on `duckdb`.
- The slice uses only numpy, for scikit-learn's `LogisticRegression`; Arrow
  and batches are built after it
  ([issue #21](https://github.com/glaucis/sqlearn/issues/21)).
- A model with no entry in the table is fed numpy, and a wrong guess is fixed
  with `feed=`.

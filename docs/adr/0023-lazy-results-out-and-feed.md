---
type: adr
tags: [api, apply, output, lazy, numpy, arrow, pandas, models]
summary: "Records that results are lazy by default: apply returns a DuckDB relation, out= turns it into what the user wants to see or save, and feed= sets the form handed to a model, numpy by default."
related: [docs/adr/0005-runtime-dependencies.md, docs/adr/0013-learn-apply-train-predict.md, docs/adr/0017-models-from-other-libraries.md, docs/adr/archived/0022-one-search-with-pluggable-methods.md]
---
# 0023: Lazy results, `out=` and `feed=`

Status: accepted (2026-11-04). Departs from scikit-learn, whose `transform`
returns a numpy array by default ([ADR 0003](0003-scikit-learn-style-api.md)).
Amended by [ADR 0034](0034-a-grouped-api.md): `sq.out_parquet` and its kin
are now `sq.out.parquet`, `sq.out.csv` and `sq.out.json`. Amended by
[ADR 0057](0057-numpy-is-a-runtime-dependency.md): numpy is a runtime
dependency beside `duckdb`.

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
the model. The default is numpy for every model; the user can override it.
Choosing the form per model automatically is left for later: one parameter
keeps that change invisible to users.

```python
pipe.train("big.parquet", target="churned")  # numpy
pipe.train("big.parquet", target="churned", feed="arrow")  # the user's choice
```

| `feed` | memory | for |
|---|---|---|
| numpy | all of it, converted | scikit-learn |
| Arrow table | all of it, columnar, no conversion | LightGBM and others that take Arrow |
| Arrow stream | one batch at a time | models that learn piece by piece |

**`feed` travels with the model.** `sq.Model(estimator, feed=...)` wraps an
outside model and carries sqlearn's settings for it; a plain model is
`sq.Model(model)` with `feed="numpy"`. In a search over several models each
candidate keeps its own:

```python
params = [
    {"model": [LogisticRegression()], "model__C": [0.1, 1, 10]},
    {"model": [sq.Model(LGBMClassifier(), feed="arrow")]},
]
```

`feed` is not a search parameter, which would try every model with every form.
A session-wide mapping by model class (`sq.set_config(feed={...})`) may come
later.

## Consequences

- sqlearn still depends only on `duckdb`.
- The slice uses only numpy, for scikit-learn's `LogisticRegression`; Arrow
  and batches are built after it
  ([issue #21](https://github.com/glaucis/sqlearn/issues/21)).
- Models that would take Arrow better still get numpy unless the user says
  otherwise.

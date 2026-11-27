---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [decompose, pca, dimensionality-reduction, whiten, explained-variance, gram, scikit-learn]
summary: "How sq.decompose.pca replaces many correlated columns with a few components: the shortcut and the general form, n_components as a count or a fraction of the variance, whiten, how it learns (means in SQL, batches into numpy, applying in SQL), and the refusals with their fixes."
related: [docs/specs/library-decomposition.md, docs/adr/0057-numpy-is-a-runtime-dependency.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/guide/selecting-features.md, docs/guide/scaling.md, docs/guide/tuning-a-model.md]
---

# Reducing columns

Where selecting features drops columns, `sq.decompose` replaces them: it finds
the directions along which the data varies most and writes each row as its
position along the first few. Columns that move together become one. The
output has fewer columns, named `pca0`, `pca1` and so on, and they replace the
input columns.

`sq.decompose.pca` is scikit-learn's `PCA` with `svd_solver="covariance_eigh"`:
the same components, signs, explained variances, names, defaults and refusals.

```{code-cell} python
import numpy as np
import pandas as pd

import sqlearn as sq

rng = np.random.default_rng(0)
n = 200
size, shade = rng.normal(size=n), rng.normal(size=n)
data = pd.DataFrame(
    {
        "width": 3 * size + rng.normal(scale=0.1, size=n),
        "height": 2 * size + rng.normal(scale=0.1, size=n),
        "shade": shade + rng.normal(scale=0.1, size=n),
        "noise": rng.normal(scale=0.1, size=n),
        "label": "x",
    }
)
```

Four columns, but two things vary: a size that `width` and `height` share, and
a shade. Keep two components:

```{code-cell} python
pipe = sq.Pipeline([sq.decompose.pca(n_components=2)]).learn(data)
pca = pipe["pca"]
pca.explained_variance_ratio_, pipe.columns_out_
```

The first component carries 92% of the variance and the second 8%.
`components_` has one row per component and one number per input column;
`pipe.apply(data)` gives the new columns, placed after the last input column,
as every step that works on whole rows places the columns it creates.

```{code-cell} python
pca.components_[0], pipe.apply(data, out="pandas").head(3)
```

By default it works on the numeric columns, so `label` passes through. Name
columns to choose them: `sq.decompose.pca("width", "height")` or
`cols=`. The general form is
`sq.decompose(*names, method="pca", n_components=None, whiten=False,
cols=None)`; `pca` is its only method for now.

## How many components

`n_components` is one of:

- `None` (the default): every component, the smaller of the rows and the
  columns;
- a whole number, from 0 up to that: keep that many;
- a fraction strictly between 0 and 1: keep the fewest components whose
  explained variance adds up to more than the fraction.

```{code-cell} python
many = sq.Pipeline([sq.decompose.pca(n_components=0.95)]).learn(data)
many["pca"].n_components_, many.columns_out_
```

A whole number above the smaller of the rows and the columns is refused at
`learn`, as scikit-learn refuses it at `fit`.

## Whiten

`whiten=True` divides each output by the square root of its explained
variance, so every output has variance 1 and none dominates a model that cares
about scale:

```{code-cell} python
white = sq.Pipeline([sq.decompose.pca(n_components=2, whiten=True)]).learn(data)
white.apply(data, out="pandas")[["pca0", "pca1"]].std()
```

## Scale first

PCA follows the variance, so a column in large units dominates. Put `sq.scale()`
before it when the columns do not share units:

```python
sq.Pipeline([sq.impute(), sq.scale(), sq.decompose.pca(n_components=3)])
```

A search can try several sizes, and learns once for all of them:

```python
sq.search(pipe, params={"pca__n_components": [5, 10, 20]}, metric=sq.metrics.f1)
```

What is learned is the whole decomposition, which does not depend on
`n_components` or `whiten`; those two only choose the output. Changing them
never learns again. Changing the columns or the steps before PCA does.

## How it learns

PCA is the one step that brings rows into Python, and only to learn
([ADR 0058](../adr/0058-a-gram-step-builds-xtx-in-numpy.md)). It is a **Gram
step**: it learns from XᵀX of its centred columns.

1. DuckDB finds the mean of each column, in SQL.
2. DuckDB runs the steps before PCA, subtracts the means, and hands the rows
   over in batches of a size the memory budget allows. numpy adds each batch's
   XᵀX into one p-by-p matrix. Only a batch and the matrix are in memory, so
   the data can be larger than memory.
3. numpy finds the eigenvalues and eigenvectors of the covariance, and
   scikit-learn's steps follow: largest first, a sign chosen for each
   component, the ratios, the cut.

Applying is SQL only: each output is one expression, the dot product of the
row's centred values with that component's weights, the weights and means
constants in the query, so it runs in parallel on data of any size and as part
of the one query of the pipeline. numpy is a runtime dependency for this
([ADR 0057](../adr/0057-numpy-is-a-runtime-dependency.md)). The learn needs
room for four p-by-p matrices; when they cannot fit, it is refused before any
row is read, and a small memory budget makes small batches, not a failure.

The query holds the p² weights, written once as one matrix, and DuckDB needs
memory to read it, outside its `memory_limit`: about 0.4 GB at 200 columns,
0.7 GB at 300 and 4.6 GB at 1,000, growing about as p²
([PCA on data larger than memory](../benchmarks/gram-streaming.md)).

## Refusals

Each message has a `Why:` and a `Fix:`.

| when | what it refuses | the fix |
|---|---|---|
| building | `n_components` that is negative, 1 or more as a fraction, or `"mle"` | a whole number, a fraction between 0 and 1, or `None` |
| `learn` and `apply` | such an `n_components` set on the step afterwards | the same |
| `learn` | `n_components` above the smaller of rows and columns | that number or fewer, or `None` |
| `learn` and `apply` | a missing value (NULL or NaN), or an infinite one, even with `n_components=0` | `sq.impute()` first, or leave the rows out |
| `learn` | values so large their products overflow 8-byte numbers | `sq.scale()` first |
| `learn` | fewer than two rows | more data |
| `learn` | a column chosen by name that is not numeric | `cols=` with numeric columns, or encode it first |

```{code-cell} python
try:
    sq.Pipeline([sq.decompose.pca(n_components=9)]).learn(data)
except sq.errors.SqlearnError as error:
    print(error)
```

A column that never changes adds nothing: its weight is 0 in every
component, and `sq.select.variance()` drops it first if you would rather not
carry it. When every chosen column is constant the total variance is 0, the
ratios are undefined, and PCA warns, as scikit-learn's does, with a `Fix:`.

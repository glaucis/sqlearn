---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [bin, kbinsdiscretizer, binarizer, quantile, uniform, edges, scikit-learn]
summary: "How sq.bin puts numbers into bins by uniform or quantile edges, matching scikit-learn's KBinsDiscretizer 1.9, what happens when edges merge, and how binarize splits at a threshold."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md]
---

# Binning: numbers into groups

`sq.bin` replaces a number by the index, from 0, of the bin it falls in.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0]})
pipe = sq.Pipeline([sq.bin.uniform(n=4)]).learn(data)
pipe["uniform"].edges_, pipe.apply(data, out="pandas")["x"].tolist()
```

The minimum is 0 and the maximum 4, so the three inner edges are 1, 2 and 3.
A value's bin is the number of inner edges at or below it: 1 is in bin 1, 4 in
the last bin, and a value below the minimum is in bin 0.

| shortcut | the inner edges | scikit-learn |
|---|---|---|
| `sq.bin.uniform(n=5)` | evenly between the minimum and the maximum | `KBinsDiscretizer(strategy="uniform", encode="ordinal")` |
| `sq.bin.quantile(n=5)` | the exact quantiles at `i / n` | `KBinsDiscretizer(strategy="quantile", encode="ordinal")` |
| `sq.bin.binarize(threshold=0.0)` | none: 1 above the threshold, else 0 | `Binarizer(threshold=0.0)` |

The general form is `sq.bin(columns, method="quantile", n=5)`.

## Quantile edges

The quantiles are those of scikit-learn 1.9 (numpy's
`averaged_inverted_cdf`), computed exactly over all the rows, so the edges
agree with `KBinsDiscretizer`. Quantiles of repeated values can coincide. As
scikit-learn does, an edge within `1e-8` of the one before it is merged away,
so there are fewer bins, and a constant column has one bin. The merge is said
once per `learn`, with a `SqlearnWarning`:

```{code-cell} python
import warnings

skewed = pd.DataFrame({"x": [0.0] * 8 + [1.0, 2.0]})
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    merged = sq.Pipeline([sq.bin.quantile(n=5)]).learn(skewed)
print(merged["quantile"].edges_)
print(caught[0].category.__name__)
```

## Binarize

`sq.bin.binarize` learns nothing. A value equal to the threshold is 0, as in
scikit-learn:

```{code-cell} python
signs = pd.DataFrame({"x": [-1.0, 0.0, 2.5]})
sq.Pipeline([sq.bin.binarize()]).learn(signs).apply(signs, out="pandas")["x"].tolist()
```

## Other things to know

- The output is an integer column that replaces the input. NULL and NaN stay
  NULL.
- A column holding infinity, or with no present value, is refused.
- `keep=True` keeps the input and adds the bin beside it, named
  `<column>_<step>` (`x_uniform`).

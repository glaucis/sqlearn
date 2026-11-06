---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [scale, standardscaler, robustscaler, minmaxscaler, maxabsscaler, normalizer, scikit-learn]
summary: "How sq.scale centres and divides numeric columns (standard, robust, minmax, maxabs), how a near-constant spread is handled, and how sq.scale.normalize divides each row by its norm."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0033-the-mean-is-summed-with-compensation.md, docs/adr/0032-the-median-is-exact-by-sorting.md]
---

# Scaling: centre and divide

`sq.scale` turns each numeric column into `(x - center) / spread`. The four
scalers differ only in what the centre and the spread are, so they are four
presets of one general form, `sq.scale(columns, method=...)`.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame({"x": [1.0, 2.0, 3.0, 10.0]})
pipe = sq.Pipeline([sq.scale.robust()]).learn(data)
pipe["robust"].center_, pipe["robust"].scale_
```

The median of `x` is 2.5 and the spread, the interquartile range, is 3, so
the 10 becomes `(10 - 2.5) / 3 = 2.5`, a value that does not drag the others
with it:

```{code-cell} python
pipe.apply(data, out="pandas")
```

## The shortcuts

| shortcut | centre | spread | scikit-learn |
|---|---|---|---|
| `sq.scale.standard()` | mean | standard deviation | `StandardScaler()` |
| `sq.scale.robust()` | median | interquartile range | `RobustScaler()` |
| `sq.scale.minmax()` | minimum | range, then onto `(0, 1)` | `MinMaxScaler()` |
| `sq.scale.maxabs()` | none | largest absolute value | `MaxAbsScaler()` |
| `sq.scale.normalize()` | none | the row's norm | `Normalizer()` |

The settings follow scikit-learn's: `sq.scale.robust(quantile_range=(10, 90))`,
`sq.scale.minmax(feature_range=(-1, 1))`. Beyond them, `center=` and `spread=`
take any aggregate of `sq.agg`, so `sq.scale.robust(center=sq.agg.mean)` is a
robust scaler centred on the mean. A dict gives each column its own method:

```{code-cell} python
both = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [0.0, 5.0, 10.0]})
step = sq.scale({"a": "standard", "b": "minmax"})
sq.Pipeline([step]).learn(both).apply(both, out="pandas")
```

The mean is summed with compensation, so it is exact to about one unit in the
last place ([ADR 0033](../adr/0033-the-mean-is-summed-with-compensation.md)).

## A constant column

A column that does not vary has a spread of nothing, and dividing by it would
give NaN. sqlearn decides as scikit-learn does: a spread at the level of
rounding counts as exactly 1 (the standard deviation by its variance's
rounding bound, any other spread when it is below ten machine epsilons). A
constant column scales to 0:

```{code-cell} python
flat = pd.DataFrame({"x": [4.0, 4.0, 4.0]})
sq.Pipeline([sq.scale.standard()]).learn(flat).apply(flat, out="pandas")
```

## Normalising rows

`sq.scale.normalize` is the odd one out: it learns nothing and divides each
row's values by that row's own norm, `"l2"` by default (`"l1"` and `"max"` are
the others). It reads the whole row, so it needs every column it divides:

```{code-cell} python
rows = pd.DataFrame({"a": [3.0, 0.0], "b": [4.0, 0.0]})
sq.Pipeline([sq.scale.normalize()]).learn(rows).apply(rows, out="pandas")
```

A row of zeros stays zeros. `normalize` refuses a missing or infinite value
when the rows are fetched, naming the column: impute first.

```{code-cell} python
broken = pd.DataFrame({"a": [3.0, None], "b": [4.0, 1.0]})
try:
    sq.Pipeline([sq.scale.normalize()]).learn(broken).apply(broken, out="pandas")
except Exception as error:
    print(str(error).splitlines()[0])
```

## Other things to know

- The default columns are the numeric ones; a text column given by name is
  refused.
- `keep=True` keeps the input and adds the scaled column beside it, named
  `<column>_<scaler>` (`x_robust`); `suffix="z"` gives `x_z`
  ([ADR 0035](../adr/0035-names-of-generated-columns.md)).
- `sq.scale(method="normalize")` is refused: normalising is a step of its own,
  `sq.scale.normalize()`.

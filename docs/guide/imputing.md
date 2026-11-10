---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [impute, missing-values, indicator, simpleimputer, scikit-learn]
summary: "How sq.impute fills missing values: the mean, median, mode or a constant, a value per column, the missing-value indicator, and where it differs from scikit-learn's SimpleImputer."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md, docs/adr/0032-the-median-is-exact-by-sorting.md]
---

# Imputing: filling missing values

`sq.impute` fills the values a column is missing: NULL, and NaN in a float
column. Every shortcut is a preset of one general form,
`sq.impute(columns, value=...)`, where the value is an aggregate (learned from
the column), the name of one, a constant, or `None`.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame(
    {
        "age": [10.0, None, 30.0, 40.0],
        "city": ["Oslo", None, "Rome", "Rome"],
    }
)
pipe = sq.Pipeline([sq.impute.median("age"), sq.impute.mode("city")])
pipe.learn(data).apply(data, out="pandas")
```

The median is 30, the most frequent city is Rome. What was learned is read
from the step, `pipe["median"].value_` here.

## The shortcuts

| shortcut | fills with | default columns | scikit-learn |
|---|---|---|---|
| `sq.impute.mean()` | the mean | numbers | `SimpleImputer(strategy="mean")` |
| `sq.impute.median()` | the exact median | numbers | `SimpleImputer(strategy="median")` |
| `sq.impute.mode()` | the most frequent value, a tie going to the smallest | every column | `SimpleImputer(strategy="most_frequent")` |
| `sq.impute.constant(v)` | the constant `v` | columns of `v`'s kind | `SimpleImputer(strategy="constant", fill_value=v)` |
| `sq.impute.indicator()` | nothing: flags the missing values | every column | `MissingIndicator()` |

The shortcuts build exactly the step the general form builds with the same
value, so `sq.impute.median("age")` and `sq.impute("age", value="median")` are
the same step. The median is exact and is computed by sorting, so it runs on
data larger than memory, up to a reach: on one thread it learned about 4 times
a 64 MB limit and about 7 times a 128 MB one (counting one DOUBLE column at 8
bytes a row, NULLs included), measured on DuckDB 2.0
([ADR 0032](../adr/0032-the-median-is-exact-by-sorting.md),
[the measurement](../benchmarks/median-reach.md)).

The reach of the exact median, by memory limit, on one thread, for one DOUBLE
column:

| memory limit | largest passing rows | smallest failing rows | rows per MB (millions) |
|---|---|---|---|
| 32 MB | 8,125,000 | 8,750,000 | 0.25 |
| 64 MB | 32,500,000 | 35,000,000 | 0.51 |
| 128 MB | 110,000,000 | 120,000,000 | 0.86 |

Past its reach the learn fails with an `SqlearnError` that says DuckDB ran out
of memory and names the fixes: more memory with `sq.set_config(memory=...)`,
fewer threads (`SET threads = 1` on the connection given to
`sq.set_config(connection=...)`), or `sq.impute.median(approx=True)`. That is
DuckDB's `approx_quantile`: constant memory, close to the exact median but not
equal to it, so not equal to scikit-learn's. sqlearn never switches to it by
itself.

A column filled by an aggregate of numbers, or by a number, comes out as a
DOUBLE column, as scikit-learn returns floats. Filled by text or by the mode,
it keeps its type.

## A value for each column

Give a dict as the first argument to choose a value per column:

```{code-cell} python
step = sq.impute({"age": "mean", "city": "unknown"})
sq.Pipeline([step]).learn(data).apply(data, out="pandas")
```

A dict step is one static step, so it cannot carry an indicator. Put
`sq.impute.indicator(...)` before it as a step of its own.

## Flagging what was missing

`indicator=True` also creates `<column>_missing`, 1 where the value was
missing and 0 elsewhere. It is created only for a column that had a missing
value when the step learned, and the step is then dynamic: it must learn to
know which columns exist.

```{code-cell} python
pipe = sq.Pipeline([sq.impute.median("age", indicator=True)]).learn(data)
pipe.columns_out_, pipe.apply(data, out="pandas")
```

```{note}
Each `<column>_missing` comes **right after its own column**. scikit-learn's
`SimpleImputer(add_indicator=True)` puts all the indicators last. The names
are the same; the order differs.
```

`sq.impute.indicator()` alone flags without filling, as scikit-learn's
`MissingIndicator`: the input columns stay as they are.

## A fill value must suit the column

A column holds one type, so a fill value of another type is refused when the
pipeline learns, naming the column and the fix. A date constant does not fill a
timestamp column, and text does not fill numbers:

```{code-cell} python
try:
    sq.Pipeline([sq.impute.constant("unknown", "age")]).learn(data)
except sq.errors.SqlearnError as error:
    print(error)
```

By default each shortcut picks only the columns its value suits, so
`sq.impute.median()` with no columns fills the numeric ones and leaves the
text alone.

## Other things to know

- A column with no present value has nothing to fill with, and a numeric
  aggregate meeting infinity is refused
  ([ADR 0030](../adr/0030-infinity-is-refused.md)).
- `keep=True` keeps the input column and adds the filled one beside it;
  `suffix=` chooses the ending of its name
  ([ADR 0035](../adr/0035-names-of-generated-columns.md)).
- Not here: `KNNImputer` and `IterativeImputer`.

---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [explore, profile, histogram, top-values, missing-patterns, correlations, spearman, notes, eda]
summary: "Looking at a dataset before building a pipeline with sq.explore: a profile with one row per column and its notes (constant, all-missing, id-like, high-cardinality) and the step each note points to, then histograms, the commonest values, missing patterns and correlations, all computed in DuckDB and handed back as relations."
related: [docs/specs/library-exploration.md, docs/benchmarks/explore-larger-than-memory.md, docs/benchmarks/explore-correlations.md, docs/guide/imputing.md, docs/guide/selecting-features.md, docs/guide/encoding.md]
---

# Exploring data

Before a pipeline is built, someone looks at the data: what each column holds,
how much is missing, which columns move together, which are identifiers or
constants. `sq.explore` answers those questions inside DuckDB, over the same
inputs a pipeline reads (a path or glob to Parquet, CSV or JSON, a table, a
relation, a pandas frame), so it works on data larger than memory.

Each function runs now and returns a relation in long form: one row per column,
pair, bin or value. It is not a step: nothing is learned for later and nothing
joins a pipeline. Pass `out="pandas"` (or `"polars"`, `"numpy"`, `"arrow"`) for
another form, as `apply` takes it. The statistics follow pandas, the tool most
users compare against, and the tests check them against it.

This page builds its own data: customers with an identifier, an age and an
income that go missing, a spend that follows the income, and four text columns
that show what the notes flag.

```{code-cell} python
import numpy as np
import pandas as pd

import sqlearn as sq

pd.set_option("display.width", 100)
pd.set_option("display.max_columns", 20)

rng = np.random.default_rng(0)
n = 1000
income = rng.lognormal(10, 0.5, n)
age = rng.integers(18, 80, n).astype(float)
age[rng.random(n) < 0.1] = np.nan
income[rng.random(n) < 0.05] = np.nan
spend = income * 0.3 + rng.normal(0, 2000, n)
income[np.isnan(age) & (rng.random(n) < 0.5)] = np.nan

frame = pd.DataFrame(
    {
        "customer_id": np.arange(n),
        "age": age,
        "income": income,
        "spend": spend,
        "country": rng.choice(["NO", "SE", "DK", "FI"], n, p=[0.5, 0.3, 0.15, 0.05]),
        "postcode": [f"P{i % 700:04d}" for i in range(n)],
        "plan": "basic",
        "referrer": [None] * n,
    }
)
frame.head(3)
```

## Profile: one row per column

`sq.explore.profile` is where to start. It returns one row per column, in the
data's column order, with the type, the rows, how many are missing and distinct,
and for each kind of column the statistics that apply to it.

```{code-cell} python
profile = sq.explore.profile(frame, out="pandas")
profile[["column", "type", "missing", "missing_share", "distinct", "notes"]]
```

A statistic that does not apply to a column's type is NULL: `mean` of a text
column, `min_length` of a number. A boolean column gets only `mean`, the share
true. The numbers' statistics are as pandas' `describe`, `skew` and `kurt`:

```{code-cell} python
numbers = ["column", "mean", "std", "min", "q25", "median", "q75", "max"]
profile[numbers].dropna(subset=["mean"]).round(2)
```

```{code-cell} python
profile[["column", "zeros", "negative", "infinite", "skewness", "kurtosis"]].dropna(
    subset=["skewness"]
).round(2)
```

`zeros`, `negative` and `infinite` count finite values (NaN is missing, and an
infinity is counted in `infinite`, not in the other two). `min_length` and
`max_length` hold the lengths of text, and `first` and `last` the earliest and
latest of a date or timestamp, as text.

Choose columns with `cols=`, as a step does: a name, a list, or a selector.

```{code-cell} python
sq.explore.profile(frame, cols=sq.cols.numeric(), out="pandas")["column"].tolist()
```

### The notes

`notes` is a list of flags, each with a rule a reader can check, and each one
points to a step.

| note | when | what to do |
|---|---|---|
| `all-missing` | every row is missing | drop the column: nothing can be learned from it |
| `constant` | one distinct non-missing value | drop it, or let `sq.select.variance` ([selecting features](selecting-features.md)) do it |
| `id-like` | an integer or text column whose non-missing values are all distinct, with at least 20 of them | drop it: a model learns the rows, not the pattern. Never set on a float column |
| `high-cardinality` | a text column with more than 50 distinct values, more than half of its non-missing values, and not `id-like` | one-hot encoding would add a column per value: use `sq.encode.target` ([encoding](encoding.md)) |

Missing values in a column that is not all-missing are the job of `sq.impute`
([imputing](imputing.md)).

```{code-cell} python
profile[profile.notes.str.len() > 0][["column", "notes"]]
```

Here `customer_id` is a key, `postcode` has 700 distinct values over 1,000 rows
(most occur once or twice), `plan` never varies and `referrer` has no value at
all. The two thresholds are settings, `id_rows=20` and `high_cardinality=50`:
with 800, `postcode` is no longer flagged.

```{code-cell} python
list(sq.explore.profile(frame, "postcode", high_cardinality=800, out="pandas")["notes"][0])
```

### Exact, or estimated

By default the distinct counts and quartiles are exact, which keeps every value
of a column in memory while it counts. `exact=False` estimates them (HyperLogLog
and t-digest) in less memory and one read of the data, and says so in the
result's `exact` column. sqlearn never switches on its own: when an exact
profile runs out of memory, the error's `Fix:` names `exact=False` first. With
the estimate a distinct count is approximate, so `id-like` may not fire. The
profile reads a wide file in blocks of 20 columns, so a statement never holds
every column;
[how far it reaches on 20 GB of data](../benchmarks/explore-larger-than-memory.md)
is measured.

```{code-cell} python
sq.explore.profile(frame, out="pandas", exact=False)[["column", "distinct", "exact"]].head(4)
```

## Histogram

`sq.explore.histogram` counts each numeric column in equal-width bins between
its minimum and maximum, as `numpy.histogram(values, bins)` does: one row per
column and bin, the last bin including its upper edge. Missing and infinite
values are left out; their counts are in the profile.

```{code-cell} python
sq.explore.histogram(frame, "income", bins=5, out="pandas")
```

Income is skewed, as the profile's skewness said: more than half of the values
sit in the first bin. Pass nothing for `cols` to bin every numeric column (a
boolean is not numeric), and plot the rows with the library you like: sqlearn
brings none.

## The commonest values

`sq.explore.top` lists the `k` commonest values of each column, of any type,
with their count and their share of all the rows.

```{code-cell} python
sq.explore.top(frame, ["country", "age"], k=3, out="pandas")
```

Missing values count together as one value, shown with a missing `value`, as
pandas' `value_counts(dropna=False)` counts NaN: age is missing more often than
any age is present. `value` is the value as text, and values with the same count
come in order of `value`.

## Missing patterns

The profile says how much of each column is missing; `sq.explore.missing` says
which columns are missing together. A pattern is the set of chosen columns that
are missing in a row, and the function lists the commonest ones, the pattern
with nothing missing included when it is among them.

```{code-cell} python
sq.explore.missing(frame, ["age", "income"], out="pandas")
```

Age is missing in 118 rows and income in 103, and the two are missing together
in 59, where gaps that were independent would give about 12: one reason may
explain both, which a fill column by column would not show. At most 64 columns
may be chosen, as the pattern grows with the width; the error says to pass fewer
`cols`.

## Correlations

`sq.explore.correlations` correlates every pair of numeric columns, each
unordered pair once. Each pair uses the rows where both values are present, as
pandas' `DataFrame.corr` does, so one sparse column does not empty the rest, and
`rows` says how many that was.

```{code-cell} python
sq.explore.correlations(frame, out="pandas")
```

The default is Pearson. `method="spearman"` correlates average ranks (ties share
the mean of their ranks), which finds a relation that is steady but not a
straight line, and is not moved by a few extreme incomes:

```{code-cell} python
sq.explore.correlations(frame, method="spearman", out="pandas")
```

A column with no variance, or a pair with fewer than two shared rows, gives a
missing correlation (pandas gives NaN). The columns are cut into blocks of 20
and each statement pairs two blocks, so a hundred columns neither make one
statement too large nor read every column at once; the block was
[measured](../benchmarks/explore-correlations.md). Spearman numbers the data
once into a temporary copy and ranks each column in it, which takes more time
and memory than Pearson; `cols=` narrows it.

## When the data is larger than memory

Every function takes a path, so the data need not be loaded first:
`sq.explore.profile("data/sales/*.parquet")`. When DuckDB runs out of memory,
each function refuses the call with a `Why:` and a `Fix:`: fewer columns with
`cols=`, more memory with `sq.set_config(memory=...)`, fewer threads, or a file
with smaller row groups, and for an exact `profile` first `exact=False`. In the
runs measured, the process was not killed.
[The benchmark](../benchmarks/explore-larger-than-memory.md) records a profile
and correlations of 12.5 million rows of 200 columns, 20 GB, on a machine with
16 GiB.

## What is not here yet

Association with a target, outliers, normality screens, Kendall's tau, sampling
for speed and time-series views come later, each as its own piece, and then the
application that renders these relations
([the spec](../specs/library-exploration.md), section 8).

---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [encode, onehot, ordinal, target-encoding, cross-fitting, categories, scikit-learn]
summary: "How sq.encode turns categories into numbers: one-hot, ordinal and target encoding, the NULL category, unseen values, and how the target encoder cross-fits in train."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md]
---

# Encoding: categories as numbers

`sq.encode` has three encoders, presets of one general form,
`sq.encode(columns, method=...)`. By default each takes the text columns.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame(
    {
        "city": ["Rome", "Oslo", "Rome", None],
        "size": ["m", "s", "l", "m"],
        "y": [1, 0, 1, 1],
    }
)
```

| shortcut | result | scikit-learn |
|---|---|---|
| `sq.encode.onehot()` | one 0/1 column per category | `OneHotEncoder(handle_unknown="ignore")` |
| `sq.encode.ordinal()` | the category's position, from 0 | `OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)` |
| `sq.encode.target()` | the target's mean in the category | `TargetEncoder()` |

## One-hot

```{code-cell} python
hot = sq.Pipeline([sq.encode.onehot("city")]).learn(data)
hot.columns_out_, hot.apply(data, out="pandas")
```

The columns exist only because of what was learned, so the step is dynamic.
`city_NULL` exists because a NULL was seen when learning; had there been none,
there would be no such column. A value not seen when learning gives 0 in every
column. The new columns take the place of `city`, named
`<column>_<value>` ([column names](column-names.md) says what happens when two
values clash, such as `Oslo` and `oslo`).

## Ordinal

```{code-cell} python
code = sq.Pipeline([sq.encode.ordinal("size")]).learn(data)
code.apply(data, out="pandas")["size"].tolist()
```

The categories are sorted, `l` is 0, `m` is 1, `s` is 2. A value not seen when
learning becomes -1. NULL stays NULL, as it does in scikit-learn, and is not a
category.

## Target encoding

The target encoder replaces each category by the mean of the target in it,
shrunk towards the overall mean, as scikit-learn's `TargetEncoder`. It learns
from the target, so give one:

```{code-cell} python
pipe = sq.Pipeline([sq.encode.target("city", smooth=0.0)])
pipe.learn(data, target="y")
pipe["target"].categories_, pipe["target"].encodings_
```

A category not seen when learning gets the overall mean. The target must be
numbers (or booleans): a **text target is refused**, so map it to numbers
first. A binary target is label-encoded, its smaller value 0 and its larger 1;
a target with three or more whole values (multiclass) is refused for now.

Encoding a row by a mean that includes that row lets the target leak into the
feature. So in `train`, which fits a model, the rows the model trains on are
**cross-fitted**: each row is encoded with statistics from the other inner
folds (`cv=5` of them). The inner folds are dealt by each row's **position in
the data's row order**, so the same rows in another order give other inner
folds. Learn-then-apply, which has no model to overfit, does **not**
cross-fit: it applies the learned encodings to every row.

## Many categories: `lookup=`

The ordinal and target encoders find each value among the learned categories.
By default (`lookup="list"`) they use `list_position`, which compares the
value with the categories one by one, so the cost per row grows with the
number of categories. `lookup="hash"` uses an MD5 perfect hash instead: one
MD5 per value and a few list reads, whatever the count.

```{code-cell} python
sq.encode.ordinal("size", lookup="hash")
```

Both give the same codes. The hash costs less per row once there are many
categories, but its SQL holds about 3.5 constants per category, which DuckDB
parses and plans on every query; so which is faster depends on the number of
categories and of rows. Applied to 1,000,000 rows read from Parquet
([the benchmark](../benchmarks/category-lookup.md), seconds):

| categories | ordinal, list | ordinal, hash | target, list | target, hash |
|---|---|---|---|---|
| 10,000 | 0.937 | 2.539 | 1.099 | 1.888 |
| 15,000 | 0.620 | 1.464 | 1.524 | 2.340 |
| 20,000 | 2.370 | 1.923 | 3.497 | 2.897 |
| 30,000 | 3.393 | 2.502 | 4.922 | 3.867 |
| 50,000 | 5.456 | 3.535 | 8.245 | 5.764 |
| 100,000 | 15.403 | 6.779 | 24.722 | 10.478 |

For both encoders the hash applies faster from 20,000 categories, and the
gap widens with more; below that the list is faster. Learning with the hash
costs a little more at nearly every count.

- Leave `lookup` out and the encoder uses `"list"`. When an encoder learns
  more than 20,000 categories in a column it warns once, naming the step, the
  count and `lookup="hash"`; passing either value is a choice and silences it
  ([ADR 0046](../adr/0046-sqlearn-warns-the-user-chooses.md)).
- The hash reads text: it takes VARCHAR and ENUM columns, and refuses any
  other.
- The hash compares the bytes exactly. A column declared with a collation
  (`VARCHAR COLLATE NOCASE`) is matched by its collation with `"list"` but by
  its bytes with `"hash"`: DuckDB does not tell a step a column's collation,
  so the encoder cannot refuse it. Use `"list"` on a collated column, or
  `sq.transform.lower` before the encoder.

## Other things to know

- NaN in a float column is a category for the one-hot encoder, as in
  scikit-learn, and is missing, like NULL, for the ordinal encoder.
- The encoders take no `suffix=`: the new columns are named after the
  categories ([ADR 0035](../adr/0035-names-of-generated-columns.md)).
- Case is not unified by an encoder. Put `sq.transform.lower("city")` before
  it to treat `Oslo` and `oslo` as one.

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

## Other things to know

- NaN in a float column is a category for the one-hot encoder, as in
  scikit-learn, and is missing, like NULL, for the ordinal encoder.
- The encoders take no `suffix=`: the new columns are named after the
  categories ([ADR 0035](../adr/0035-names-of-generated-columns.md)).
- Case is not unified by an encoder. Put `sq.transform.lower("city")` before
  it to treat `Oslo` and `oslo` as one.

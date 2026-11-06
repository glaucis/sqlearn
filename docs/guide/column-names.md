---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [columns, naming, columns_out_, onehot, clashes, case]
summary: "How steps name the columns they create: the clash numbering that never refuses, NULL as a category, keeping the input, and reading the final names from columns_out_."
related: [docs/adr/0035-names-of-generated-columns.md, docs/adr/0020-column-selectors.md, docs/specs/library-preprocessing.md]
---

# Names of created columns

Some steps create columns whose names come from the data: a one-hot encoder
makes one per city. This page says how they are named
([ADR 0035](../adr/0035-names-of-generated-columns.md)).

A created column is named `<column>_<label>`. The trouble is that DuckDB keeps
the values `Oslo` and `oslo` apart but treats column names without regard to
case, so `city_Oslo` and `city_oslo` would be one name.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame({"city": ["Oslo", "oslo", None, "Rome"], "age": [41, 33, 28, 50]})
pipe = sq.Pipeline([sq.encode.onehot("city")]).learn(data)
pipe.columns_out_
```

Nothing is refused. Names that clash, compared without regard to case, are
numbered in the sorted order of their labels: the first keeps its name, the
next get `_2`, `_3`. An input column is never renamed. `columns_out_` shows the
final names, so look there for a name that came out numbered.

## NULL is a category

The missing category is `<column>_NULL`, created only if a NULL was seen when
learning. scikit-learn says `_nan`; in SQL a missing value is NULL. The text
`'NULL'` beside a real NULL is a clash, numbered by the same rule.

## Case is your choice

An encoder does not unify case. To treat `Oslo` and `oslo` as one city, say so
with a step of its own:

```{code-cell} python
same = sq.Pipeline([sq.transform.lower("city"), sq.encode.onehot("city")])
same.learn(data).columns_out_
```

## Keeping the input

`keep=True` names the new column `<column>_<step name>`, and `suffix=` chooses
another ending. `suffix=` exists only on steps that give one column per input
(scaling, imputing, transforming, binning); encoders and feature makers do not
take it.

```{code-cell} python
ages = pd.DataFrame({"age": [10.0, 20.0, 60.0]})
both = sq.Pipeline([sq.scale.robust("age", keep=True)]).learn(ages)
both.columns_out_
```

## Feature makers

Polynomials and splines use scikit-learn's labels, which DuckDB quotes as
needed: `a^2`, `a*b`, `b^2`, and `x_sp_0`, `x_sp_1`.

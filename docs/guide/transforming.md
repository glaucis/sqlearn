---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [transform, log, log1p, sqrt, clip, lower, upper, numpy]
summary: "How sq.transform changes values with one function (log, log1p, sqrt, clip, lower, upper), and how bad input such as the log of 0 is refused when the value is met."
related: [docs/specs/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md]
---

# Transforming: one function per value

`sq.transform` applies one function to each value of the chosen columns. It
learns nothing, so it chains into the steps around it. NULL stays NULL.

```{code-cell} python
import pandas as pd
import sqlearn as sq

data = pd.DataFrame({"x": [1.0, 4.0, 9.0], "city": ["Oslo", "ROME", None]})
pipe = sq.Pipeline([sq.transform.sqrt("x"), sq.transform.lower("city")])
pipe.learn(data).apply(data, out="pandas")
```

| shortcut | result | numpy |
|---|---|---|
| `sq.transform.log()` | natural logarithm | `np.log` |
| `sq.transform.log1p()` | `log(1 + x)`, accurate for small `x` | `np.log1p` |
| `sq.transform.sqrt()` | square root | `np.sqrt` |
| `sq.transform.clip(lower=0, upper=10)` | `x` held between the bounds | `np.clip` |
| `sq.transform.lower()` | text in lower case | `str.lower` |
| `sq.transform.upper()` | text in upper case | `str.upper` |

The general form is `sq.transform(columns, method="log")`. `log1p(x)` is not
`log(1 + x)` written out: for a tiny `x` the sum `1 + x` rounds away the very
digits that matter, and `log1p` keeps them. `clip` keeps the column's type
where numpy would: integer bounds on an integer column give integers, a float
bound gives DOUBLE.

## Bad input is refused when it is met

numpy gives `-inf` or `nan` for the log of 0 or the square root of -1, with a
warning. sqlearn refuses: the error is raised when the rows are fetched, by the
value that is wrong, naming the step, the column and the fix.

```{code-cell} python
bad = pd.DataFrame({"x": [1.0, 0.0, 5.0]})
try:
    sq.Pipeline([sq.transform.log()]).learn(bad).apply(bad, out="pandas")
except Exception as error:
    print(str(error).splitlines()[0])
```

`log` refuses a value at or below 0, `log1p` one at or below -1, and `sqrt` a
negative one. Either `clip` first, or choose `log1p`. NaN passes as numpy
gives it, and so does infinity above the domain.

## Other things to know

- The default columns are the numeric ones; for `lower` and `upper` the text
  ones.
- `keep=True` keeps the input and adds the result beside it, named
  `<column>_<step>` (`x_sqrt`); `suffix=` chooses another ending
  ([ADR 0035](../adr/0035-names-of-generated-columns.md)).
- `lower` is how to treat `Oslo` and `oslo` as one category before encoding
  ([column names](column-names.md)).

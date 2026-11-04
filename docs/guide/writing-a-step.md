---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [steps, custom-steps, learn, apply, static, dynamic, errors]
summary: "How to write your own sqlearn step: the learn/apply contract, what a step declares, placeholders, static or dynamic, and the messages a failing step gets."
related: [docs/specs/library-core.md, docs/adr/0012-static-and-dynamic-steps.md, docs/adr/0019-custom-steps-and-failure-feedback.md]
---

# Writing a step

A step prepares data. You write one by subclassing `sq.Step` and giving it two
parts: what it **learns** from the data, and how it **applies** what it
learned. Both are built from DuckDB expressions, never SQL text, and sqlearn
turns them into queries.

## The two-part contract

```{code-cell} python
import pandas as pd
import sqlearn as sq


class MyScale(sq.Step):
    def __init__(self, cols=sq.numeric(), keep=False, suffix=None):
        super().__init__(cols, keep, suffix)

    def learn(self, x):
        return {"mean": sq.avg(x), "scale": sq.stddev_pop(x)}

    def apply(self, x, learned):
        return (x - learned.mean) / learned.scale
```

- `learn(x)` is called once per selected column; `x` is that column as an
  expression. It returns a mapping of name to aggregate, built with `sq.avg`,
  `sq.stddev_pop`, `sq.median`, `sq.count`, `sq.distinct_values` or `sq.const`.
  A step that learns nothing does not define it.
- `apply(x, learned)` is called once per selected column. It returns one
  expression, the column's new value, or a dict of name to expression, which
  makes new columns.
- `sq.median` is an exact median computed by sorting, so it can run on data
  larger than memory. Use it on its own as a learned value
  (`{"middle": sq.median(x)}`), not inside a larger expression.
- `sq.avg` is DuckDB's compensated mean, exact to about one unit in the last
  place. It gives NaN, not infinity, when the data holds an infinity or the sum
  overflows.

Run it on a small table:

```{code-cell} python
data = pd.DataFrame({"age": [1.0, 2.0, 6.0], "city": ["a", "b", "a"]})
pipe = sq.Pipeline([("scale", MyScale())])
pipe.learn(data)
pipe["scale"].mean_, pipe["scale"].scale_
```

After learning, each learned value is readable as the step's attribute named
after it with `_` added: `pipe["scale"].mean_` is a dict of column to value.
Applying gives a lazy DuckDB relation:

```{code-cell} python
pipe.apply(data)
```

## What a step declares

A step declares, as data, what the planner needs, so it does not have to run
your code to find out:

- **its settings:** the `__init__` arguments, stored under their own names, as
  in scikit-learn. A step takes `cols`, `keep` and `suffix`; the base class
  stores them when you pass them to `super().__init__`.
- **its inputs:** the columns it reads, from `cols=` (a list of names or a
  selector such as `sq.numeric()`; `None` means every column).
- **its outputs:** a replacing step writes its inputs. With `keep=True` it
  writes `<column>_<step>` as well (`suffix=` chooses another ending). A name
  that already exists stops the run with a message naming it.
- **static or dynamic:** see below.

## Static or dynamic

A step is **static** when the columns it writes are known without the learned
values: `MyScale` writes `age` whatever the mean is. It is **dynamic** when
the learned values decide which columns exist: a one-hot encoder writes one
column per distinct value, so it must learn before the steps after it can know
what to read.

```{code-cell} python
from duckdb.sqltypes import INTEGER


class MyEncoder(sq.Step):
    def __init__(self, cols=("city",), keep=False, suffix=None):
        super().__init__(cols, keep, suffix)

    def learn(self, x):
        return {"cities": sq.distinct_values(x)}

    def apply(self, x, learned):
        return {f"city_{c}": (x == sq.const(c)).cast(INTEGER) for c in learned.cities}


encoder = sq.Pipeline([("encode", MyEncoder())])
encoder.learn(data)
encoder.apply(data)
```

You may declare it with a class attribute, `static = True` or `dynamic = True`,
and sqlearn trusts you. Or leave both out, and sqlearn finds out before the
first run.

## Placeholders

When a query both learns and applies, the learned values do not exist yet. So
sqlearn calls your `apply` with **placeholders** in `learned`: each one is a
reference to the learn stage of the same query. `learned.mean` is then an
expression, and `(x - learned.mean) / learned.scale` builds. When the values
are known, because an earlier run learned them or because you apply to new
data, `learned` holds them as constants and the same code runs.

That is how sqlearn classifies a step you did not declare: it calls `apply`
with placeholders. If an expression comes back, the step is static. If the step
needs a real value to write its SQL, such as looping over `learned.cities`,
the placeholder raises and the step is dynamic. Any other unexpected failure
also counts as dynamic. The answer is kept in memory for the session, once per
step class and settings; it is never written onto your step.

Learned values come only through `learned`. A step whose `apply` reaches for a
value from somewhere else, such as a module-level variable, builds and runs
with that stale value, and nothing can catch it.

## When something fails

Diagnosis runs only after a failure; a run that works pays nothing for it.
When a step you wrote fails, the message names the step and its position
(counted from 1), what went wrong, why, and the fix. If `MyEncoder` is declared
static, but loops over the learned cities:

```{code-cell} python
class WrongEncoder(MyEncoder):
    static = True


try:
    sq.Pipeline([("encode", WrongEncoder())]).learn(data)
except sq.StepError as error:
    print(error)
```

The rest of the cases follow the same form: an exception inside `learn` or
`apply`, a name that already exists, a selector that matches nothing. When
a built-in step fails, the failure is sqlearn's bug and is reported as an
`sq.InternalError`, with what is needed to reproduce it.

One limit. `apply` returns a lazy DuckDB relation, and sqlearn checks all the
SQL up front, so a mistake in your expressions is reported with your step's
name. An error DuckDB raises only when that relation is later fetched, because
of the data (a cast that fails on one value, say), cannot name the step: it
comes with DuckDB's own message.

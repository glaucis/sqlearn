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
    def __init__(self, cols=sq.cols.numeric(), keep=False, suffix=None):
        super().__init__(cols, keep, suffix)

    def learn(self, x):
        return {"mean": sq.agg.mean(x), "scale": sq.agg.std(x)}

    def apply(self, x, learned):
        return (x - learned.mean) / learned.scale
```

- `learn(x)` is called once per selected column; `x` is that column as an
  expression. It returns a mapping of name to aggregate, built with the
  aggregates of `sq.agg` (`sq.agg.mean`, `sq.agg.std`, `sq.agg.median`,
  `sq.agg.quantile`, `sq.agg.mode`, `sq.agg.count`, `sq.agg.distinct` and the
  rest), which leave missing values (NULL and NaN) out, or
  `sq.fn.const`. A step that learns nothing does not define it.
- `apply(x, learned)` is called once per selected column. It returns one
  expression, the column's new value, or a dict of name to expression, which
  makes new columns.
- `sq.agg.median`, `sq.agg.quantile(x, q=0.9)` and `sq.agg.iqr` are exact,
  computed by sorting, so they can run on data larger than memory; every
  quantile a step learns shares one sort. They may sit inside a larger
  expression (`{"spread": sq.agg.iqr(x) / sq.agg.median(x)}`). `sq.agg.mode`
  is the most frequent value, a tie going to the smallest.
- `sq.agg.mean` is DuckDB's compensated mean, exact to about one unit in the
  last place. It gives NaN, not infinity, when the data holds an infinity or
  the sum overflows.

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
  selector such as `sq.cols.numeric()`; `None` means every column).
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
        return {"cities": sq.agg.distinct(x)}

    def apply(self, x, learned):
        return {f"city_{c}": (x == sq.fn.const(c)).cast(INTEGER) for c in learned.cities}


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

## A step without a subclass

For a step that needs no settings of its own, pass `learn` and `apply` as
callables to `sq.Step`. They follow the same contract as the methods; an
`apply` that uses nothing learned may take only the column:

```{code-cell} python
log = sq.Step(apply=lambda x: sq.fn.ln(x + 1), cols=["age"])

top = sq.Step(
    learn=lambda x: {"top": sq.agg.max(x)},
    apply=lambda x, learned: x / learned.top,
    cols=["age"],
)
sq.Pipeline([top]).learn(data).apply(data)
```

Its name in a pipeline is `step`. Its store key uses the callables themselves,
so defining a lambda again relearns. A step built from a lambda cannot be
pickled, since lambdas cannot; use a module-level function for that. A subclass
is still the form for a step with settings of its own.

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
except sq.errors.StepError as error:
    print(error)
```

The rest of the cases follow the same form: an exception inside `learn` or
`apply`, a name that already exists, a selector that matches nothing. When
a built-in step fails, the failure is sqlearn's bug and is reported as an
`sq.errors.InternalError`, with what is needed to reproduce it.

One limit. `apply` returns a lazy DuckDB relation, and sqlearn checks all the
SQL up front, so a mistake in your expressions is reported with your step's
name. An error DuckDB raises only when that relation is later fetched, because
of the data (a cast that fails on one value, say), cannot name the step: it
comes with DuckDB's own message.

---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [steps, custom-steps, learn, apply, apply_row, rowwise, uses_target, cross-fitting, static, dynamic, errors]
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
  expression, the column's new value, or a dict of **label** to expression,
  which makes new columns: the label `"low"` on the column `x` makes `x_low`,
  and the label `""` is the column `x` itself, replaced. sqlearn names the
  columns; your step never builds a full name (see
  [Names of new columns](#names-of-new-columns)).
- `sq.agg.median`, `sq.agg.quantile(x, q=0.9)` and `sq.agg.iqr` are exact,
  computed by sorting, so they can run on data several times larger than
  memory (about 4 times a 64 MB limit, counting one DOUBLE column at 8 bytes a
  row, NULLs included; see
  [the measurement](../benchmarks/median-reach.md)); every
  quantile a step learns shares one sort. They may sit inside a larger
  expression (`{"spread": sq.agg.iqr(x) / sq.agg.median(x)}`). `sq.agg.mode` is
  the most frequent value, a tie going to the smallest. `sq.agg.std` is the
  population standard deviation in two compensated passes, the mean first
  ([ADR 0044](../adr/0044-the-standard-deviation-in-two-staged-passes.md)).
  Any aggregate may sit inside any other, at any depth, such as the median
  absolute deviation, `sq.agg.median(sq.fn.abs(x - sq.agg.median(x)))`, or
  `sq.agg.std(x - sq.agg.mean(x))`. The inner one is learned first, in a level
  of its own, and fed to the outer one; each level costs one more pass over
  the data (a sort for a median), all in the same query
  ([ADR 0051](../adr/0051-aggregates-learn-in-levels.md)). A missing inner
  value reaches the outer aggregate as NULL: `sq.agg`'s aggregates then give
  NULL, DuckDB's own as their SQL does (`count` gives 0).
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
after it with `_` added: `pipe["scale"].mean_` is a dict of column to value. To
say something about what was learned, such as a warning, override
`learned(values)`: it is called once per `learn` or `train`, with the values by
column, whether they were computed or found in the store. Applying gives a lazy
DuckDB relation:

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
  that already exists is numbered, never refused (see below).
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
        return {c: (x == sq.fn.const(c)).cast(INTEGER) for c in learned.cities}


encoder = sq.Pipeline([("encode", MyEncoder())])
encoder.learn(data)
encoder.apply(data)
```

The keys `"a"` and `"b"` are labels: the new columns are `city_a` and
`city_b`.

You may declare it with a class attribute, `static = True` or `dynamic = True`,
and sqlearn trusts you. Or leave both out, and sqlearn finds out before the
first run.

A dynamic step replaces its inputs, as the encoder above replaces `city`: the
steps after it no longer see them. One whose `apply` writes each input again
under its own name (the label `""`), of the same kind (numbers stay numbers,
text stays text), declares `keeps_inputs = True`. `sq.impute.indicator` is
one: it passes `city` through and adds `city_missing`. The steps after it
then see `city` too, once the indicator has learned, so a later
`sq.encode.onehot()` still encodes it. A step with `keep` that also writes a
copy of each input of the input's own type, beside new columns of the type
`creates` names, declares `copies_inputs = True`, as `sq.impute` with a
fill value, `keep` and the indicator does for its filled copies.

(names-of-new-columns)=

## Names of new columns

Every step's new columns are named by one rule (ADR 0035): `<column>_<label>`.
DuckDB compares column names without regard to case, so `city_Oslo` and
`city_oslo` are the same name to it. Names that clash are numbered in sorted
order of their labels: the first keeps its name, the next get `_2`, `_3`.
Nothing is refused, and a column passing through is never renamed.

```{code-cell} python
cities = pd.DataFrame({"city": ["Oslo", "oslo", "Oslo"]})
sq.Pipeline([MyEncoder()]).learn(cities).columns_out_
```

`columns_out_` shows the final names, and a later step selects the numbered
column by that name. When two outputs share a label (the text `'NULL'` and a
real NULL, say), return a list of `(label, expression)` pairs instead of a
dict; they are numbered in the order given.

## Steps that read the whole row

Some outputs need several columns of the same row: dividing each value by the
row's norm, or multiplying columns together. Such a step sets
`rowwise = True` and defines `apply_row(xs, learned, values)` instead of
`apply`.
`xs` holds every selected column at once, by name, and `learned` holds each
column's learned values by the same name; `learn` stays per column. It
returns a dict of output columns, which replace the selected ones.

```{code-cell} python
class Share(sq.Step):
    rowwise = True
    static = True

    def __init__(self, cols=sq.cols.numeric(), keep=False, suffix=None):
        super().__init__(cols, keep, suffix)

    def apply_row(self, xs, learned, values):
        total = sum(xs.values(), sq.fn.const(0.0))
        return {name: x / total for name, x in xs.items()}


parts = pd.DataFrame({"a": [1.0, 3.0], "b": [3.0, 1.0]})
sq.Pipeline([Share()]).learn(parts).apply(parts)
```

The first output named after a selected column takes its place (with
`keep=True`, `a_share` comes beside `a`); any other name follows the last
selected column. Names are given by the same rule as above. When two outputs
share a name, return a list of `(name, expression)` pairs instead of a dict:
both are kept, and the second is numbered. `sq.features.polynomial` does so,
since the square of `a` is spelt `a^2`, as an input column may be. Since each
output reads the whole row, a later step reading any one of them depends on
every selected column, and on the steps that made them.

A value every output shares, such as the row's total above, is written into
each output, so the SQL grows with the square of the number of columns. To
compute it once per row instead, return it from `row_values(xs, learned)`:
sqlearn computes it in a projection before the outputs, and `values` holds a
reference to it by name (`values` is empty for a step without row values).

```{code-cell} python
class OnceShare(Share):
    def row_values(self, xs, learned):
        return {"total": sum(xs.values(), sq.fn.const(0.0))}

    def apply_row(self, xs, learned, values):
        return {name: x / values["total"] for name, x in xs.items()}


sq.Pipeline([OnceShare()]).learn(parts).apply(parts)
```

`sq.scale.normalize` is built this way, computing each row's norm once.

## Steps that learn from the target

A step can learn from the target, as `sq.encode.target` learns the target's
mean in each category. It sets `uses_target = True`, and its `learn` gets the
target as a second argument, `learn(x, y)` (write `y=None`, so the signature
extends the base class's). No other step sees the target, and no selector
matches it. Such a step also has the settings `cv` and `seed`, its inner
folds, and its `apply` returns one expression per column, a DOUBLE.

```{code-cell} python
class OverTarget(sq.Step):
    uses_target = True
    static = True

    def __init__(self, cols=sq.cols.numeric(), keep=False, cv=5, seed=0):
        super().__init__(cols, keep)
        self.cv = cv
        self.seed = seed

    def learn(self, x, y=None):
        return {"mean": sq.agg.mean(y)}

    def apply(self, x, learned):
        return x / learned.mean


answers = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 6.0]})
sq.Pipeline([OverTarget()]).learn(answers, target="y").apply(answers)
```

The pipeline learns it only when given the target: `train` gives it, and
`learn` needs `target=` (without it, such a step is refused). `apply` then
needs no target.

In `train`, the rows the model trains on are **cross-fitted**, as
scikit-learn's `fit_transform` does: each row is dealt into an inner fold
(`sq.folds.kfold(cv, seed)` over the row's position in the data as read, so rows
alike get folds of their own) and encoded
with what was learned on the rows outside its fold, so a row's own answer
does not leak into its features. Later steps learn from those values, so such
a step ends its run, like a dynamic one. `predict`, and `apply` after
`learn`, use what was learned on all rows.

To cross-fit, a step learns its statistics grouped by inner fold, then turns
them into its values for all rows (`"all"`) and for each fold's complement
(`"0"`, `"1"`, ...) in `derive(values, k)`. The default `derive` gives every
fold the values learned on all rows: `OverTarget` above is not cross-fitted.
`sq.encode.target` learns, with `sqlearn._expr.target_stats`, the count, sum
and sum of squares of the target per fold and category, in one `GROUP BY`,
and derives every fold's encodings from them in Python.

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

A search with `keep_prepared` keeps prepared folds in a DuckDB file across
sessions, under a key made of each step's class name and settings
([inputs and the store](inputs-and-the-store.md)). It does not see a change
to your step's code: after editing `learn` or `apply`, run
`sq.store.clear(prepared=path)`. It keys settings by their content, and
refuses one it cannot: a lambda, a function defined inside another, a
`functools.partial`, or an object of a type it does not know, since nothing
names those the same way in the next session. A module-level function is known
by its dotted name, a numpy array by its bytes.

## Changing what a step learns: `state_version`

A pipeline saved with `sq.save` holds what each step's `learn` returned.
`Step.state_version` is a class attribute, 1 by default. Raise it when the
names or the meaning of what your `learn` returns change: a file saved with
the old number then loads as a recipe, with a warning naming the step, and
the next `learn` learns again, instead of `apply` reading values that mean
something else. See [saving a pipeline](saving-a-pipeline.md).

```python
class MyScale(sq.Step):
    state_version = 2  # learn now returns "scale" as a variance, not a std
```

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
`apply`, a selector that matches nothing. When
a built-in step fails, the failure is sqlearn's bug and is reported as an
`sq.errors.InternalError`, with what is needed to reproduce it.

One limit. `apply` returns a lazy DuckDB relation, and sqlearn checks all the
SQL up front, so a mistake in your expressions is reported with your step's
name. An error DuckDB raises only when that relation is later fetched, because
of the data (a cast that fails on one value, say), cannot name the step: it
comes with DuckDB's own message.

The steps sqlearn ships are written the same way. See the guide pages for
[imputing](imputing.md), [scaling](scaling.md), [encoding](encoding.md),
[binning](binning.md), [transforming](transforming.md) and [making
features](making-features.md), and [column names](column-names.md) for how
created columns are named.

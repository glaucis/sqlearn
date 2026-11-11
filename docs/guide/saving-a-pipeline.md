---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [save, load, json, recipe, learned-state, fingerprint, allow, trust-model, pickle, state-version, checkpoint]
summary: "How sq.save and sq.load keep a pipeline across processes: the recipe and the learned values in one JSON file, which inputs carry their values to a new process, the warning when the data changed, CHECKPOINT before saving a table, sharing a recipe with learned=False, allow= for classes of other packages, the trained model by pickle only on request, and state_version for step authors."
related: [docs/specs/library-saving.md, docs/adr/0047-a-pipeline-saves-as-json.md, docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/guide/inputs-and-the-store.md, docs/guide/writing-a-step.md]
---

# Saving a pipeline

The learned values live in the learning store while the program runs, so a
restart learns everything again. `sq.save` writes a pipeline to one file, and
`sq.load` reads it back in a new process
([ADR 0047](../adr/0047-a-pipeline-saves-as-json.md)). The case it is made
for: the data is prepared and learned today, there is no time to train the
model, and tomorrow the pipeline just runs.

```{code-cell} python
import tempfile
from pathlib import Path

import sqlearn as sq

folder = Path(tempfile.mkdtemp())  # the examples save here
data = sq.datasets.customers(rows=200, seed=1)

pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard()])
pipe.learn(data, target="target")
sq.save(pipe, folder / "customers.sqlearn.json")
```

In a new process:

```{code-cell} python
pipe = sq.load(folder / "customers.sqlearn.json")
pipe["standard"].center_  # the learned values are back
```

`pipe.apply(...)` works at once, on any data with the columns and types it
learned from. Pass `target=` to `learn` as you did when learning the saved
values: a later `train` reuses the saved preparation only when `learn` was
given the target (`pipe.learn("customers.parquet", target="churned")`).
Learning without it reads the target as a feature, so `train` learns again.

## What is saved, and what is not

The file is JSON, never pickle: opening it does not run anything from it.
It can name classes to import, which `allow=` limits, and the trained model
has a pickle file of its own, opened only with `trust_model=True` (both
below).
The same pipeline always gives the same bytes, so a change is a readable
diff. It holds:

- **the recipe:** each step's class and settings, in order, selectors
  included, and the model by its class and parameters;
- **the learned values** of every step, once the pipeline has learned or
  trained: medians, means, categories, folds of a target encoder, as exact
  values (a float reads back as the same double). A learned
  `TIMESTAMP WITH TIME ZONE` value needs `pytz` when it is learned, which
  sqlearn does not depend on;
- **the fingerprint of the data** the values came from, so that sqlearn can
  tell later whether that data changed.

It does not hold the data. It does not hold the trained model unless you ask
(below). A search object is not saved; its best pipeline is a `Pipeline` and
saves as one. A setting that has no exact form is refused when saving, never
written approximately: a lambda, a numpy array, a function passed to a
model. The error names the step and the setting and says what would save. A
step of your own saves by its import path, so it must live in an importable
module, not in `__main__` or inside a function.

## Which inputs carry their values to a new process

Learned values are found again in a new process only for data whose
fingerprint means the same there:

| input | saved as | carries across processes |
|---|---|---|
| file or glob | each file's real path, size and modification time | yes |
| table of a DuckDB database file | the file, the table, its row count, columns and storage blocks | yes |
| pandas DataFrame or numpy array | its values and row order | yes |
| Polars or Arrow table, relation, table of an in-memory database | nothing | no |

For an input of the last kind, `apply` works after loading, but the first
`learn` learns again, without a warning.

## When the data changed

At the next `learn` or `train` (never at `apply` or `predict`), when the data
is the same file or table as the saved one and its fingerprint differs,
sqlearn learns again and warns with a `SqlearnWarning` that names the source
and the file, with a `Fix:` line: save the pipeline again to keep the new
values. A glob that gains or loses a file counts as a change. A file moved to
another machine has another modification time, so it is learned again there,
with the warning: sqlearn errs towards learning again rather than reading the
whole file to hash it.

The warning belongs to the source (the file or table), not to the loaded
pipeline: the first `learn` or `train` from that source in the process gets
it, once. A different file is simply new data, and a pandas DataFrame has no
source to compare with: a changed one is learned without a warning.

## A table: `CHECKPOINT` first

A table with writes not yet checkpointed would get a new fingerprint at the
next checkpoint (DuckDB checkpoints when the database closes) without any
edit. A warning then would be false. So `sq.save` warns and saves that
table's fingerprint as unknown, and a new process learns it again. Run
`CHECKPOINT` before learning and saving: the fingerprint is read when
learning.

```python
con.execute("CHECKPOINT")
pipe.learn("customers", target="churned")
sq.save(pipe, "customers.sqlearn.json")
```

sqlearn never runs `CHECKPOINT` on your database itself
([ADR 0046](../adr/0046-sqlearn-warns-the-user-chooses.md)).

## Sharing a recipe: `learned=False`

```{code-cell} python
sq.save(pipe, folder / "recipe.sqlearn.json", learned=False)
[name for name, _ in sq.load(folder / "recipe.sqlearn.json").steps]
```

The recipe alone holds no data and no learned value, and can be sent to
someone else. Learned values are not the same: they come from data, and a
category an encoder learned is a real value from your data (a name, a city,
a code). Share a learned file only as you would share the data's categories.

## Loading imports only what you allow

A class in the file is code to import, and importing a module runs it. So
`sq.load` imports classes of `sqlearn` and nothing else unless you allow the
package:

```python
pipe = sq.load("churn.sqlearn.json", allow=["sklearn"])  # a scikit-learn model
```

Every class in the file is read and checked before any is imported, and the
whole file is refused, naming each package and step, if one is not allowed.
The check follows the class a path finally resolves to, by the module that
defines it. Of sqlearn's own classes, a file builds only steps, `sq.Model` and
the fold schemes of `sq.folds` from settings; it refuses any other, however the
file names it (an allowed package that imports a sqlearn class does not open
that class up), and a learned value that names a class. Allow only packages
you trust.

## The trained model, only when asked

A model's trained state belongs to its library, and for scikit-learn it is a
pickle. Opening a pickle can run any code its author put in it, so saving the
model is opt-in, and so is opening it:

```python
sq.save(trained, "churn.sqlearn.json", model="pickle")
# writes churn.sqlearn.json and churn.sqlearn.model.pickle

pipe = sq.load("churn.sqlearn.json", allow=["sklearn"], trust_model=True)
pipe.predict(...)  # trained: nothing to train again
```

The model file is named by `Path(path).with_suffix(".model.pickle")`. The JSON
stays pure: it names the model file, its format and its SHA-256. Without
`trust_model=True` the model file is never opened: the pipeline loads learned
but not trained, with a warning, and `predict` refuses until `train`.

With `trust_model=True` the file is read once and refused unless its SHA-256
matches the JSON's; the bytes checked are the bytes unpickled. Know what that
does and does not prove:

- **The checks on the model run after the file is opened.** The model must be
  of the class the recipe names, whose package `allow=` lists, but that is
  checked on the object the pickle gave. By then any code the pickle carries
  has run.
- **`trust_model=True` goes around `allow=`** for whatever the pickle itself
  imports. A pickle names its own modules, and opening it imports them
  whether `allow=` lists their packages or not.
- **The hash proves only that the model file matches the JSON**, so that
  neither changed without the other since the save. It says nothing of who
  wrote them: an author who supplies both files controls both, hash included.

So pass `trust_model=True` only when you trust whoever gave you both files,
as you would before running their code.

## For authors of steps: `state_version`

A saved file holds what a step's `learn` returned. If you change the names or
the meaning of what `learn` returns, raise the class attribute
`state_version` (it starts at 1). A file saved with the old number then loads
as a recipe, with a warning naming the step, and the next `learn` learns
everything again, rather than `apply` reading values that mean something
else. See [writing a step](writing-a-step.md).

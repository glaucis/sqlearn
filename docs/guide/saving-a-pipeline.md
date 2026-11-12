---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [save, load, json, recipe, learned-state, fingerprint, trained-model, use-model, import, joblib, state-version, checkpoint]
summary: "How sq.save and sq.load keep sqlearn's part of a pipeline across processes (the recipe and the learned values in one JSON file), how the user saves the trained model with its own library and puts it back with pipe.use_model, what sq.load imports (nothing) and builds (only steps, models and folds), which inputs carry their values to a new process, the warning when the data changed, CHECKPOINT before saving a table, sharing a recipe with learned=False, and state_version for step authors."
related: [docs/specs/library-saving.md, docs/adr/0047-a-pipeline-saves-as-json.md, docs/adr/0048-the-user-saves-the-model-and-imports-its-packages.md, docs/specs/library-saving-the-model.md, docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/guide/inputs-and-the-store.md, docs/guide/writing-a-step.md]
---

# Saving a pipeline

The learned values live in the learning store while the program runs, so a
restart learns everything again. `sq.save` writes a pipeline to one file, and
`sq.load` reads it back in a new process
([ADR 0047](../adr/0047-a-pipeline-saves-as-json.md)). The case it is made
for: the data is prepared and learned today, there is no time to train the
model, and tomorrow the pipeline just runs.

sqlearn saves and loads its own part, the steps and what they learned. The
trained model is yours: you save it with the library it comes from, as you would
without sqlearn, and you import the packages a file names before you load it
([ADR 0048](../adr/0048-the-user-saves-the-model-and-imports-its-packages.md)).

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

## Four cases

**1. No saving.** Most programs train and predict in one process. Nothing
here is needed.

**2. Saving both parts.** `sq.save` writes sqlearn's part. The trained model
is `pipe.model_`, the library's own object (a `CatBoostClassifier`, not
`sq.Model`), and you save it in its library's way:

```python
import sqlearn as sq
from catboost import CatBoostClassifier

pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.encode.onehot("city"),
        CatBoostClassifier(verbose=0),
    ]
)
pipe.train("customers.parquet", target="churned")

sq.save(pipe, "churn.json")  # sqlearn's part
pipe.model_.save_model("churn.cbm")  # the model, in CatBoost's own format
```

**3. A new process.** Import what the file names, load, open the model, and
put it back with `use_model`:

```python
import sqlearn as sq
from catboost import CatBoostClassifier

pipe = sq.load("churn.json")  # imports nothing
pipe.use_model(CatBoostClassifier().load_model("churn.cbm"))
pipe.predict("new_customers.parquet")  # no learning, no training
```

`use_model` works when the pipeline has a training record: the file was
saved after `train`, or the pipeline was trained here. Without the JSON, give
`use_model` the training data and it learns the steps again, rebuilds the
record and does not fit the model:

```python
pipe = sq.Pipeline([sq.impute.median(), sq.encode.onehot("city"), CatBoostClassifier()])
pipe.use_model(
    CatBoostClassifier().load_model("churn.cbm"),
    data="customers.parquet",
    target="churned",
)
pipe.predict("new_customers.parquet")  # steps learned again; no training
```

Pass the same training data the model was trained on. Without the JSON,
nothing can check that it is the same, and a model fed columns made from other
data predicts nonsense without an error.

`use_model` holds the object you pass, not a copy. A later `train` on that
pipeline fits the same object again.

**4. A recipe trained again.** A recipe shared to be trained by someone else
needs no model file. The person who loads it has the model's package:

```python
import sqlearn as sq
import catboost  # you choose what runs

pipe = sq.load("recipe.json")  # builds an untrained CatBoostClassifier
pipe.train("customers.parquet", target="churned")
```

Here is a case 2 and 3 that runs, with scikit-learn and `joblib`, which
comes with it:

```{code-cell} python
import joblib
from sklearn.linear_model import LogisticRegression

model_pipe = sq.Pipeline(
    [
        sq.impute.median(),
        sq.encode.onehot("city", "plan"),
        sq.scale.standard(),
        LogisticRegression(),
    ]
)
model_pipe.train(data, target="target")
sq.save(model_pipe, folder / "churn.json")
joblib.dump(model_pipe.model_, folder / "churn.joblib")

# the new process
again = sq.load(folder / "churn.json")
again.use_model(joblib.load(folder / "churn.joblib"))
again.predict(data).shape
```

## The model, in its library's way

What follows is advice about other libraries, not sqlearn's code. Check each
library's documentation for its version.

- **CatBoost:** `save_model` and `load_model` (a `.cbm` file). `load_model`
  gives the classifier back, as in the example above.
- **XGBoost:** `save_model` and `load_model` on its scikit-learn class
  (`XGBClassifier`). sqlearn's tests do not cover XGBoost, so try it on your
  data before relying on it.
- **LightGBM:** its own text file reloads as a `Booster`, not as an
  `LGBMClassifier`, and `use_model` refuses a model of another class than the
  recipe's. With sqlearn use `joblib` for it.
- **scikit-learn:** `joblib`, or `skops`. `joblib` is pickle, which runs
  whatever code its author put in the file when it is opened: only open files
  you wrote. `skops` does not run code that way, so it suits a file from
  someone else.

## What is saved, and what is not

The file is JSON, never pickle: opening it runs nothing from it. The same
pipeline always gives the same bytes, so a change is a readable diff. It
holds:

- **the recipe:** each step's class and settings, in order, selectors
  included, and the model by its class and parameters, never trained;
- **the learned values** of every step, once the pipeline has learned or
  trained: medians, means, categories, folds of a target encoder, as exact
  values (a float reads back as the same double). A learned
  `TIMESTAMP WITH TIME ZONE` value is the same instant in UTC;
- **the fingerprint of the data** the values came from, so that sqlearn can
  tell later whether that data changed;
- **the training record**, for a pipeline trained with `train`: the form the
  model was fed in and the categories of its text columns, which
  `use_model` needs to put the model back.

It does not hold the data and never the trained model. A search object is not
saved; its best pipeline is a `Pipeline` and saves as one. A setting that has
no exact form is refused when saving, never written approximately: a lambda,
a numpy array, a function passed to a model. The error names the step and the
setting and says what would save. A step of your own saves by its import
path, so it must live in an importable module, not in `__main__` or inside a
function.

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

## Loading imports nothing, and builds only what a pipeline holds

A file names classes, and importing a module runs it. So `sq.load` imports
nothing. It finds a class only in a module your program has already
imported. When one is missing, the whole file is refused, every missing
class named at once:

```text
the file names 'catboost.core:CatBoostClassifier', which is not imported.
Why: sq.load imports nothing, so loading a file can never run code you did
not choose to run. Fix: import CatBoostClassifier from catboost before
loading.
```

You import the packages as you would to build the pipeline in code. The
lookup runs no code of the module it reads.

A file also builds only what a pipeline holds: a sqlearn step, a model (an
object with `fit` and `predict`), an estimator nested in the model's settings
(one with `get_params`) or a fold scheme. A class of any other kind is refused
before anything is built, even when its module is imported. A crafted file
naming `subprocess.Popen` is the case this is for: `Popen` is none of those
four, so it is refused and no process starts, whatever you imported.

## For authors of steps: `state_version`

A saved file holds what a step's `learn` returned. If you change the names or
the meaning of what `learn` returns, raise the class attribute
`state_version` (it starts at 1). A file saved with the old number then loads
as a recipe, with a warning naming the step, and the next `learn` learns
everything again, rather than `apply` reading values that mean something
else. See [writing a step](writing-a-step.md).

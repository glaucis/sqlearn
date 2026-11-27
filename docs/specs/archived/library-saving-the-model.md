---
type: spec
tags: [saving, loading, models, imports, security, library-breadth]
summary: "Spec for #55 under ADR 0048: the user saves and opens the trained model in any format, pipe.model_ hands it out and pipe.use_model puts it back; sq.save writes only sqlearn's part, sq.load imports nothing and builds only steps, models and fold schemes from modules already imported; allow=, trust_model= and model= are removed."
related: [docs/adr/archived/0048-the-user-saves-the-model-and-imports-its-packages.md, docs/adr/archived/0047-a-pipeline-saves-as-json.md, docs/specs/archived/library-saving.md, old_python/docs/guide/saving-a-pipeline.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Library breadth: saving the model

A change to the saving area ([its spec](library-saving.md)), for issue
[#55](https://github.com/glaucis/sqlearn/issues/55), under
[ADR 0048](../../adr/archived/0048-the-user-saves-the-model-and-imports-its-packages.md).
Where this spec amends the saving spec, this one wins.

Status: written on 2026-11-11 from the design talk of the same day, and checked
by a builder's read; for Tomas to approve before the plan. Where this spec makes
a call of its own, it says "(spec's call)"; section 11 lists them.

## 1. Purpose

Tomas, 2026-11-11: *the user can install their own models, not sqlearn. If I
use scikit-learn and need CatBoost, I install it, and the user does the same
for every model they need.* And: *if the user wants to use something that is
not part of sqlearn, they import it.*

Today sqlearn saves the trained model itself, by pickle only, and guards
loading with two switches, `allow=` and `trust_model=`, which confused the
person they were for. After this change:

- the trained model is the user's: they save it and open it in whatever
  format they choose, as they would without sqlearn;
- sqlearn saves and loads only its own part, and loading a file can never run
  code by being opened;
- a program that loads a pipeline imports the packages its steps and model
  come from, as it would to build the pipeline in code; sqlearn imports
  nothing for it.

## 2. What it looks like

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

The next day, in a new process:

```python
import sqlearn as sq
from catboost import CatBoostClassifier

pipe = sq.load("churn.json")  # imports nothing; no allow=
pipe.use_model(CatBoostClassifier().load_model("churn.cbm"))
pipe.predict("new_customers.parquet")  # no learning, no training
```

With the model file and the training data but no JSON, sqlearn rebuilds its
part from the data (Tomas, 2026-11-11: *if something is missing, rebuild or
relearn it from what is there*):

```python
pipe = sq.Pipeline([sq.impute.median(), sq.encode.onehot("city"), CatBoostClassifier()])
pipe.use_model(
    CatBoostClassifier().load_model("churn.cbm"),
    data="customers.parquet",
    target="churned",
)
pipe.predict("new_customers.parquet")  # steps learned again; no training
```

A recipe shared to be trained again, by someone who has CatBoost:

```python
import sqlearn as sq
import catboost  # the user chooses what runs

pipe = sq.load("recipe.json")  # builds an untrained CatBoostClassifier
pipe.train("customers.parquet", target="churned")
```

The same file loaded without `import catboost` is refused:

```
sq.load: churn.json names catboost.core:CatBoostClassifier, but catboost.core
is not imported. Why: sq.load imports nothing, so loading a file can never
run code you did not choose to run. Fix: import CatBoostClassifier from
catboost before loading.
```

## 3. `pipe.model_` and `pipe.use_model`

- **`pipe.model_`** is the trained model: the estimator object the model step
  wraps, the library's own (a `CatBoostClassifier`, not `sq.Model`). It is a
  read-only property of `Pipeline`. On a pipeline with no model, or one not
  trained, it raises `SqlearnError` in the house form (`Fix: call
  train(data, target=...) first`) (spec's call: the trailing underscore
  follows scikit-learn's habit for what training makes, as `categories_` on
  steps does).
- **`pipe.use_model(model, data=None, target=None, feed=None)`** puts a
  trained model into the pipeline in place of its model step's estimator, so
  `predict` runs with no training. It returns the pipeline, so calls chain.
  It works two ways (Tomas, 2026-11-11):
  - **without `data`**, on a pipeline that has a training record (loaded
    from a file saved after `train`, or trained in this process): instant,
    nothing is read;
  - **with `data` and `target`**, on any pipeline ending in a model: it does
    what `train(data, target, feed)` does, the steps learned (or found in
    the store, so unchanged data learns nothing again) and the training
    record made, in the same `feed` and with the same categories `train`
    would make, but the model is not fitted: the one passed is used. It
    costs one pass over the data. How the categories are read is the
    builder's call (`train` reads them while fetching every feature; a query
    of each text feature's values is enough), but they must equal `train`'s
    for the same data, order included, and a test says so. With no JSON
    there is no fingerprint, so sqlearn cannot tell whether this is the data
    the model was trained on: the docstring and the guide say to pass the
    same training data. `data` given replaces any training record the
    pipeline had.

  It refuses, each with `Why:` and `Fix:`:
  1. a pipeline whose last step is not a model;
  2. without `data`, a pipeline with no training record (built in code and
     never trained, a file saved with `learned=False`, or one whose learned
     part was dropped by a `state_version` change). `Fix: pass the training
     data, as use_model(model, data=..., target=...), or load the file
     sq.save wrote after train.`; `target` or `feed` given without `data`,
     and `data` without `target`, refused as `train` refuses a missing
     target;
  3. an object with no `fit` or no `predict` (not a model);
  4. a model of another class than the pipeline's model step holds
     (`isinstance` against the class the recipe names). `Fix: build the
     pipeline with that model, or pass a <class>.` (spec's call, as the
     pickle path checked before);
  5. a model not trained (below).
- **Trained** is decided without importing any library (spec's call): the
  model's own `__sklearn_is_fitted__()` when it has one (scikit-learn
  pipelines, LightGBM); else its `is_fitted()` when it has one (CatBoost);
  else whether it has a public attribute ending in `_` (scikit-learn's
  `check_is_fitted` rule, without scikit-learn). Checked on 2026-11-11 for
  scikit-learn's `LogisticRegression`, `BaggingClassifier` and `Pipeline`,
  LightGBM's `LGBMClassifier` and CatBoost's `CatBoostClassifier`, fitted and
  reloaded.
- Without `data`, `use_model` changes only the estimator: the steps' learned
  values, the feed and the categories stay as they were. It checks the model
  (refusals 3 to 5) before reading any data. It does not copy the model: the
  pipeline holds the object passed, as `Pipeline([...])` holds its steps.
- **Two facts, kept apart** (spec's call, after the builder check): the
  pipeline's **training record** (the feed and the categories, set by
  `train` or by loading a file that has `trained`) and **whether its model
  is trained** (set only by `train` and `use_model`, cleared when a fit
  fails, as `_feed` is cleared today). `predict` and `model_` need both;
  `use_model` needs the training record; `sq.save` writes `trained` whenever
  the training record exists. So a pipeline loaded and saved again before
  `use_model` keeps its `trained` key, and a model fitted by hand through
  `pipe.steps` does not count until it is passed to `use_model`.

## 4. `sq.save`

- **`model=` is removed.** `sq.save(pipe, path, *, learned=True)`.
- **A trained pipeline's file holds what training handed the model**, in a
  new optional top-level key `trained`, written after `learned` when the
  pipeline has a training record (section 3) and `learned=True`:

  ```json
  "trained": {"feed": "pandas", "categories": {"city": ["oslo", "paris"]}}
  ```

  `feed` is the form the model was trained on (`Pipeline._feed`), and
  `categories` each text feature's categories in training order
  (`Pipeline._categories`), encoded as today's `model_file` record encodes
  them. The key `model_file`, the model file, its SHA-256 and the format
  registry (`sqlearn/_saving/models.py`) are removed.
- `learned=False` writes neither `learned` nor `trained`, as today a recipe
  holds nothing learned.
- **`format_version` stays 1** (spec's call): sqlearn has not been released,
  so no file in use has `model_file`. A file that has one is refused as an
  unknown field, as any unknown field is.

## 5. `sq.load`

`sq.load(path)`: `allow=` and `trust_model=` are removed.

- **It imports nothing.** A class path `module:qualname` resolves only when
  `module` is already in `sys.modules`; the qualname is then walked by
  attribute, as today (a walk through a module is still refused). A module
  not imported is refused before anything is built, naming the class, the
  module, and in `Fix:` the class to import and the top-level package it
  comes from (`Fix: import CatBoostClassifier from catboost before
  loading`). A package not installed gives the same message: to import it,
  the user installs it. Every class the file names is checked before any is
  built, as `check_allowed` checks them today, and the first file-wide
  refusal names every class not imported, not only the first (spec's call:
  one round of imports fixes the file).
- **Only what belongs in a pipeline is built.** The class is checked before
  it is built:
  - a step record: a subclass of `sq.Step` (as today);
  - the model record's estimator: `fit` and `predict` (as today);
  - an estimator nested in the model's settings (a `BaggingClassifier`'s
    `estimator`, a `StackingClassifier`'s list, a scikit-learn `Pipeline`'s
    steps, a Gaussian process's kernel): `get_params`, which is what makes
    `sq.save` write a value as an estimator (`_param` in `recipe.py`). Today
    such a class is "any class" once allowed; this check replaces the
    package check;
  - an `object` tag: the closed list of fold schemes, as today;
  - `sq.Model` for the model record, as today.

  Anything else is refused, naming the class and why, before anything is
  built. `subprocess.Popen` named anywhere is refused by this check.
- **What stays as it is:** no class of sqlearn as an estimator, top-level or
  nested, however the path names it; the learned part and the categories name
  no class; a class found through a re-export is checked by the module that
  defines it (for the sqlearn rule); the nesting limit; the version and field
  checks; the warnings (newer sqlearn, `state_version`).
- **`trained`** is read with `learned`: when the learned part is restored,
  `Pipeline._feed` and `Pipeline._categories` are set from it, so
  `use_model` can follow. The model step keeps its untrained estimator built
  from the recipe, so the pipeline is learned, not trained: `predict`
  refuses (`Fix: train, or put a trained model back with use_model`) until
  `use_model` or `train`. A `trained` key with no `learned`, or on a file
  whose last step is not a model, or whose feed is not one of `FEEDS`, or
  whose categories are not lists of text, is refused as damaged. When the
  learned part is dropped (a `state_version` mismatch), `trained` is dropped
  with it.

### What the settings survey found

ADR 0048 asked which settings are objects rather than plain values. A
survey on 2026-11-11 of the default settings of every scikit-learn estimator
(`all_estimators()`), LightGBM's and CatBoost's classifiers and regressors
(XGBoost is not installed in the test group) found:

- **No model has an object as a default setting.** Every object found
  belongs to a transformer: functions (`score_func` of the `Select*`
  classes, `pooling_func`) and types (`dtype` of the encoders and
  vectorisers). `sq.save` already refuses them (a callable, a type, an array,
  a random state cannot be saved).
- **Objects the user passes** as settings are nested estimators, saved by
  their class and parameters and now checked by `get_params` (above).
  Anything else is refused at save, as today.

So no named list is needed beyond the fold schemes that exist today.

## 6. What is removed

- `allow=` and `trust_model=` on `sq.load`; `model=` on `sq.save`;
  `check_allowed`; the `allow` parameters of `import_class`, `build_step`,
  `build_model` and `_import_of`.
- `sqlearn/_saving/models.py` (`ModelFormat`, `FORMATS`) and its tests; the
  `model_file` key; the pickle, the SHA-256 and the warning about a model
  file not opened.
- From the docs: every mention of the above in the guide, the saving spec
  (a note at its top pointing here, as its other notes do; its text stays as
  the record of what was built), and the API reference.

## 7. Errors

Every refusal is a `SqlearnError` in the house form (what, `Why:`, `Fix:`).

- Load: a class whose module is not imported (every such class named); a
  class not a step, model, nested estimator or fold scheme; a damaged
  `trained` key; and every refusal of the saving spec's section 9 that does
  not concern `allow=` or the model file.
- `model_`: no model; not trained.
- `use_model`: the five refusals of section 3; with `data`, every refusal
  of `train` (a target not a column, a feature not a number for numpy, a
  feed not installed).
- `predict` on a loaded pipeline with no model put back: as today for a
  pipeline not trained, with the `use_model` fix added.

## 8. Docs

- **The guide page "Saving a pipeline"** is rewritten around four cases:
  1. no saving (most programs);
  2. saving both parts: `sq.save` for sqlearn's part, the model in its
     library's own way;
  3. loading in a new process: import, `sq.load`, open the model,
     `use_model`, `predict`; and without the JSON, `use_model` with the
     training data, which learns the steps again (pass the same data the
     model was trained on: without the JSON nothing can check it);
  4. a recipe shared to be trained again.

  It says what each model library offers and what to watch for, as advice,
  not as sqlearn's code: CatBoost's `save_model`/`load_model` (`.cbm`), which
  gives the classifier back; XGBoost's `save_model`/`load_model` on its
  scikit-learn class; LightGBM's own text file, which reloads as a `Booster`,
  not an `LGBMClassifier`, so with sqlearn use `joblib` for it; scikit-learn's
  `joblib` (runs code when opened: only your own files) or `skops` (does not).
  It keeps the section on what is saved and why a file can be shared, and
  explains the import rule and the kind rule in plain words, with the
  `subprocess.Popen` example.
- Docstrings with an example each: `Pipeline.model_`, `Pipeline.use_model`,
  the new `sq.save` and `sq.load`.
- `GLOSSARY.md` already defines **Trained model** this way (ADR 0048).
- The saving spec gets a note at its top; the overview and `HANDOFF.md` are
  updated as usual.

## 9. Tests

Through the public seams (`sq.save`, `sq.load`, `Pipeline`), named in
`GLOSSARY.md` terms:

- **The core test, across processes:** for scikit-learn
  (`LogisticRegression`, and a `BaggingClassifier` with a nested estimator),
  LightGBM and CatBoost (the test group's model libraries): train, save the
  file, save the model in the test with the library's own way or `joblib` as
  the guide advises; in a new subprocess import the library, load, open the
  model, `use_model`, `predict`: equal to the original's predictions, with
  text features fed as categories (`feed="pandas"`) for at least one library.
- **Nothing is imported:** a file naming a class of a test module that
  records its own import is refused, and the module is still not in
  `sys.modules` afterwards; the message names every class not imported and
  the fix.
- **The kind rule:** a file naming `subprocess:Popen` as a step, as the
  estimator, as a nested estimator, and as an `object`, each refused before
  anything is built (`subprocess` imported beforehand, so only the kind rule
  can refuse it).
- **`use_model` with the data, no JSON:** in a new subprocess, the pipeline
  built in code, `use_model(model, data=..., target=...)` with the model
  file and the training data, then `predict`: equal to the original's, with
  text features fed as categories (`feed="pandas"`); its categories equal
  `train`'s on the same data, order included; on data the store already
  holds, nothing is learned again (`STORE.learns`).
- **`use_model` refusals**, each of section 3, and `model_` on a pipeline not
  trained.
- **`trained` round trip:** feed and categories come back equal; a damaged
  `trained` key is refused; a `state_version` mismatch drops it.
- **The old switches are gone:** `sq.load(path, allow=[...])`,
  `sq.load(path, trust_model=True)` and `sq.save(pipe, path, model="pickle")`
  fail as unknown keywords (Python's own `TypeError`; spec's call: sqlearn
  has not been released, so no message pointing to the new way).
- Existing saving tests that pass `allow=` drop it and import the package
  instead; the cross-process tests keep everything else they check.
- The docs build with its doctests passes.

## 10. Answered in the talk

1. **A model put back without the JSON** (Tomas, 2026-11-11): what is
   missing is rebuilt from what is there. The data is the ground, the JSON
   holds the learned values, the model file the trained model; without the
   JSON, `use_model(model, data=..., target=...)` learns the steps again and
   remakes the training record from the data, and uses the model passed
   (section 3). `learn` is unchanged: it still refuses a pipeline ending in
   a model.

## 11. The spec's calls, for Tomas to check

1. `model_` is a read-only property, refusing when not trained.
2. `use_model` checks the class against the recipe's, and trainedness
   without importing any library (section 3's order of checks).
3. `use_model` holds the object passed, without copying it.
4. `trained` is a new top-level key; `format_version` stays 1.
5. The load refusal names every class not imported at once.
6. A nested estimator is checked by `get_params`, the rule `sq.save` uses
   to write one.
7. The old keywords fail with Python's `TypeError`, no migration message.
8. The guide advises `joblib` for LightGBM inside sqlearn, as its own text
   file reloads as a `Booster`.
9. The training record and "the model is trained" are two facts (section
   3): a loaded pipeline saved again keeps `trained`, and only `train` and
   `use_model` make the model count as trained.

## 12. Not in this area

Saving a model in sqlearn's name in any format; a list of supported model
libraries; XGBoost in the test group; saving a search or the whole store;
exporting a pipeline as code (#24, part 2).

---
type: adr
tags: [saving, loading, security, models, imports, api]
summary: "Amends ADR 0047: the user saves and opens the trained model in any format and puts it back with use_model; sq.save writes only sqlearn's part; sq.load imports nothing and builds only steps, models and fold schemes from packages the user has imported; allow=, trust_model= and model='pickle' are removed."
related: [docs/adr/0047-a-pipeline-saves-as-json.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0004-apache-2-licence.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/specs/library-saving.md]
---
# 0048: The user saves the model and imports its packages

Status: accepted (2026-11-11). Amends
[ADR 0047](0047-a-pipeline-saves-as-json.md). Issue: #55.

## Context

ADR 0047 saved the trained model only by pickle, written by sqlearn. Opening
a pickle can run code, so loading it needed `trust_model=True`, and the
classes a saved file names were imported only as `allow=` permitted. #55
asked for formats that cannot run code. Each of them (CatBoost's `.cbm`,
LightGBM's text model, XGBoost's JSON, skops for scikit-learn) belongs to a
library the user installs, never sqlearn ([ADR 0004](0004-apache-2-licence.md),
[ADR 0005](0005-runtime-dependencies.md)), and each library already saves
itself. Building them into sqlearn would make sqlearn choose, wrap and test
every library's format, and keep two switches users found confusing.

In scikit-learn the user saves a pipeline with `joblib.dump` and chooses the
format. `joblib.load` imports whatever the file names, silently, so a file
from someone else can run any code.

## Decision

- **The model is the user's.** After `train`, `pipe.model_` is the trained
  model, the library's own object. The user saves it and opens it, in any
  format, as without sqlearn. `pipe.use_model(model)` puts a trained model
  back into a pipeline whose steps have learned, so `predict` runs with no
  training. It refuses, with a `Fix:` line, a pipeline with no model, an
  object with no `predict`, and a model that is not trained.
- **`sq.save` stays optional and writes only sqlearn's part:** the recipe,
  the learned part, and, once trained, what `use_model` needs from training
  (the feed the data was handed over in, and the categories the model saw).
  It never writes the model.
- **The user imports; sqlearn never does.** `sq.load` imports nothing. A
  class the file names is found only in a module the user's program has
  already imported; otherwise the file is refused, naming the class and the
  package to import (`Fix: import catboost before loading`). A package not
  installed gives the same message, since it cannot be imported.
- **Only what belongs in a pipeline is built.** Before any class is built,
  the class itself is checked: a sqlearn step, a model (it has `fit` and
  `predict`), or a fold scheme of `sq.folds`. Anything else is refused,
  naming it, before anything is built. Most of Python's standard library is
  always imported (`os`, `shutil`, `socket`, and `subprocess` after
  `import catboost`), so without this check a file could build
  `subprocess.Popen` with a command of its choosing.
- **Support follows what a class can do, not a list of packages.** Any
  model with `fit` and `predict`, from any package, is supported with no
  change to sqlearn.
- **Removed:** `allow=` and `trust_model=` on `sq.load`, `model=` on
  `sq.save`, the pickle model file and its format registry. sqlearn has not
  been released, so no user's code or file moves over.

## Considered options

- **sqlearn writes each library's own format** (#55 as filed): no
  `trust_model` for those formats, but sqlearn chooses and maintains a
  format per library, and pickle stays for the rest.
- **Keep `allow=` and drop only pickle:** the user would still name in code
  each package a file may import, when importing it already says that.
- **The "imported" check alone:** simpler, but it builds any class of an
  imported module, `subprocess.Popen` included.

## Consequences

- No file sqlearn opens can run code by being opened; the model file the
  user opens is theirs to trust, as any file they open in Python.
- A program loading a pipeline imports the packages its steps and model come
  from, as it would to build the pipeline in code.
- To check before building: settings that are objects rather than plain
  values (a scikit-learn ensemble's inner model, a random-number generator).
  An inner model passes the model check; any other kind found in the
  libraries sqlearn is tested with is named in the spec, or refused.
- A class with `fit` and `predict` in an imported package is built with the
  file's settings, running its `__init__`: the user chose to import that
  package.

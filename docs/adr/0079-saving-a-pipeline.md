---
type: adr
tags: [saving, pipeline, json, serialization, security, sqlearn]
summary: "Accepted ADR consolidating sqlearn's rules for saving and loading pipelines as JSON, with the trained model kept separate and no imports by sq.load."
related: [docs/adr/archived/0047-a-pipeline-saves-as-json.md, docs/adr/archived/0048-the-user-saves-the-model-and-imports-its-packages.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0076-the-learning-store-and-its-keys.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md]
mdindex: [type=0fc814, tags=30e998, summary=a950cf, related=29bd45]
---
# 0079: Saving a pipeline: JSON, sqlearn's part only, nothing imported

Status: accepted (2026-11-27). Written on Tomas's decision of 2026-11-27, in the
docs cleanup, to consolidate the records below: it states their rules as they
stand and takes no new decision. Supersedes
[ADR 0047](archived/0047-a-pipeline-saves-as-json.md) and
[ADR 0048](archived/0048-the-user-saves-the-model-and-imports-its-packages.md).
Restates the saving rule of [ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md).
Specs: [library saving](../specs/archived/library-saving.md),
[saving the model](../specs/archived/library-saving-the-model.md).

## Context

The rule for saving a pipeline was spread over three records. ADR 0047
(2026-11-11) made `sq.save` and `sq.load` write a pipeline's recipe and
learned part as one JSON file, never pickle, with tagged values, classes
imported only as `allow=` permitted, and the trained model saved only on
request as a pickle beside it. ADR 0048 (2026-11-11, #55) amended it: the
user saves the trained model in any format, `sq.save` writes only sqlearn's
part, `sq.load` imports nothing and builds only what belongs in a pipeline,
and `allow=`, `trust_model=`, `model=` and the pickle file went. ADR 0070
(2026-11-27), which stays current, added that files saved before the C++
rewrite need not load after it, and that `sq.load`'s security rules hold in
C++.

## Decision

- **Two functions, `sq.save(pipe, path)` and `sq.load(path)`**, as
  `joblib.dump` and `joblib.load` take an object and a path
  ([ADR 0003](0003-scikit-learn-style-api.md)). No method on the pipeline
  (ADR 0047; `allow=` removed by ADR 0048).
- **One file for sqlearn's part only:** the recipe and, when learned, the
  learned part; once trained, also what `use_model` needs from training (the
  feed the data was handed over in, and the categories the model saw).
  `learned=False` saves the recipe alone, to share it. The file never holds
  the trained model (ADR 0047, ADR 0048).
- **JSON, never pickle.** UTF-8, indented by two spaces, keys in a fixed
  order, so the same pipeline gives the same bytes. Opening it never runs
  code from it. It is written to a temporary file and renamed, so a failed
  save leaves no half file (ADR 0047).
- **Values are plain JSON when JSON says them exactly, tagged objects
  otherwise:** an object whose first key is `"$"`. Every mapping is tagged,
  so a user's key never collides with a tag. The tags are `float` (NaN,
  `inf`, `-inf`), `tuple`, `dict` (key-value pairs, keeping order),
  `decimal`, `date`, `datetime`, `time`, `timedelta`, `uuid`, `bytes`
  (base64), `selector`, `aggregate` (one of `sq.agg`), `constant_text`,
  `object` (a fold scheme of `sq.folds`, by class path and settings, from a
  closed list checked as text before anything is built) and `estimator` (a
  model's estimator by class path and parameters). A finite float is written
  as text that reads back as the same double. A value with no tag is refused
  at save, naming the step, the setting and the type, never written as its
  string form (ADR 0047). The tags are the file format's, though several
  are named after Python types: since files saved before the C++ rewrite
  need not load after it (ADR 0070), the C++ saving group may rename or
  extend them, and records the set it settles on.
- **The trained model is the user's.** After `train`, `pipe.model_` is the
  trained model, the model library's own object. The user saves and opens
  it, in any format, as without sqlearn. `pipe.use_model(model)` puts a
  trained model back into a pipeline whose steps have learned, so `predict`
  runs with no training. It refuses, with a `Fix:` line, a pipeline with no
  model, an object with no `predict`, and a model that is not trained
  (ADR 0048).
- **The user imports; sqlearn never does.** `sq.load` imports nothing. A
  class the file names is found only in a module the user's program has
  already imported; otherwise the file is refused, naming the class and the
  package to import (`Fix: import catboost before loading`). A package not
  installed gives the same message (ADR 0048, replacing ADR 0047's
  `allow=`).
- **Only what belongs in a pipeline is built.** Every class in the file is
  read and checked before any is built: a sqlearn step, a model (it has
  `fit` and `predict`), or a fold scheme of `sq.folds`. Anything else is
  refused, naming it, before anything is built (ADR 0048). The class a path
  finally resolves to is checked, by the module that defines it, so a name
  re-exported into another module cannot slip past. An estimator, top-level
  or nested, is never a class of sqlearn; a fold scheme comes back only by
  the `object` tag, never as an estimator; `sq.Model`'s own settings hold no
  estimator; and the learned part and the model's categories name no class:
  one named there is refused (ADR 0047).
- **Support follows what a class can do, not a list of packages:** any model
  with `fit` and `predict`, from any package, is supported with no change to
  sqlearn (ADR 0048).
- **The learned part is filed under the stable key**, with the data's
  fingerprint: loading fills the learning store by it, so a later `learn` on
  unchanged data learns nothing again, and on changed data learns again with
  a warning ([ADR 0076](0076-the-learning-store-and-its-keys.md),
  ADR 0047).
- **sqlearn does not adjust what it cannot honour:** it refuses, or loads
  with a warning in the house form
  ([ADR 0046](0046-sqlearn-warns-the-user-chooses.md); ADR 0047).
- **Files saved before the C++ rewrite need not load after it**: nothing is
  released (ADR 0070).
- **The security rules hold in C++:** a static class lookup, and values
  reach exact arithmetic only as plain numbers. The saving group gets a
  whole-branch security review of its own (ADR 0070).
- **Removed:** `allow=` and `trust_model=` on `sq.load`,
  `model=` on `sq.save`, the pickle model file and its format registry
  (ADR 0048, removing what ADR 0047 added).
- **Mechanics:** the old Python implemented saving with the standard
  library's `json`, `hashlib` and `pickle`, under `src/sqlearn/_saving/`
  (now `old_python/src/sqlearn/_saving/`). The C++ group's design decides the
  mechanics ([ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md)).

## Consequences

- A recipe can be shared and diffed; a file from someone else cannot run an
  installed module by naming it (ADR 0047). No file sqlearn opens can run
  code by being opened; the model file the user opens is theirs to trust, as
  any file they open in Python (ADR 0048).
- A program loading a pipeline imports the packages its steps and model come
  from, as it would to build the pipeline in code (ADR 0048).
- Every setting type a public step, group or model takes needs a row in the
  value table, found by a test that walks them; a new type adds its row
  (ADR 0047).
- A callable, a numpy array or a lambda cannot be saved; the user gives a
  plain value or a step class from a module (ADR 0047).
- Settings that are objects rather than plain values (a scikit-learn
  ensemble's inner model, a random-number generator) are checked before
  building: an inner model passes the model check; any other kind found in
  the libraries sqlearn is tested with is named in the spec, or refused
  (ADR 0048).
- A class with `fit` and `predict` in an imported package is built with the
  file's settings, running its constructor: the user chose to import that
  package (ADR 0048).
- No new dependency ([ADR 0005](0005-runtime-dependencies.md)); nothing
  leaves the machine ([ADR 0006](0006-local-and-offline.md)) (ADR 0047).
- ADRs 0047 and 0048 are archived in `archived/` and keep their numbers.

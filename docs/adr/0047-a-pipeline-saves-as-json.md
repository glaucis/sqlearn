---
type: adr
tags: [saving, json, serialisation, security, pickle, learning-store, api]
summary: "Records that sq.save and sq.load write a pipeline's recipe and learned values as one JSON file with tagged values, never pickle, import only classes from allowed packages, key learned values by the store's stable key, and save a trained model only on request, by pickle in its own file with room for other formats."
related: [docs/specs/archived/library-saving.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# 0047: A pipeline saves as JSON

Status: accepted (2026-11-11); amended by
[ADR 0048](0048-the-user-saves-the-model-and-imports-its-packages.md): the
user saves the model and imports its packages, and `allow=`, `trust_model=`
and `model=` are removed. Spec:
[library saving](../specs/archived/library-saving.md), sections 3, 5, 7 and 8.

## Context

Learned values live in the learning store while the program runs, so a restart
learns everything again, and a recipe cannot be shared. scikit-learn's
`joblib.dump` and `pickle` write anything, and opening such a file can run any
code its author put in it. sqlearn needs a file that holds the recipe and the
learned values, that is safe to open and readable in a diff.

## Decision

- **Two functions, `sq.save(pipe, path)` and `sq.load(path, allow=())`**, as
  `joblib.dump` and `joblib.load` take an object and a path
  ([ADR 0003](0003-scikit-learn-style-api.md)). No method on `Pipeline`.
- **One file for both parts**: the recipe (steps, order, settings, the model
  by class and parameters), and, when learned, each step's learned values.
  `learned=False` saves the recipe alone, to share it.
- **JSON, never pickle.** UTF-8, written by the standard library's `json`,
  indented by two spaces, keys in a fixed order, so the same pipeline gives
  the same bytes. Opening it never runs code from it; the classes it names
  are imported only as `allow=` permits, and the model's pickle is opened
  only with `trust_model=True` (below). It is written to a
  temporary file and renamed, so a failed save leaves no half file.
- **Values are plain JSON when JSON says them exactly, tagged objects
  otherwise**: an object whose first key is `"$"`. Every mapping is tagged, so a
  user's key never collides with a tag. The tags are `float` (NaN, `inf`,
  `-inf`), `tuple`, `dict` (key-value pairs, keeping order), `decimal`, `date`,
  `datetime`, `time`, `timedelta`, `uuid`, `bytes` (base64), `selector`,
  `aggregate` (one of `sq.agg`), `constant_text`, `object` (a fold scheme of
  `sq.folds`, by class path and settings, from a closed list checked as text
  before any import: building another class could run what it does on
  creation) and `estimator` (a model's estimator by class path
  and parameters). Finite floats go by `repr`, which reads back as the same
  double. A value with no tag is refused at save, naming the step, the setting
  and the type, never written with `str()`.
- **Loading is pure and imports only allowed code.** `sqlearn` is always
  allowed; any other top-level package must be named in `allow=`. Every class
  in the file is read and checked before any is imported, and the whole file
  is refused when one package is not allowed. The class a path finally
  resolves to is checked too, by the module that defines it, so a name
  re-exported from an allowed package into another cannot slip past. An
  estimator, top-level or nested, is never a class of sqlearn, whether its
  path starts in sqlearn or in an allowed package that imports one; a fold
  scheme comes back only by the `object` tag, never as an estimator; and
  `sq.Model`'s own settings hold no estimator. The learned part and the
  model's categories name no class: one named there is refused.
- **The store's stable key is a second key**: learned values are saved under
  the key a step's values are stored by, with the data's fingerprint, so a
  later `learn` on unchanged data learns nothing again, and on changed data
  learns again with a warning
  ([ADR 0021](0021-inputs-and-how-the-store-knows-them.md)).
- **The trained model is saved only on request**, by `model="pickle"`, in a file
  of its own beside the JSON (`Path(path).with_suffix(".model.pickle")`). The
  JSON names it, its format and its SHA-256, and stays pure. Loading it is
  opt-in too (`trust_model=True`): the file is read once, and the bytes whose
  SHA-256 matches are the bytes unpickled. The class and `allow=` checks of
  the model run after it is opened, `trust_model=True` goes around `allow=`
  for what the pickle itself imports, and the hash proves only that the model
  file matches the JSON: an author who supplies both files controls both.
  `model=` names a format in a small
  registry, so another format (a library's own file, skops) needs no change to
  the JSON.
- **sqlearn does not adjust what it cannot honour**: it refuses, or loads
  with a warning in the house form
  ([ADR 0046](0046-sqlearn-warns-the-user-chooses.md)).

## Consequences

- A recipe can be shared and diffed; a file from someone else cannot run an
  installed module by naming it.
- Every setting type a public step, group or model takes needs a row in the
  value table, found by a test that walks them; a new type adds its row here.
- A callable, a numpy array or a lambda cannot be saved; the user gives a plain
  value or a step class in an importable module.
- No new dependency: `json`, `pickle`, `hashlib` are the standard library
  ([ADR 0005](0005-runtime-dependencies.md)). Nothing leaves the machine
  ([ADR 0006](0006-local-and-offline.md)).
- The pickle of a trained model remains code to be trusted; the docs say so
  where `trust_model` is described.

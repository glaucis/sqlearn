---
type: spec
tags: [saving, serialisation, json, learned-state, store, pipeline-file, library-breadth]
summary: "Spec for the saving area of sqlearn's library breadth (overview 3.3): one JSON file holds a pipeline's recipe and, once learned, its learned values with the fingerprint of the data they came from, so a pipeline learned today is trained or applied tomorrow in a new process without learning again; the trained model is saved only on request, by pickle in a file of its own opened only when trusted, and loading imports only modules the user allows."
related: [docs/architecture/overview.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/adr/0024-store-keys-follow-what-a-step-reads.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Library breadth: saving

The fifth area of part 3.3 of [the overview](../architecture/overview.md).
It specifies issues [#20](https://github.com/glaucis/sqlearn/issues/20) (save
learned state to a file) and part 1 of
[#24](https://github.com/glaucis/sqlearn/issues/24) (a pipeline file) together,
as Tomas decided on 2026-11-05: one file format, one round-trip test, one
answer for custom steps and selectors.

Status: written on 2026-11-11 at Tomas's request without a design talk ("skip
questions"); every decision below not quoted from the issues is the spec's
call, listed in section 12. Tomas reviews it before the plan.

## 1. Purpose

Learned values live in the learning store while the program runs (ADR 0014):
a restart empties it and everything is learned again. Tomas's case
(2026-11-11): *a pipeline is prepared and its values learned, there is no time
to train the model today; tomorrow the user comes back and just runs it.*

This area gives sqlearn one file that holds:

1. **The recipe:** the steps, their order and settings, column selectors
   included, and the model by its class and parameters. Loading it gives back
   a pipeline that runs exactly as the original (#24, part 1). It can be shared:
   it holds no data.
2. **What was learned**, when the pipeline was learned or trained: each step's
   learned values, keyed as the store keys them, with the fingerprint of the
   data they came from (#20). Loading it makes `apply` work at once, and a
   later `learn` or `train` on the same, unchanged data learns nothing again.
   On changed data it learns again and says so with a warning, which closes
   ruling R6's gap (#50: a new process prepared an edited table again without a
   warning, as the last fingerprint seen lived only in memory).

The overview's node editor (3.7) is to serialise to "the same form the
library's own pipeline uses": this file's recipe part is that form.

## 2. What it looks like

```python
import sqlearn as sq

pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard(), sq.encode.onehot()])
pipe.learn("customers.parquet")
sq.save(pipe, "customers.sqlearn.json")  # recipe and learned values

# Tomorrow, a new process:
pipe = sq.load("customers.sqlearn.json")
pipe.apply("new_customers.parquet")  # at once: nothing learned again
pipe.learn("customers.parquet")  # unchanged file: nothing learned again

model = sq.Pipeline([*pipe.steps, ("model", sq.Model(LogisticRegression()))])
model.train("customers.parquet", "churned")  # the preparation comes from the file

# A recipe with a model from another library: the module is allowed by name.
sq.load("churn.sqlearn.json", allow=["sklearn"])
```

## 3. The contract (a new ADR, 0047)

- **Two functions, `sq.save(pipe, path)` and `sq.load(path, allow=())`**, as
  `joblib.dump`/`joblib.load` and `skops.io.dump`/`skops.io.load` take an
  object and a path (ADR 0003). No method on `Pipeline`, no `to_json` string
  form for now.
- **One format for both parts.** A pipeline never learned saves its recipe
  alone; a learned or trained one saves the recipe and the learned part.
  `sq.save(pipe, path, learned=False)` saves the recipe alone of a learned
  pipeline, to share it.
- **JSON, never pickle.** Opening the file never runs code from it (section
  7). The one exception is the trained model's own file, written only when
  asked and opened only when trusted (section 8).
  The file is UTF-8, written by the standard library's `json`, indented by
  two spaces, keys in a fixed order, so the same pipeline gives the same bytes
  and a changed value is a readable diff. No dates or times in it except the
  learned data's own fingerprint.
- **Loading is pure:** it reads the file, imports the classes it names when
  allowed, builds the objects and fills the store. It reads no data, opens no
  database and runs no SQL; the fingerprint is compared when a call reads
  data, as the store's key always is (ADR 0021).
- **The trained model is saved only when asked**, in a file of its own beside
  the JSON (section 8). By default a pipeline that ends in a model saves its
  preparation's learned values and the model's recipe.
- **sqlearn never changes what the user asked for on its own (ADR 0046):** a
  file it cannot honour exactly is refused or loaded with a warning in the
  house form, never quietly adjusted.

## 4. The file

```json
{
  "format": "sqlearn.pipeline",
  "format_version": 1,
  "sqlearn": "0.3.0",
  "steps": [
    {
      "name": "impute",
      "class": "sqlearn.preprocessing.impute:Impute",
      "state_version": 1,
      "settings": {"cols": {"$": "selector", "kind": "numeric"}, "method": "median"}
    }
  ],
  "learned": {
    "data": {"kind": "file", "path": "/abs/customers.parquet", "size": 1048576, "mtime_ns": 1762851200000000000, "columns": [["age", "DOUBLE"]]},
    "target": null,
    "columns_out": ["age", "income"],
    "types": [{"age": "DOUBLE"}],
    "steps": [
      {"columns": ["age"], "values": {"median": {"age": 41.0}}, "folds": {}}
    ]
  }
}
```

- **`class`** is `module:qualname`, never a `repr` to evaluate. A step built
  by a group (`sq.impute.median()`) is saved as its class and settings, and
  loads as the same object (`repr` equal, `settings()` equal).
- **`settings`** are `Step.settings()` (and, for a model, the wrapped
  estimator's `get_params(deep=False)` beside `sq.Model`'s own settings:
  `feed`, `rows`, `megabytes`, `epochs`, `shuffle`, `seed`), encoded as in
  section 5. A setting equal to its default is written too: the file says
  everything, so a later change of a default does not change a saved
  pipeline.
- **`learned`** is absent from a recipe. `data` is the fingerprint of the input
  the values came from (section 6); `target` the target column of `learn` or
  `train`; `columns_out`, `types` and `names` (each stage's created columns,
  `Pipeline._names`) what `apply` needs to rebuild its stages with the same
  SQL;
  `steps` one entry per step, in order: the store `Entry`'s `columns`,
  `values` and `folds` (ADR 0038's inner folds of a step learning from the
  target). `Entry.apply_sql` is not saved: it is informational, and `apply`
  builds every stage again from the values.
- **`state_version`** is a new class attribute of `Step` (`ClassVar[int]`,
  default 1). A step's author raises it when the names or meaning of what
  its `learn` returns change. On load, when any step's saved number differs
  from its class's, the whole learned part is dropped and the file loads as a
  recipe, with a `SqlearnWarning` naming each such step: a pipeline stays
  learned in full or not at all, as today (`_commit` runs only when every step
  succeeded). The next `learn` learns everything.
- **`format_version`** is 1. A file of a higher version is refused (`Fix:`
  upgrade sqlearn). A missing field is refused; an unknown field is refused,
  as it would mean the file is from a version that knows something this one
  does not.

## 5. Values in JSON

JSON knows strings, finite numbers, booleans, null, arrays and objects; a
setting or a learned value can be more. Every value is written as plain JSON
when JSON says it exactly, and as a **tagged object** otherwise: an object
whose first key is `"$"`, naming the kind. Every object in the file's values is
tagged, a plain mapping included, so a user's key never collides with a tag.

| value | written as |
|---|---|
| `None`, `bool`, `str` | itself |
| `int` (any size: HUGEINT, UBIGINT) | itself |
| finite `float` | itself, by `repr` (shortest round-trip form: `0.1` reads back as the same double, `-0.0` stays `-0.0`) |
| NaN, `inf`, `-inf` | `{"$": "float", "value": "nan"}` (and `"inf"`, `"-inf"`) |
| `list` | an array |
| `tuple` | `{"$": "tuple", "items": [...]}` |
| `dict` (and a DuckDB STRUCT or MAP) | `{"$": "dict", "items": [[key, value], ...]}`, keys encoded as values |
| `decimal.Decimal` | `{"$": "decimal", "value": "12.50"}` (the text keeps the scale) |
| `datetime.date`, `datetime.datetime`, `datetime.time`, `datetime.timedelta` | `{"$": "date", "value": "<ISO 8601>"}` and so on; a zone kept as its offset |
| `uuid.UUID` | `{"$": "uuid", "value": "..."}` |
| `bytes` | `{"$": "bytes", "base64": "..."}` |
| a selector (`sq.cols(...)`, `sq.cols.numeric()`, `\|`, `&`, `-`, `~`) | `{"$": "selector", ...}` as a tree of its parts |
| a sqlearn object named by its class (an aggregate of `sq.agg`, a fold scheme) | `{"$": "object", "class": "module:qualname", "settings": {...}}` |

- **Floats are exact.** `repr` of a Python float is the shortest text that
  reads back as the same double, and `json` writes it that way; the round-trip
  test (section 10) checks it on values that are hard to round (subnormals,
  `5e-324`, `1.7976931348623157e308`, `0.1 + 0.2`, every learned value of the
  validation's datasets).
- **What cannot be saved is refused at save, not at load:** a function or
  lambda (`sq.Step(learn=lambda x: ...)`), a value with no encoding (any
  object with the default `repr`), a model whose estimator has no
  `get_params`. The error names the step, the setting and the value's type,
  and its `Fix:` says what would save: a step class in an importable module
  in place of a lambda. The file is not written, nor half-written: it is
  written to a temporary file beside it and renamed.
- **A model's estimator settings** (`get_params(deep=False)`): plain values
  and numpy scalars (written as the plain value they equal, numpy never
  imported at load) are saved; a nested estimator (`estimator=`, a
  scikit-learn `Pipeline`, `Stacking`) is saved as `{"$": "estimator",
  "class": ..., "params": {...}}`, recursively, and `allow=` checks every
  nested class before importing any. A callable (`scoring=`, a kernel
  function), a numpy array, a `RandomState` or any other object is refused at
  save, naming the parameter, with `Fix:` set it to a plain value or save the
  model with its own library. This is the spec's call.
- **The encodings are closed:** the build lists every setting type the
  public steps, groups and models take (a test walks every public step's
  `settings()` with its defaults and with each documented choice) and every
  type DuckDB returns for a learned value; each has its row above or is
  added to it in the ADR. A type with no row is refused, never written with
  `str()` (the earlier attempts' `default=str` turned anything into text
  without saying so).

## 6. The data's fingerprint, and what load does with it

The store's key of a step (ADR 0024) is the data's key, the fold, the chain of
steps with their settings, and the columns the step read. The steps' part is
rebuilt from the loaded recipe; the data's part comes from the file. Only
inputs whose key means the same in another process can be saved:

| input | saved as | portable |
|---|---|---|
| file or glob | each file's real path, size, modification time (ns); columns and types | yes |
| table of a DuckDB database file | the file's real path, the table's name, row count, columns and types, storage blocks (#50) | yes |
| pandas or numpy frame | the fingerprint of its values and row order (ADR 0021), columns and types | yes |
| Polars or Arrow table, a relation, a table of an in-memory database | not saved: `{"kind": "unknown"}` | no |

**On load**, sqlearn:

1. builds each step and the model from `class` and `settings`;
2. gives each step its learned values, as `learn` does (`Step._set_learned`,
   then `Step.learned` once), so attributes ending in `_` read as before
   (`pipe["impute"].median_`) and `apply` works at once, on any data with the
   columns and types it learned from (as after `learn`; a column missing or of
   another type is refused as `apply` refuses it today);
3. when the data's kind is portable, puts each step's entry in the store's
   new **index by stable key**, so a `learn`, `train` or search on the same
   unchanged data finds it and learns nothing. The store's own key cannot be
   rebuilt at load: it holds a file's path as the user spelled it and a
   table's connection token, which only one process knows. The store's live
   key stays as it is (ADRs 0021 and 0024 unchanged); `Source.stable` (in
   `_inputs.py` today, used by nothing) becomes the second key. On a miss of
   the live key, the store looks the stable key up, and a hit is filed under
   the live key as well, so any pipeline with the same steps finds it (the
   example of section 2 builds a new pipeline from the loaded steps). This is
   the spec's call.

**The same source** is the same glob pattern or path as the user passed it,
resolved to a real path (the file saves the pattern beside the files it
matched, so a glob that gains or loses a file is a change and warns), or the
same database file and table. A pandas frame has no source identity: an
unchanged frame finds its values, a changed one is new data, learned without a
warning.

**A table with writes not yet checkpointed** when it is saved would get a new
storage fingerprint at the next checkpoint (DuckDB checkpoints on close)
without any edit, and a warning there would be false (ruling R6, #50). So
`sq.save` warns: `Fix: run CHECKPOINT before saving, so the learned values
carry across processes`, and saves that table's fingerprint as kind
`unknown`. sqlearn never checkpoints the user's database itself (ADR 0046).
Block ids are stable across a clean close and reopen with no edit (measured
on #50); the build measures this again for its test.

**At the next `learn` or `train`** (never at `apply` or `predict`, as #50's
ruling), when the input is the same source and its key differs from the saved
one, sqlearn
learns again, as it does today, and warns in the house form:
`customers.parquet changed since the values in customers.sqlearn.json were
learned (its size or modification time differs), so sqlearn learned them
again. Fix: save the pipeline again to keep the new values.` Data that is not
the same source (another file) is simply new data: learned, no warning, as
today.

For an input of kind `unknown`, step 3 is skipped: `apply` works, and the
first `learn` learns again, without a warning. The docs say which inputs
carry their learned values across processes.

A file moved to another machine has another modification time, so its values
are learned again there, with the warning. This errs towards learning again;
a content hash of the file would cost a read of all of it (section 11).

## 7. Loading imports only allowed modules

A `class` field names code to import, and importing a module runs its top
level. A file from someone else must not be able to run any installed module
by naming it.

- **`sqlearn` itself is always allowed.** Every other module's top-level
  package must be named in `allow=`: `sq.load(path, allow=["sklearn"])`.
- **Before importing anything**, `load` reads every `class` in the file; if
  any names a package not allowed, it refuses the whole file, naming each
  package and the step or model that needs it. `Fix:` pass
  `allow=["sklearn"]` if you trust the file.
- **After importing**, a step's class must be a subclass of `sq.Step`, and a
  model's estimator class must have `fit` and `predict` (as `sq.Model`
  checks today); anything else is refused. A class the import cannot find is
  refused, naming the module, with `Fix:` install the package or the user's
  own steps.
- A user's own step class is saved by its import path, as any step: it loads
  where that module is importable and allowed. A class defined in
  `__main__` or inside a function cannot be imported by path and is refused
  at save.

## 8. The trained model, opt-in

A model's trained state belongs to its library and is not JSON: XGBoost,
LightGBM and CatBoost save their own models their own ways, and scikit-learn
relies on pickle. Opening a pickle can run any code its author put in it.
Tomas's ruling (2026-11-11): **saving the trained model is opt-in, by pickle
first, and the design leaves room for other ways later.**

- **By default, the model is not saved.** `sq.save` keeps its recipe; the
  loaded pipeline is learned, not trained, and `predict` refuses until
  `train`, as for any pipeline not trained.
- **`sq.save(pipe, path, model="pickle")`** writes the trained estimator
  (the object `sq.Model` wraps, not the pipeline) with the standard library's
  `pickle` to a file beside the JSON, `<path stem>.model.pickle`. The JSON
  stays pure: it names the model file, its format and its SHA-256, and
  shares as a recipe without it. A pipeline not trained, with `model=`
  given, is refused (there is nothing to save).
- **Loading the model is opt-in as well:** `sq.load(path, trust_model=True)`.
  Without it, a file that names a model file loads learned but not trained,
  and warns: `the trained model in churn.model.pickle was not opened, as
  opening a pickle can run code. Fix: pass trust_model=True if you trust
  the file.` With it, the model file's SHA-256 must match the JSON's (a
  swapped or edited file is refused before it is opened), and the loaded
  object must be of the class the recipe names, whose package `allow=` must
  list, as for any class.
- **Room for more formats:** `model=` names a format from a small registry
  inside sqlearn: each entry saves an estimator to a path, loads it back, and
  says whether loading it can run code. Only `"pickle"` is built now. Later
  entries need no change to the JSON format: a model's library's own file
  (XGBoost's JSON, LightGBM's text, CatBoost's `.cbm`), or skops for
  scikit-learn, which loads without running code. A format that cannot run
  code would load without `trust_model`.
- **No new dependency:** `pickle` and `hashlib` are the standard library.
  A future format whose library is the model's own (XGBoost saving XGBoost)
  adds nothing either; skops would need a written reason (ADR 0005).

## 8a. Not saved
- **The whole store.** `sq.save` writes what one pipeline points to, not every
  entry the process holds; a search's folds already persist with
  `keep_prepared`. A search object is not saved; its best pipeline is a
  `Pipeline` and saves as one.
- **Data.** Never: the file holds values learned from data, such as an
  encoder's categories and a median, which can be sensitive (a category is a
  real value). The docs say so where they say a recipe can be shared:
  `learned=False` for that.

## 9. Errors

Every refusal is a `SqlearnError` in the house form (what, `Why:`, `Fix:`);
every warning a `SqlearnWarning` placed at the user's line.

- Save: a value with no encoding; a class not importable by path; a path whose
  folder does not exist; a pipeline step whose learning failed half-way is
  impossible (learned state is committed only when every step succeeded).
- Load: not a sqlearn file (`format` missing or other); a higher
  `format_version`; a missing or unknown field; a package not allowed; a class
  not found or of the wrong kind; a tagged value of an unknown kind or a
  malformed one (a `"value": "1.2.3"` for a decimal); a settings set the
  class's `__init__` refuses (its own error, with the file and step named).
- Model: `model=` an unknown format; `model=` on a pipeline not trained; a
  model file missing, or whose SHA-256 differs; a loaded model of another
  class than the recipe's.
- Warn at load: a model file not opened for want of `trust_model=True`;
  a step's `state_version` differs (its values dropped);
  the file's `sqlearn` version is newer than the running one (it loads if
  the format is known).

## 10. Tests and validation

- **The round trip, the core test:** for every public step, group shortcut
  and documented setting, with default settings and with each choice,
  `load(save(pipe))` gives a pipeline whose `repr`, `settings()` and
  `apply` SQL text are equal to the original's, and whose `apply` output on
  the validation's datasets is equal value for value (0 ULPs). A test fails
  when a public step has no case, as `check-mirror` fails a module with no
  test.
- **Values:** a property-based test (Hypothesis, test-only dependency) of the
  encoding over nested values of every row of section 5's table: decode of
  encode is equal, type included (a tuple stays a tuple, `-0.0` stays `-0.0`,
  NaN stays NaN), and the bytes are the same for equal values.
- **Learned state across processes:** learn in one subprocess and save; in a
  new subprocess load, then `apply` (nothing learned: `STORE.learns` empty),
  then `learn` on the same file (nothing learned), then touch the file and
  `learn` (learned again, the warning raised once); the same for a glob that
  gains a file, and for a table of a database file edited and checkpointed; a
  table saved with writes not checkpointed warns at save and learns again in
  the next process without a warning; an unchanged pandas frame learns
  nothing, a changed one learns again without a warning.
- **Imports:** a file naming a package not allowed is refused before any
  import (a test module whose import would record itself proves nothing was
  imported).
- **A target step** (`sq.encode.target`) round-trips its inner folds and
  `predict` after `train` on the loaded pipeline equals the original's.
- **The model, opt-in:** a trained pipeline saved with `model="pickle"` and
  loaded with `trust_model=True` predicts equal values to the original
  without training, for scikit-learn, XGBoost, LightGBM and CatBoost (the
  test group's models); loaded without it, it warns and `predict` refuses;
  a model file changed by one byte is refused before it is opened.
- No new validation runner: saving computes nothing (ADR 0016's pages are
  about numbers); the round-trip results join `validation/tests.json`.

## 11. Done when

- `sq.save` and `sq.load` exist, documented with an example each, refusing in
  the house form as section 9 lists.
- The round-trip test covers every public step; the value test passes; the
  cross-process test shows Tomas's case: learned in one process, applied and
  trained in the next without learning again, and the warning when the data
  changed; a trained pipeline saved with `model="pickle"` predicts in the
  next process without training.
- `Step.state_version` exists and is documented for authors of steps.
- A guide page, "Saving a pipeline", says what is saved, what is not (the
  model, which inputs carry their values), how to share a recipe, and why
  `allow=` exists; ADR 0047 records the contract; `HANDOFF.md` and the
  overview are updated; #20 and part 1 of #24 are closed, part 2 (export as
  code) kept open.

## 12. The spec's calls, for Tomas to check

1. **`sq.save(pipe, path)` / `sq.load(path)`**, not `pipe.save()`: as joblib
   and skops.
2. **Decided by Tomas (2026-11-11): the trained model is saved opt-in by
   pickle** (section 8), in its own file beside the JSON, opened only with
   `trust_model=True` and a matching SHA-256; other formats can be added
   later. The sidecar file, the hash and `trust_model` are the spec's calls.
3. **Loading imports only `sqlearn` and the packages in `allow=`.**
4. **A file's fingerprint is size and modification time**, as the store's
   key: a copied file relearns, with a warning. A content hash is exact but
   reads the whole file.
5. **Polars, Arrow, relations and in-memory tables do not carry learned values
   across processes** (their key is the object or the connection, which a new
   process does not have); `apply` still works after load.
6. **`state_version` per step** rather than refusing a file from another
   sqlearn version: during development the version changes with every commit.
7. **One pipeline per file, not the whole store**; searches keep using
   `keep_prepared`.
8. **Every setting is written, defaults included**, so a later default change
   does not change a saved pipeline.

Settled after the builder check, as the spec's calls:

9. **Loaded values are found by a second key** in the store (the input's
   stable key), beside the live key, which stays as it is.
10. **A table saved with writes not yet checkpointed** warns at save and does
    not carry its values across processes; sqlearn never checkpoints it.
11. **A `state_version` mismatch drops the whole learned part**, never some
    steps: no half-learned pipeline.
12. **A glob saves its pattern**, so gaining or losing a file warns; a
    pandas frame never warns.
13. **A model's nested estimators are saved by class and parameters**, every
    class checked against `allow=`; callables, arrays and random states are
    refused at save.

## 13. Not in this area

Exporting a trained pipeline as standalone code (#24, part 2: it builds on this
file's description of steps); model formats other than pickle (section 8
leaves room for them); saving a search or the
whole store; a size limit and clearing of the store (#23); a content hash of
files; reading the file from a URL (ADR 0006).

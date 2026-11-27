---
type: plan
tags: [saving, loading, models, imports, security, library-breadth]
summary: "Builds #55 under ADR 0048: sq.load imports nothing and builds only steps, models, nested estimators and fold schemes from modules already imported; a pipeline keeps its training record apart from whether its model is trained; pipe.model_ and pipe.use_model, with or without the training data; sq.save writes a trained key and no model file; allow=, trust_model=, model= and the pickle format are removed."
related: [docs/specs/archived/library-saving-the-model.md, docs/adr/archived/0048-the-user-saves-the-model-and-imports-its-packages.md, docs/specs/archived/library-saving.md, docs/plans/archived/2026-11-11-library-saving.md]
---
# Library saving the model: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** the trained model is the user's: they save and open it, and
`pipe.use_model` puts it back; `sq.save` writes only sqlearn's part and
`sq.load` imports nothing.

**Architecture:** the loading rules live in `src/sqlearn/_saving/recipe.py`
(class lookup in `sys.modules`, the kind check) and `files.py` (the file's
keys); the pipeline's state and the two new names live in
`src/sqlearn/_pipeline.py`; the "is this model trained?" rule lives in
`src/sqlearn/_model.py`. `src/sqlearn/_saving/models.py` is deleted.

**Tech Stack:** Python 3.12+, DuckDB 2.0, the standard library (`sys`,
`json`); pytest; scikit-learn, LightGBM, CatBoost and joblib in the test
group only.

**Spec:** `docs/specs/library-saving-the-model.md` (approved by Tomas,
2026-11-11). ADR 0048.

## Global Constraints

- The only runtime dependency is `duckdb` (ADR 0004). sqlearn imports no
  model library and no `joblib`; tests may.
- `sq.load` calls no `importlib.import_module` and no `__import__`: a class
  is found only in `sys.modules`.
- Refusals: `SqlearnError` in the house form (what, `Why:`, `Fix:`);
  warnings: `SqlearnWarning` at the user's line (`sqlearn._errors`).
- sqlearn never changes what the user asked for on its own (ADR 0046).
- The file stays as the saving spec's section 4 lays it out, plus the
  optional key `trained` after `learned`; `format_version` stays 1;
  `_OPTIONAL = ("learned", "trained")`.
- Test names read as sentences in `GLOSSARY.md` terms (recipe, learned
  part, stable key, trained model), through `sq.save`, `sq.load` and
  `Pipeline` unless a task names a private function.
- British English in prose, American spelling in identifiers (ADR 0010).
- Model tests pass `allow_writing_files=False` to CatBoost, so no
  `catboost_info/` folder appears.
- Commits: `feat:`, `test:`, `docs:`, `refactor:`, each naming `#55`; no AI
  attribution.
- Before each commit: `just fmt`, `just check`, `just test`, naming every
  failure. Before the branch is called done: `just verify`, and the docs
  rebuilt clean (`rm -rf docs/reference/generated docs/_build && just
  build-docs`). The `HANDOFF.md` trap: probe every tag (`object`,
  `estimator`, `aggregate`, learned part, `trained`) end to end after the
  change to `_saving`.

## Review Focus

1. A program that imported only the parent package (`import sklearn`) loads
   a file naming `sklearn.linear_model._logistic:LogisticRegression`: it is
   refused (the submodule is not in `sys.modules`), and the `Fix:` names
   the class and `sklearn`, not the private module. Test in Task 1.
2. `use_model(CatBoostClassifier)`, the class instead of an object: refused
   as "a class, not a trained model object", not passed to `isinstance` or
   the trained rule. Test in Task 2.
3. A model trained on other columns than the pipeline prepares: `use_model`
   accepts it (nothing can tell), and `predict` raises the library's own
   error unchanged, not swallowed or rewritten. Test in Task 2.
4. A pipeline given its model with `data=` and then saved: the file holds
   `learned` and `trained`, and loads into a pipeline that `use_model`
   accepts without data. Test in Task 4.
5. A file loaded, then saved again before `use_model`: it keeps `trained`
   (the training record), so the copy still accepts `use_model` without
   data. Test in Task 3.

---

### Task 1: `sq.load` imports nothing and builds only what belongs in a pipeline

**Files:**
- Modify: `src/sqlearn/_saving/recipe.py` (`check_allowed` becomes
  `check_imported`; `import_class`, `build_step`, `build_model`,
  `_import_of` lose `allow`)
- Modify: `src/sqlearn/_saving/files.py` (`load` loses `allow=`)
- Modify: `src/sqlearn/_saving/codec.py` only where it calls the above
- Test: `tests/src/sqlearn/_saving/test_recipe.py`,
  `tests/src/sqlearn/_saving/test_files.py`, and every saving test that
  passes `allow=` (it imports the package instead)

**Interfaces:**
- Produces: `check_imported(paths: Iterable[str]) -> None` (refuses, naming
  every class whose module is not in `sys.modules`);
  `import_class(path: str, kind: Literal["step", "model", "nested",
  "object"], where: str) -> type`; `sq.load(path, *, trust_model=False)`
  (trust_model goes in Task 3).

- [ ] **Step 1: Write the failing tests** in `test_recipe.py`:
  - `test_a_class_whose_module_is_not_imported_is_refused_and_nothing_is_imported`:
    a file naming `tests.src.sqlearn._saving.recorded_import:X` as a step and as
    an estimator, with `sys.modules` cleared of `sqlearn_test_imported` and the
    module: `sq.load` raises `SqlearnError` whose text holds
    `"recorded_import"`, `"is not imported"`, `"Why:"` and
    `"Fix: import X from tests before loading"`; afterwards
    `"sqlearn_test_imported" not in sys.modules`.
  - `test_every_class_not_imported_is_named_at_once`: two classes of two
    modules not imported; the message names both.
  - `test_a_submodule_not_imported_is_refused_with_the_package_named`
    (Review Focus 1): `import sklearn` only (pop
    `sklearn.linear_model._logistic` and `sklearn.linear_model` from a copy
    of `sys.modules` with `monkeypatch.delitem`), a file naming
    `sklearn.linear_model._logistic:LogisticRegression`: refused, the `Fix:`
    reads `import LogisticRegression from sklearn before loading`.
  - `test_a_class_that_is_not_a_step_model_or_estimator_is_refused`:
    `subprocess` imported, a file naming `subprocess:Popen` as a step, as the
    model's estimator, as a nested estimator (a `BaggingClassifier`
    parameter) and as an `object` tag: each refused before anything is
    built (patch `subprocess.Popen.__init__` to record a call; it is never
    called), the message names `subprocess:Popen` and says it is not a step,
    a model or an estimator.
  - `test_a_nested_estimator_is_rebuilt_when_its_module_is_imported`: a
    `BaggingClassifier(estimator=DecisionTreeClassifier(max_depth=2))` model
    saved and loaded with no `allow=`; `repr` equal.

- [ ] **Step 2: Run them to verify they fail**

Run:
```bash
uv run pytest tests/src/sqlearn/_saving/test_recipe.py -k "imported or \
  not_a_step or nested_estimator" -v
```
Expected: FAIL (load still imports, or still asks for `allow=`).

- [ ] **Step 3: Implement the import rule and the kind rule**

  - `check_imported`: for each path, `module, _, qualname =
    path.partition(":")`; missing when `module not in sys.modules`. One
    refusal naming each missing `module:qualname`, `Why: sq.load imports
    nothing, so loading a file can never run code you did not choose to
    run.` and `Fix:` one `import <last part of qualname> from <top-level
    package> before loading` per class, joined by `; `.
  - `import_class`: `found = sys.modules[module]` (the walk by attribute and
    its refusals stay). Kind checks on the class before returning, all
    before any instance is made: `"step"` subclass of `Step`; `"model"` has
    `fit` and `predict`; `"nested"` has `get_params`; `"object"` unchanged
    (callers check the closed lists). Refusal text: `<path> is not a step,
    a model or an estimator` with `Why: a saved pipeline holds only those.`
    and `Fix: check where this file came from.`
  - `_import_of`: the top estimator is `"model"`, every other estimator
    `"nested"`. The rules that no estimator is a class of sqlearn stay.
  - `load`: replace `check_allowed(paths, allow)` by `check_imported(paths)`;
    remove `allow=` and its text check. Delete `check_allowed` and the
    owner-in-allow refusal.

- [ ] **Step 4: Update the existing tests** that pass `allow=`: each imports
  the package at the top of its module or script instead. Tests whose point
  was the `allow=` refusal (`test_files.py` lines 89, 159, 346-352,
  `test_recipe.py` lines 212 and 296) are rewritten to the import rule or,
  where the import rule already covers them, deleted.

- [ ] **Step 5: Run the saving tests**

Run: `uv run pytest tests/src/sqlearn/_saving -q`
Expected: PASS (the model tests still use `trust_model=True` until Task 3).

- [ ] **Step 6: Commit**
      `feat: sq.load imports nothing, builds only what a pipeline holds (#55)`

### Task 2: The training record, `model_` and `use_model(model)`

**Files:**
- Modify: `src/sqlearn/_model.py` (the trained rule)
- Modify: `src/sqlearn/_pipeline.py` (state, `model_`, `use_model`,
  `predict`'s check)
- Test: `tests/src/sqlearn/test__model.py`,
  `tests/src/sqlearn/test__pipeline.py`

**Interfaces:**
- Produces: `is_trained(model: object) -> bool` in `sqlearn._model`;
  `Pipeline._model_trained: bool` (False at build, True after a successful
  `train` or `use_model`, False when a fit fails); the training record is
  `Pipeline._feed is not None` with `Pipeline._categories`;
  `Pipeline.model_` (property) and `Pipeline.use_model(self, model: object,
  data: object = None, target: str | None = None, feed: str | None = None)
  -> Pipeline` (the `data` path comes in Task 4: here `data`, `target` and
  `feed` given raise `NotImplementedError` only until Task 4).

- [ ] **Step 1: Write the failing tests**
  - `test__model.py`, `test_a_model_is_trained_by_its_own_rule`: parametrised
    over `LogisticRegression()`, `make_pipeline(StandardScaler(),
    LogisticRegression())`, `LGBMClassifier(verbose=-1)`,
    `CatBoostClassifier(verbose=0, iterations=5,
    allow_writing_files=False)`: `is_trained` is False before `fit` and True
    after; and True for a CatBoost model reloaded with `load_model`.
  - `test__pipeline.py`:
    - `test_model_is_the_trained_estimator`: after `train`,
      `pipe.model_` is the `LogisticRegression` object itself (`is`), not
      `sq.Model`.
    - `test_model_refuses_before_train` and on a pipeline with no model:
      `SqlearnError` with `"Fix: call train(data, target=...) first"`.
    - `test_use_model_puts_a_trained_model_back`: train pipeline A; build
      the same pipeline B and train it on other data; `B.use_model(A.model_)`
      returns B and `B.predict(data)` equals `A.predict(data)`.
    - one test per refusal of the spec's section 3, each matching its
      `Fix:`: no model step; no training record and no data (`Fix: pass the
      training data, as use_model(model, data=..., target=...), or load the
      file sq.save wrote after train.`); no `fit` or `predict`; another
      class than the recipe's; not trained.
    - `test_use_model_refuses_a_class_instead_of_a_model` (Review Focus 2):
      `use_model(LogisticRegression)` says it is a class and the `Fix:` asks
      for a trained model object.
    - `test_a_model_trained_on_other_columns_fails_in_predict_with_its_own_error`
      (Review Focus 3): a `LogisticRegression` fitted on 5 columns given to a
      pipeline that prepares 3: `use_model` accepts it and `predict` raises the
      `ValueError` scikit-learn raises, unchanged.
    - `test_a_fit_that_fails_leaves_the_model_untrained`: an estimator whose
      `fit` raises; afterwards `pipe.model_` refuses and `predict` refuses.

- [ ] **Step 2: Run them to verify they fail**

Run:
```bash
uv run pytest tests/src/sqlearn/test__model.py \
  tests/src/sqlearn/test__pipeline.py -k "trained or model_ or use_model or \
  fit_that_fails" -v
```
Expected: FAIL (`is_trained`, `model_`, `use_model` do not exist).

- [ ] **Step 3: Implement**
  - `is_trained`: `__sklearn_is_fitted__()` when callable; else
    `is_fitted()` when callable; else any key of `vars(model)` that ends in
    `_` and does not start with `_`. Imports no library.
  - `Pipeline`: `_model_trained` set where `_feed` is set in `_train`, and
    cleared with it in the `except`. `predict` refuses unless
    `_model_trained` and the training record and `_entries` exist; its
    `Fix:` adds `or put a trained model back with use_model(model)`.
  - `model_`: returns the model step's estimator (`self._split()[1].estimator`)
    when `_model_trained`, else refuses.
  - `use_model`, refusals in the spec's order, all before reading data: no
    model step; `data` absent and no training record (or `target`/`feed`
    without `data`); `isinstance(model, type)` (a class); no `fit` or
    `predict`; not `isinstance(model, type(<recipe estimator>))`; not
    `is_trained(model)`. Then set the model step's estimator to `model`
    (the object itself, not a copy), `_model_trained = True`, return
    `self`.

- [ ] **Step 4: Run the tests**

Run:
```bash
uv run pytest tests/src/sqlearn/test__model.py \
  tests/src/sqlearn/test__pipeline.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit** `feat: pipe.model_ and pipe.use_model (#55)`

### Task 3: `sq.save` writes `trained`; the model file and its switches go

**Files:**
- Modify: `src/sqlearn/_saving/files.py` (`save` loses `model=`; `load`
  loses `trust_model=`; `trained` written and read; `model_file`,
  `_MODEL_KEYS`, `_model_format`, `_model_file`, `_open_model`, the pair
  commit for two files removed)
- Delete: `src/sqlearn/_saving/models.py`,
  `tests/src/sqlearn/_saving/recorded_pickle.py`
- Rewrite: `tests/src/sqlearn/_saving/test_models.py` (the user's model,
  across processes); `tests/src/sqlearn/_saving/test_across_processes.py`
  line 165

**Interfaces:**
- Consumes: Task 2's training record, `_model_trained`, `use_model`.
- Produces: the file key `"trained": {"feed": <str>, "categories": <encoded
  dict of str to list of str>}`; `sq.save(pipe, path, *, learned=True)`;
  `sq.load(path)`.

- [ ] **Step 1: Write the failing tests** in `test_models.py` (replacing the
  pickle tests):
  - `test_a_users_model_predicts_after_load_without_training`: for
    `LogisticRegression` and
    `BaggingClassifier(estimator=DecisionTreeClassifier())` (saved with
    `joblib.dump`), LightGBM (`joblib.dump`, as the guide advises) and CatBoost
    (`save_model` to `.cbm`), each in a pipeline with `sq.impute.median()` and
    `sq.encode.onehot()`, plus one CatBoost case with `feed="pandas"` and a raw
    text feature: train, `sq.save`, save the model; in a new subprocess import
    the library, `sq.load`, open the model, `use_model`, `predict`: predictions
    equal and `STORE.learns == {}`.
  - `test_the_file_holds_the_training_record_and_no_model`: the saved JSON
    has `trained` with `feed` and `categories`, no `model_file`, and no file
    other than the JSON appears in the folder.
  - `test_a_loaded_pipeline_does_not_predict_until_its_model_is_back`:
    `predict` refuses with `use_model` in the `Fix:`.
  - `test_a_loaded_pipeline_saved_again_keeps_its_training_record`
    (Review Focus 5): load, `sq.save` to a copy, load the copy,
    `use_model` with no data succeeds.
  - `test_a_damaged_trained_key_is_refused`: `trained` with no `learned`; a
    last step that is not a model; a `feed` not in `FEEDS`; categories not
    lists of text: each refused as damaged.
  - `test_a_changed_state_version_drops_the_training_record`: as the learned
    part is dropped, `use_model` without data then refuses.
  - `test_the_old_switches_are_gone`: `sq.save(..., model="pickle")`,
    `sq.load(..., allow=["sklearn"])`, `sq.load(..., trust_model=True)` each
    raise `TypeError`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/src/sqlearn/_saving/test_models.py -v`
Expected: FAIL (no `trained` key; `model=` still accepted).

- [ ] **Step 3: Implement** in `files.py`: `save` writes `trained` after
  `learned` when `learned` and `pipe._feed is not None`, categories through
  `encode` as the model record did; `load` reads it after the learned part
  is restored (and only then: dropped with it on a `state_version`
  mismatch), checks its shape as `_model_file` checked feed and categories,
  and sets `pipe._feed`, `pipe._categories`; the model step keeps the
  untrained estimator from the recipe and `_model_trained` stays False.
  Delete what the Files block lists; `save` writes one file again
  (`os.replace` of one temporary).

- [ ] **Step 4: Run the saving tests and probe every tag**

Run:
`uv run pytest tests/src/sqlearn/_saving tests/src/sqlearn/test__pipeline.py -q`
Expected: PASS. Then, by hand in a scratch script, a file naming
`subprocess:Popen` under each tag (`object`, `estimator`, nested estimator,
`aggregate`, the learned part, `trained` categories): every one refused before
anything is built.

- [ ] **Step 5: Commit**
      `feat: sq.save writes the training record, never the model (#55)`

### Task 4: `use_model` with the training data

**Files:**
- Modify: `src/sqlearn/_pipeline.py` (`use_model`'s data path; `_train`
  gains a way to skip the fit)
- Test: `tests/src/sqlearn/test__pipeline.py`,
  `tests/src/sqlearn/_saving/test_models.py`

**Interfaces:**
- Consumes: Task 2's `use_model` refusals; `_train(self, source, target,
  feed)`.
- Produces: `_train(self, source: Source, target: str, feed: str, *,
  model: object | None = None) -> Pipeline`: with `model` given, everything
  `train` does except the fit, then the model step's estimator is `model`.

- [ ] **Step 1: Write the failing tests**
  - `test__pipeline.py`:
    - `test_use_model_with_the_data_makes_the_training_record_train_would`:
      for `feed="pandas"` with two text features and for `feed="numpy"`:
      pipeline A trained; pipeline B built the same, `B.use_model(A.model_,
      data=..., target=...)`; `B._feed == A._feed`, `B._categories ==
      A._categories` (order included), `B.predict(data) ==
      A.predict(data)`.
    - `test_use_model_with_data_already_learned_learns_nothing_again`: after
      A's `train`, B's `use_model` with the same data: `STORE.learns` for
      the steps is empty.
    - `test_use_model_with_data_does_not_fit_the_model`: a model whose `fit`
      raises, already trained by hand (fitted before its `fit` is patched):
      `use_model(..., data=..., target=...)` succeeds.
    - `test_use_model_refuses_target_or_feed_without_data` and
      `test_use_model_refuses_data_without_target`.
    - `test_use_model_refuses_what_train_refuses`: a target not a column.
  - `test_models.py`:
    - `test_a_users_model_predicts_with_the_data_and_no_file`: in a new
      subprocess, the pipeline built in code, the CatBoost model opened,
      `use_model(model, data="customers.parquet", target="y")`, `predict`:
      equal to the original's.
    - `test_a_pipeline_given_its_model_with_data_saves_and_loads`
      (Review Focus 4): then `sq.save`, `sq.load`, `use_model` without
      data: predictions equal.

- [ ] **Step 2: Run them to verify they fail**

Run:
```bash
uv run pytest tests/src/sqlearn/test__pipeline.py \
  tests/src/sqlearn/_saving/test_models.py -k "with_data or with_the_data or \
  without_data or train_refuses" -v
```
Expected: FAIL (`NotImplementedError` from Task 2).

- [ ] **Step 3: Implement** `use_model`'s data path: after the model checks,
  `feed = model step's feed if feed is None else feed`, `check_feed(feed)`,
  then `self._train(read(data, learning=True), target, feed, model=model)`.
  In `_train`, with `model` given: the categories are those `train` would
  make (read them as the non-stream path's `fetch` does; the stream path's
  are `{}` as at `train`), the fit is skipped, the estimator set to
  `model`, and `_model_trained` set as after a fit. Reading every feature
  through `fetch` to get the categories is acceptable; a query of the text
  features alone is better if it gives the same order, which the test
  above checks.

- [ ] **Step 4: Run the tests**

Run:
`uv run pytest tests/src/sqlearn/test__pipeline.py tests/src/sqlearn/_saving -q`
Expected: PASS.

- [ ] **Step 5: Commit**
      `feat: use_model rebuilds sqlearn's part from the training data (#55)`

### Task 5: The guide, the docs and the issue

**Files:**
- Rewrite: `docs/guide/saving-a-pipeline.md`
- Modify: docstrings of `sq.save`, `sq.load`, `Pipeline.model_`,
  `Pipeline.use_model` (one runnable example each, doctested by the docs
  build); `docs/specs/library-saving.md` (a dated note at its top pointing
  to the new spec, as its other notes do); `docs/architecture/overview.md`
  (the saving area's line); `HANDOFF.md`; `validation/tests.json` (tests
  added)

- [ ] **Step 1: Rewrite the guide** around the spec's section 8: the four
  cases (no saving; both parts; a new process, with and without the JSON;
  a recipe trained again), what each model library offers (CatBoost
  `save_model`/`load_model`; XGBoost `save_model`/`load_model` on its
  scikit-learn class; LightGBM: use `joblib`, as its own text file reloads
  as a `Booster`; scikit-learn: `joblib` for your own files, `skops` for
  others), the import rule and the kind rule with the `subprocess.Popen`
  example, and "pass the same training data" for `use_model` with `data=`.
  No mention of `allow=`, `trust_model=` or `model=`.

- [ ] **Step 2: Check nothing still names the old switches**

Run:
```bash
grep -rnE "trust_model|allow=|model=\"pickle\"|model_file|FORMATS" src tests \
  docs/guide docs/reference --include=*.py --include=*.md
```
Expected: no line (the specs, plans and ADRs keep their history).

- [ ] **Step 3: Run every check**

Run: `just fmt && just check && just test`, then `just verify` and
`rm -rf docs/reference/generated docs/_build && just build-docs`.
Expected: all pass; discard `validation/**/*.results.json` diffs, commit
`validation/tests.json`.

- [ ] **Step 4: Update `HANDOFF.md`** (#55 to "Just finished") **and commit**
  `docs: saving the model is the user's (#55)` with `Closes #55` in the
  body. Close #55 with a summary comment (what changed, the spec's calls,
  any finding left), and set its board card to Done.

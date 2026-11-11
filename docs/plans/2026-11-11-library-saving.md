---
type: plan
tags: [saving, serialisation, json, learned-state, store, pickle, library-breadth]
summary: "Builds the saving area: sq.save and sq.load over one JSON file holding a pipeline's recipe and learned values with their data's fingerprint, a second store key so loaded values are found in a new process, the changed-data warning, and the trained model opt-in by pickle in a file of its own."
related: [docs/specs/library-saving.md, docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/adr/0024-store-keys-follow-what-a-step-reads.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Library saving: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sq.save(pipe, path)` and `sq.load(path)`: a pipeline learned in
one process is applied, learned and trained in the next without learning
again, and a trained model travels with it when the user asks.

**Architecture:** A private package `src/sqlearn/_saving/`: `codec.py`
(values to JSON and back), `recipe.py` (steps, selectors and models by class
path, the `allow=` check), `learned.py` (the pipeline's learned state and
its data's fingerprint), `models.py` (the model formats, pickle first),
`files.py` (`save` and `load`, the file's layout). The store gains a second
index by the input's stable key; `Source` gains its origin; `Pipeline`
keeps what saving needs from its last learn.

**Tech Stack:** Python 3.12+, DuckDB 2.0, the standard library's `json`,
`pickle`, `hashlib`, `importlib`; pytest; Hypothesis (test group only).

**Spec:** `docs/specs/library-saving.md` (approved by Tomas, 2026-11-11).

## Global Constraints

- The only runtime dependency is `duckdb` (ADR 0004); `json`, `pickle`,
  `hashlib`, `importlib`, `base64`, `tempfile` are the standard library.
  Hypothesis joins the `test` group only: `uv add --group test hypothesis`.
- Nothing needs the network (ADR 0006); `load` reads one local file (and
  the model file beside it), runs no SQL and opens no database.
- The JSON file is never pickle. The trained model is written only with
  `model="pickle"`, to its own file, and opened only with
  `trust_model=True` and a matching SHA-256.
- `load` imports only `sqlearn` and the top-level packages in `allow=`, and
  checks every class the file names before importing any.
- Refusals: `SqlearnError` in the house form (what, `Why:`, `Fix:`);
  warnings: `SqlearnWarning` placed at the user's line (`sqlearn._errors`).
- sqlearn never changes what the user asked for on its own (ADR 0046): it
  never checkpoints the user's database, never drops a setting it cannot
  save; it refuses or warns.
- The file: UTF-8, `json.dumps(..., indent=2, ensure_ascii=False,
  allow_nan=False)`, keys in the order the spec's section 4 gives, the same
  bytes for the same pipeline; written to a temporary file in the same
  folder and renamed (`os.replace`).
- Test names read as sentences (`test_<behaviour>`), in `GLOSSARY.md`
  terms, through `sq.save`/`sq.load` unless a task names a private function.
- British English in prose, American spelling in identifiers (ADR 0010).
- Every new module gets its mirrored test module (`just check-mirror`).
- Commits: `feat: ...`, `test: ...`, `docs: ...`; no AI attribution.
- Before each commit: `just fmt`, `just check`, `just test`, naming every
  failure. Before the branch is called done: `just verify`, and the docs
  rebuilt clean (`rm -rf docs/reference/generated docs/_build && just
  build-docs`).

## Review Focus

1. **A float that does not come back bit for bit.** `5e-324`,
   `1.7976931348623157e308`, `-0.0`, `0.1 + 0.2`, NaN with its sign lost.
   Task 1's property test compares with `math.copysign` and `struct.pack`,
   not `==`.
2. **A file from someone else that imports a module by naming it.** A class
   path `os:system` or `antigravity:x`. Task 2 tests that the refusal comes
   before any import (a test module that records its own import).
3. **A relative path learned, then loaded from another working directory.**
   `learn("customers.parquet")` in `/a`, `load` and `learn` in `/a` again
   finds the values; in `/b` it is another file. Task 5 tests both.
4. **A file written half-way.** The disk fills or a value cannot be
   encoded after some steps were written: the old file stays as it was.
   Task 3 tests a refusal on the last step leaves a prior file unchanged.
5. **A model file swapped for another pickle.** Task 6 tests a one-byte
   change is refused before `pickle.loads` runs (a pickle whose loading
   would record itself).

---

### Task 1: Values to JSON and back, and ADR 0047

**Files:**

- Create: `src/sqlearn/_saving/__init__.py` (empty docstring module),
  `src/sqlearn/_saving/codec.py`
- Create: `tests/src/sqlearn/_saving/test_codec.py`
- Modify: `pyproject.toml`, `uv.lock` (`uv add --group test hypothesis`)
- Create: `docs/adr/0047-a-pipeline-saves-as-json.md` (the spec's sections 3,
  5, 7 and 8 as a decision: `sq.save`/`sq.load`, JSON, the tags, `allow=`,
  the stable key as a second store key, the model opt-in by pickle in its
  own file with room for other formats), listed in `docs/adr/index.md`

**Interfaces (produces):**

- `encode(value: object, where: str) -> object`: a JSON-ready value per the
  spec's section 5 table. `where` names the place for errors, as
  `"impute (step 1), setting 'cols'"`. Floats: finite as themselves; NaN,
  `inf`, `-inf` as `{"$": "float", "value": "nan" | "inf" | "-inf"}`.
  Tuples, dicts, decimals, dates, datetimes, times, timedeltas, UUIDs,
  bytes: the tags of the table (`"$"` first). Selectors:
  `{"$": "selector", "kind": "cols", "names": [...]}`,
  `{"$": "selector", "kind": "<label>"}` for `_Kind`,
  `{"$": "selector", "kind": "or" | "and" | "sub", "left": ..., "right": ...}`,
  `{"$": "selector", "kind": "not", "operand": ...}`. A sqlearn object
  (an aggregate of `sq.agg`, a fold scheme) as
  `{"$": "object", "class": "module:qualname", "settings": {...}}` from its
  `settings()` or `__init__` parameters. Anything else (a function, an object
  with the default `repr`) raises `SqlearnError` naming `where` and the type.
- `decode(data: object, where: str, resolve: Callable[[str], type]) -> object`:
  the inverse; `resolve` imports a class path (Task 2 passes its checked
  importer). A tag of an unknown kind or a malformed value raises
  `SqlearnError` naming `where`.
- `class_paths(data: object) -> set[str]`: every `"class"` inside tagged
  objects and estimators, nested, for the `allow=` check before any import.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_value_comes_back_equal_and_of_its_type`: a Hypothesis strategy
    over nested lists, tuples and dicts of `None`, bools, ints (up to
    `2**127`), floats (NaN and infinities included), strings, `Decimal`
    (finite), dates, datetimes (naive and with `timezone(timedelta(hours=2))`),
    times, timedeltas, UUIDs and bytes; `decode(json.loads(json.dumps(encode(v),
    allow_nan=False)), ...)` equals `v`, compared by a helper that checks
    `type(a) is type(b)` at every level and floats by
    `struct.pack("<d", a) == struct.pack("<d", b)` (NaN by `math.isnan`).
  - `test_floats_that_are_hard_to_round_come_back_exactly`: `5e-324`,
    `1.7976931348623157e308`, `-0.0`, `0.1 + 0.2`, `2.0**-1074 * 3` by
    `struct.pack`.
  - `test_equal_values_give_the_same_bytes`: `json.dumps(encode(v))` of two
    equal values built separately gives equal text; a dict keeps its
    insertion order (`{"b": 1, "a": 2}` comes back with `b` first).
  - `test_selectors_come_back_as_they_were`: `repr` equal after the round
    trip for `sq.cols("a", "b")`, `sq.cols.numeric()`,
    `(sq.cols.numeric() - sq.cols("id")) | ~sq.cols.string()`.
  - `test_a_function_is_refused_naming_where_it_was`: `encode(lambda x: x,
    "custom (step 2), setting 'learn'")` raises `SqlearnError` whose message
    holds `custom (step 2)`, `'learn'`, `function` and `Fix:`.
  - `test_an_unknown_tag_is_refused`: `decode({"$": "complex", "value": "1j"},
    ...)` and `decode({"$": "decimal", "value": "1.2.3"}, ...)` raise
    `SqlearnError`.
  - `test_class_paths_finds_nested_classes`: on an encoded
    `{"$": "estimator", "class": "a:B", "params": {"estimator": {"$":
    "estimator", "class": "c:D", "params": {}}}}` it returns `{"a:B", "c:D"}`.
- [ ] **Step 2: Run them to see them fail**: `uv run pytest
  tests/src/sqlearn/_saving/test_codec.py -q`: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3: Implement `encode`, `decode`, `class_paths`** in
  `src/sqlearn/_saving/codec.py`. Floats go through `json`'s own `repr`;
  `Decimal` as `str(d)`; dates and times by `isoformat()` and
  `fromisoformat`; timedelta as `{"$": "timedelta", "days": d, "seconds": s,
  "microseconds": us}`; bytes by `base64.b64encode(...).decode("ascii")`.
  Estimators (`"$": "estimator"`) are decoded by `resolve` too; Task 2 writes
  them.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Write ADR 0047** and list it; `just fmt`, `just check`.
- [ ] **Step 6: Commit**: `feat: encode saved values as JSON and back`.

### Task 2: Steps and models as records, and the `allow=` check

**Files:**

- Create: `src/sqlearn/_saving/recipe.py`
- Create: `tests/src/sqlearn/_saving/test_recipe.py`, and
  `tests/src/sqlearn/_saving/recorded_import.py` (a module that records its
  own import: its top level sets `sys.modules["sqlearn_test_imported"] =
  True`, so a test can assert it was never imported)
- Modify: `src/sqlearn/_step.py` (`state_version: ClassVar[int] = 1` on
  `Step`, documented under Attributes: "raise it when the names or meaning
  of what `learn` returns change; a saved pipeline then loads as a recipe")

**Interfaces:**

- Consumes: `encode`, `decode`, `class_paths` (Task 1).
- Produces:
  - `class_path(cls: type, where: str) -> str`:
    `f"{cls.__module__}:{cls.__qualname__}"`; refuses a class of `__main__` or
    with `<locals>` in its qualname (`Fix:` define the step in an importable
    module).
  - `check_allowed(paths: Iterable[str], allow: Collection[str]) -> None`:
    each path's top-level package must be `sqlearn` or in `allow`; else one
    `SqlearnError` naming every package not allowed, sorted, and
    `Fix: pass allow=['sklearn'] if you trust the file`. Imports nothing.
  - `import_class(path: str, kind: Literal["step", "model", "object"],
    where: str) -> type`: `importlib.import_module` then `getattr` by
    qualname parts; a `step` must subclass `Step`, a `model` must have `fit`
    and `predict`; a missing module or attribute is refused (`Fix:` install
    the package).
  - `step_record(name: str, step: Step, position: int) -> dict[str, object]`:
    `{"name", "class", "state_version", "settings"}`, settings from
    `step.settings()`, every one written (defaults too), in `settings()` order.
  - `model_record(model: Model, position: int) -> dict[str, object]`:
    `{"name", "class": class_path(sq.Model), "settings": {feed, rows,
    megabytes, epochs, shuffle, seed}, "estimator": {"$": "estimator",
    "class": ..., "params": ...}}` from `get_params(deep=False)`. Params:
    plain values; numpy scalars as `.item()` (detected by
    `type(v).__module__ == "numpy"` and `hasattr(v, "item")` with
    `v.ndim == 0`, so numpy is never imported); a nested estimator (has
    `get_params`) recursively as `{"$": "estimator", ...}`; anything else
    refused naming the parameter (`Fix:` set it to a plain value, or save the
    model with its own library).
  - `build_step(record: Mapping[str, object], where: str) -> Step` and
    `build_model(record: Mapping[str, object], where: str) -> Model`: the
    inverse, through `import_class` and `decode`; the class's own `__init__`
    errors pass through with `where` prefixed.

- [ ] **Step 1: Write the failing tests**:
  - `test_every_public_step_round_trips_as_a_record`: for every shortcut of
    every group in `sq` (`sq.impute`, `sq.scale`, `sq.encode`, `sq.bin`,
    `sq.features`, `sq.transform`: each name in `dir(group)` that is callable
    and returns a `Step` with no arguments), with default settings,
    `build_step(step_record("s", step, 1), "s")` has `repr` and `settings()`
    equal to the original's; and a second list `DOCUMENTED_CHOICES` (one
    entry per documented non-default setting value in each step's docstring:
    the builder fills it while writing the test, one line each) does the
    same. The test fails when a group gains a shortcut with no default case.
  - `test_a_model_and_its_nested_estimators_round_trip`:
    `sq.Model(BaggingClassifier(LogisticRegression(C=0.5)), feed="pandas")`
    rebuilt with `allow=["sklearn"]` has equal `get_params(deep=True)` and
    equal `sq.Model` settings; a `np.float64(0.5)` parameter comes back as
    the float `0.5`.
  - `test_a_callable_parameter_is_refused`:
    `SVC(kernel=lambda a, b: a @ b.T)` raises `SqlearnError` naming `kernel`.
  - `test_a_package_not_allowed_is_refused_before_any_import`:
    `check_allowed(paths, ())` with `paths` the set of
    `"tests.src.sqlearn._saving.recorded_import:X"` and `"os:system"`
    raises, the message names `os` and `tests`, and
    `"sqlearn_test_imported" not in sys.modules` afterwards.
  - `test_a_step_class_from_main_is_refused`: a `Step` subclass with
    `__module__ = "__main__"` raises at `class_path`.
  - `test_a_class_of_the_wrong_kind_is_refused`:
    `import_class("collections:OrderedDict", "step", ...)` raises (`allow`
    checked separately).
- [ ] **Step 2: Run them to see them fail**: `uv run pytest
  tests/src/sqlearn/_saving/test_recipe.py -q`.
- [ ] **Step 3: Add `Step.state_version`; implement the five functions** in
  `src/sqlearn/_saving/recipe.py`.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Commit**: `feat: describe steps and models as records`.

### Task 3: `sq.save` and `sq.load` for a recipe

**Files:**

- Create: `src/sqlearn/_saving/files.py`
- Create: `tests/src/sqlearn/_saving/test_files.py`
- Modify: `src/sqlearn/__init__.py` (`from sqlearn._saving.files import
  load, save`; `__all__` gains `"load"`, `"save"`)

**Interfaces:**

- Consumes: Task 2's records and `check_allowed`; Task 1's `class_paths`.
- Produces:
  - `save(pipe: Pipeline, path: str | os.PathLike[str], *, learned: bool =
    True, model: str | None = None) -> None` (Task 4 fills `learned`, Task 6
    `model`; here a learned pipeline still saves its recipe only).
  - `load(path: str | os.PathLike[str], *, allow: Sequence[str] = (),
    trust_model: bool = False) -> Pipeline`.
  - `FORMAT = "sqlearn.pipeline"`, `FORMAT_VERSION = 1`. Top-level keys, in
    order: `format`, `format_version`, `sqlearn` (`sqlearn.__version__`),
    `steps` (the step records, then the model record last when the pipeline
    ends in a model, with `"kind": "step" | "model"` after `name`),
    `learned` (Task 4), `model_file` (Task 6). Unknown or missing keys and a
    higher `format_version` are refused; a newer `sqlearn` with a known
    format warns.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_recipe_loads_as_the_same_pipeline`: a pipeline of
    `sq.impute.median()`, `sq.scale.standard(cols=sq.cols.numeric() -
    sq.cols("id"))`, `sq.encode.onehot()` saved and loaded: `repr(loaded) ==
    repr(pipe)`, step names equal, and `loaded.learn(df).apply(df)` equals
    `pipe.learn(df).apply(df)` (the same frame).
  - `test_the_same_pipeline_gives_the_same_bytes`: saving twice gives equal
    file bytes; the first line is `{` and the file ends in a newline.
  - `test_a_model_needs_its_package_allowed`: a pipeline ending in
    `sq.Model(LogisticRegression())` loads with `allow=["sklearn"]` and is
    refused without, the message holding `sklearn` and `allow=`.
  - `test_a_refused_save_leaves_the_old_file_as_it_was` (Review Focus 4):
    save a good pipeline, then a pipeline whose last step has a lambda
    `learn=` to the same path: refused, and the file's bytes are the first
    save's; no temporary file is left in the folder.
  - `test_a_file_from_a_later_format_is_refused`: `format_version: 2` refused
    with `Fix:` upgrade sqlearn; a missing `steps`, an extra key `"x"`, and
    `"format": "other"` each refused.
  - `test_a_path_whose_folder_does_not_exist_is_refused`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `save` and `load`** in
  `src/sqlearn/_saving/files.py`, each with a numpydoc docstring and an
  example (doctests run under `just verify`). `load` reads the JSON, runs
  `check_allowed(class_paths(...) | record classes, allow)` before building
  anything, then builds the steps and the model in order.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Commit**: `feat: save a pipeline's recipe to JSON and load it`.

### Task 4: The learned part

**Files:**

- Create: `src/sqlearn/_saving/learned.py`
- Create: `tests/src/sqlearn/_saving/test_learned.py`
- Modify: `src/sqlearn/_pipeline.py`: `_commit` takes `source: Source` and
  `depends_on: list[frozenset[int]]` and keeps `self._depends_on` (sorted
  lists) and `self._source = (source.origin, source.stable)`; `learn` and
  `_train` pass them (`the_plan.depends_on`). `__init__` sets both to
  `None`. The search's final training goes through `_train`, so it keeps
  them too.
- Modify: `src/sqlearn/_saving/files.py` (write and read `learned`)
- Modify: `src/sqlearn/_inputs.py`: `Source` gains `origin: tuple | None =
  None` (a field with a default, after `stable`): a file or glob
  `("file", os.path.realpath(os.path.dirname(pattern) or "."),
  os.path.basename(pattern))`; a table of a database file `("table", real
  file path, table name)`; anything else None. A frame's `stable` stays its
  key (already portable). Task 5 reads it; its unit test goes in
  `tests/src/sqlearn/test__inputs.py` here.

**Interfaces:**

- Consumes: `Pipeline._entries`, `_types`, `_names`, `_columns_out`,
  `_target`, `_depends_on`, `_source`; `encode`/`decode`; `Entry`.
- Produces:
  - `learned_record(pipe: Pipeline) -> dict[str, object] | None`: None for
    a pipeline not learned. Keys in order: `data` (Task 5 fills it; here
    `{"kind": "unknown"}`), `target`, `columns_out`, `types` (each
    `dict[str, str]` by `str(DuckDBPyType)`), `names`, `depends_on`,
    `steps` (per step `{"columns", "values", "folds"}`, values and folds
    through `encode`).
  - `restore_learned(pipe: Pipeline, record: Mapping[str, object], where:
    str) -> None`: decodes, rebuilds `Entry(values, columns, "", folds)`
    (empty `apply_sql`), types with `duckdb.sqltype(text)`, then calls
    `pipe._commit`'s state-setting part (split out of `_commit` as
    `_restore(entries, types, names, columns_out, target, depends_on,
    source)` so `Step._set_learned` and `Step.learned` run once each, as
    after `learn`).
  - On load, when any record's `state_version` differs from its class's,
    the learned part is skipped and a `SqlearnWarning` names each step and
    both numbers.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_loaded_pipeline_applies_without_learning`: learn
    `sq.impute.median()`, `sq.scale.standard()`, `sq.encode.onehot()`,
    `sq.encode.target("city")` (with a target) on a frame; save; clear the
    store (`sq.store.clear()`); load: `STORE.learns` stays empty through
    `loaded.apply(df)`, whose SQL text (`loaded.runs_[0].statements[0]`)
    equals the original's and whose rows equal value for value.
  - `test_learned_values_read_as_attributes_after_load`:
    `loaded["impute"].median_ == pipe["impute"].median_`.
  - `test_a_pipeline_saved_without_its_learned_part_loads_unlearned`:
    `save(pipe, p, learned=False)`; `load(p).apply(df)` raises "has not
    learned yet".
  - `test_a_changed_state_version_loads_the_recipe_and_warns`: a test step
    class with `state_version = 1`, saved; its class attribute set to 2
    (monkeypatch); load warns naming the step and `1` and `2`, and the
    pipeline has not learned.
  - `test_a_learned_value_of_every_type_round_trips`: a custom step in the
    test module learning `min` of a DATE, a TIMESTAMP WITH TIME ZONE, a
    DECIMAL(10, 2), a BLOB, a UUID and a list of VARCHAR; after load, `apply`
    SQL text equal.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `learned_record`, `restore_learned`, the
  `_commit`/`_restore` split and the file's `learned` key.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Commit**: `feat: save and load what a pipeline learned`.

### Task 5: The data's fingerprint, the second store key and the warning

**Files:**

- Modify: `src/sqlearn/_store.py`: `Store` gains `_stable: dict[StepKey,
  Entry]` and `_saved: dict[tuple, tuple[DataKey, str]]`;
  `put_stable(key: StepKey, entry: Entry) -> None` (no learn counted);
  `get(key: StepKey, stable: DataKey | None = None) -> Entry | None`: on a
  miss of `key`, looks up `(stable, *key[1:])` in `_stable` and, on a hit,
  files it under `key` too; `remember_saved(origin: tuple, stable: DataKey,
  file: str) -> None`; `changed_since_saved(origin: tuple | None, stable:
  DataKey | None) -> str | None`: the saved file's path when the origin is
  remembered and the stable key differs, forgetting it (warn once). `clear`
  clears both.
- Modify: `src/sqlearn/_pipeline.py`: `_learn_run` calls
  `STORE.get(keys[i], stable=source.stable)` when `fold is None`; `learn`
  and `_train` call `STORE.changed_since_saved(source.origin,
  source.stable)` after `read(data, learning=True)` and warn with the
  spec's section 6 message (`<data> changed since the values in <file>
  were learned (...), so sqlearn learned them again. Fix: save the pipeline
  again to keep the new values.`), naming size and modification time for a
  file, storage for a table, the files gained or lost for a glob.
- Modify: `src/sqlearn/_saving/learned.py` and `files.py`: `data` holds
  `{"kind": "file", "pattern": ..., "files": [[real path, size, mtime_ns],
  ...], "columns": [[name, type], ...]}`, `{"kind": "table", "file", "table",
  "rows", "columns", "storage"}`, `{"kind": "frame", "rows", "digest",
  "columns"}` or `{"kind": "unknown"}`; `load` rebuilds the stable key
  exactly as `_inputs` builds it, puts each step's entry with
  `put_stable(step_key(stable, None, steps, i, depends_on[i], columns))` and
  calls `remember_saved` for a file or table.
- Modify: `save`: a table whose storage shows writes not yet checkpointed
  (row groups edited or segments not written, `Storage[1]` or `Storage[2]`
  non-empty or non-zero) is saved as `{"kind": "unknown"}` with a
  `SqlearnWarning`: `Fix: run CHECKPOINT before saving, so the learned
  values carry across processes.`
- Create: `tests/src/sqlearn/_saving/test_across_processes.py` (each case
  runs `uv run python -c` scripts through `subprocess.run` with
  `sys.executable`, in `tmp_path`)

**Interfaces:**

- Consumes: Task 4's `learned_record`/`restore_learned`; `step_key`.
- Produces: `Source.origin`; `Store.put_stable`, `Store.get(..., stable=)`,
  `Store.remember_saved`, `Store.changed_since_saved`.

- [ ] **Step 1: Write the failing tests** (each process prints
  `STORE.learns` as JSON for the parent to assert):
  - `test_values_learned_in_one_process_are_found_in_the_next` (Tomas's
    case): process 1 learns from `customers.parquet` and saves; process 2
    loads, applies (learns nothing), learns on the same file (learns
    nothing), then builds `sq.Pipeline([*loaded.steps, ("model",
    sq.Model(LogisticRegression()))])` and trains: only the model trains
    (`STORE.learns` empty).
  - `test_a_changed_file_is_learned_again_with_a_warning`: process 2 rewrites
    the file with other values, then learns: learned again, one warning naming
    the file and the saved JSON; a second learn neither learns nor warns.
  - `test_a_glob_that_gains_a_file_warns`: `data/*.csv`, one file added.
  - `test_a_relative_path_is_found_from_the_same_folder_only` (Review Focus
    3): learn `"customers.parquet"` with `cwd=a`; process 2 with `cwd=a`
    learns nothing; with `cwd=b` holding another `customers.parquet`, learns
    without a warning.
  - `test_a_checkpointed_table_carries_its_values`: a table in
    `data.duckdb`, `CHECKPOINT` before saving; process 2 learns nothing;
    after an `UPDATE` and `CHECKPOINT`, learns again with the warning.
  - `test_a_table_with_pending_writes_warns_at_save`: no `CHECKPOINT` before
    saving: the save warns with `CHECKPOINT` in its `Fix:`; process 2 learns
    again without a warning.
  - `test_a_frame_carries_its_values_and_never_warns`: an equal frame in
    process 2 learns nothing; a changed one learns again, no warning.
  - `test_a_relation_does_not_carry_its_values`: a relation learned and
    saved: `data` is `unknown`; process 2's `apply` works, `learn` learns.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the changes to `_store.py`, `_pipeline.py`,
  `learned.py` and `files.py`; unit tests of
  `Store.get(..., stable=)` and `changed_since_saved` go in
  `tests/src/sqlearn/test__store.py`.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Commit**:
      `feat: find saved values in a new process, and warn when the data changed`.

### Task 6: The trained model, opt-in by pickle

**Files:**

- Create: `src/sqlearn/_saving/models.py`
- Create: `tests/src/sqlearn/_saving/test_models.py`, and
  `tests/src/sqlearn/_saving/recorded_pickle.py` (a class whose
  `__reduce__` makes loading call a function that sets
  `sys.modules["sqlearn_test_unpickled"] = True`)
- Modify: `src/sqlearn/_saving/files.py`

**Interfaces:**

- Consumes: `Pipeline._feed`, `_categories`, `model.estimator` (the fitted
  object `sq.Model` wraps); Task 2's records.
- Produces:
  - `@dataclass(frozen=True) class ModelFormat`: `suffix: str`, `save:
    Callable[[object, Path], None]`, `load: Callable[[Path], object]`,
    `runs_code: bool`.
  - `FORMATS: dict[str, ModelFormat] = {"pickle": ModelFormat(".model.pickle",
    ..., ..., runs_code=True)}`, pickle by `pickle.dump(..., protocol=5)`.
  - The model file: `Path(path).with_suffix(".model.pickle")` (so
    `churn.sqlearn.json` gives `churn.sqlearn.model.pickle`), written to a
    temporary file and renamed, as the JSON.
  - The JSON's last key `model_file`: `{"format": "pickle", "file": <name
    beside the JSON>, "sha256": <hex>, "feed": pipe._feed, "categories":
    encode(pipe._categories)}`, present only with `model=`.
  - `save(..., model="pickle")` on a pipeline not trained, or with an
    unknown format, is refused. `load` with a `model_file` and
    `trust_model=False` warns (the spec's section 8 message) and returns a
    learned, untrained pipeline; with `trust_model=True` it checks the file
    exists and its SHA-256 matches **before** loading it, then that the
    object is an instance of the recipe's estimator class (whose package
    `allow=` already checked), sets `model.estimator`, `pipe._feed`,
    `pipe._categories`.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_trained_model_predicts_after_load_without_training`: for each of
    `LogisticRegression`, `LGBMClassifier`, `CatBoostClassifier(verbose=0)`
    (the `test` group's libraries) and a pipeline with `sq.encode.target`,
    trained, saved with `model="pickle"`, loaded with `trust_model=True,
    allow=[package]` in a new process: `predict` equals the original's
    element for element, and `STORE.learns` is empty.
  - `test_a_model_not_trusted_loads_untrained_with_a_warning`: the warning
    holds `trust_model=True`; `predict` raises "not trained".
  - `test_a_changed_model_file_is_refused_before_it_is_opened` (Review Focus
    5): the model file replaced by a pickle of `recorded_pickle` with the
    JSON's hash left as it was: refused, and
    `"sqlearn_test_unpickled" not in sys.modules`.
  - `test_a_model_file_missing_is_refused` with `trust_model=True`.
  - `test_a_pipeline_not_trained_cannot_save_its_model`, and
    `test_an_unknown_model_format_is_refused` (`model="onnx"`, the message
    listing `pickle`).
  - `test_a_model_cannot_be_saved_without_the_learned_part`: `save(pipe, p,
    model="pickle", learned=False)` is refused, as the model was trained on
    the prepared data and predicts only through it; the `Fix:` says to drop
    `learned=False` or `model=`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `models.py` and the `model=`/`trust_model=`
  paths in `files.py`.
- [ ] **Step 4: Run them to see them pass**, then `just test`.
- [ ] **Step 5: Commit**: `feat: save the trained model by pickle when asked`.

### Task 7: The guide, the docs and the issues

**Files:**

- Create: `docs/guide/saving-a-pipeline.md` (frontmatter as the other guide
  pages), listed in `docs/guide/index.md`'s toctree after
  `inputs-and-the-store`: what is saved (recipe, learned values, the data's
  fingerprint), what is not (the model unless asked, data), which inputs carry
  their values across processes (the spec's section 6 table), the changed-data
  warning, `CHECKPOINT` before saving a table, sharing a recipe with
  `learned=False` (and that learned values such as categories are real
  values), `allow=` and why, `model="pickle"` and `trust_model=True` and why,
  `Step.state_version` for authors of steps.
- Modify: `docs/guide/inputs-and-the-store.md` (a paragraph and a link: values
  survive a restart only through `sq.save`), `docs/guide/writing-a-step.md`
  (`state_version`), `docs/architecture/overview.md` (3.3's areas: saving
  built), `CLAUDE.md` (the "Done" sentence gains the fifth area: spec, plan,
  ADR 0047, summary issue), `HANDOFF.md` (Just finished), `GLOSSARY.md`
  (*recipe*, *learned part*, *stable key*, *model file*).
- GitHub: close #20 and part 1 of #24 with a comment each naming the commits;
  keep #24 open for part 2 (retitle it "Export a trained pipeline as
  standalone code"); open a summary issue for the area, as #45 for datasets,
  with the calls of the spec's section 12 and anything deferred; file an issue
  for model formats other than pickle (section 8's registry).

- [ ] **Step 1: Write the pages and edits above.**
- [ ] **Step 2: Rebuild the docs clean**: `rm -rf docs/reference/generated
  docs/_build && just build-docs`: no warnings; `sq.save` and `sq.load`
  appear in the reference.
- [ ] **Step 3: `just verify`**: passes; commit `validation/tests.json`
  (tests were added), discard ULP-only diffs in `*.results.json` (ADR 0043).
- [ ] **Step 4: Commit**: `docs: saving a pipeline`.
- [ ] **Step 5: Update the issues and the board** (github-pm).

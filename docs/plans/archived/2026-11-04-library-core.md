---
type: task
tags: [library-core, pipeline, steps, learn, apply, search, validation]
summary: "Implementation plan for sqlearn's library core (overview 3.2): the step contract, run planner, compositor, learning store, selectors, pipeline, models, search, metric, validation results and docs, in 17 tasks."
related: [docs/specs/archived/library-core.md, docs/architecture/overview.md, docs/adr/archived/0018-runs-follow-the-chains-between-steps.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/archived/0024-store-keys-follow-what-a-step-reads.md, docs/adr/0025-results-stored-as-data-in-mirrored-folders.md]
---
# Library Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sqlearn's library core and prove it with the slice in spec §2:
four preparation steps chained into as few DuckDB queries as their
dependencies allow, a learning store, a grid search over folds handing numpy
to scikit-learn, accuracy in SQL, and every result stored as data.

**Architecture:** Steps build DuckDB expression objects. A planner turns a
pipeline into runs from the graph of columns (ADR 0018); a compositor turns
each run into SQL (`WITH` stages, one-row learn stages cross-joined); a
process-wide store keeps learned values keyed by data, fold and the steps a
step reads (ADR 0024). The pipeline, the model wrapper and the search sit on
top; validation runners write committed JSON (ADR 0025).

**Tech Stack:** Python 3.12+, duckdb 2.0 (the one runtime dependency); tests
and validation: pytest, scikit-learn, numpy, pandas, mpmath.

**Spec:** [`docs/specs/library-core.md`](../../specs/archived/library-core.md).
"§N" below is a section of it; "ADR N" is `docs/adr/00NN-*.md`. Read the spec
and ADRs 0012–0025 before starting; the plan argues from them.

## Global Constraints

- Work on the branch `library-core` in the worktree
  `.claude/worktrees/library-core` (`superpowers:using-git-worktrees`). Merge
  only on Tomas's word.
- Runtime dependency: `duckdb>=2.0.0` only. numpy, pandas, scikit-learn and
  mpmath are added to the `test` group; `src/` never imports them at module
  level (numpy is imported lazily inside the numpy hand-over only).
- uv only (`uv add --group test ...`, `uv run`); every task through `just`.
- Before every commit: `just fmt`, `just check`, `just test`. Never
  `--no-verify`. Conventional commits, no scope except `deps`; no AI
  attribution.
- Every module `src/sqlearn/X/Y.py` has `tests/src/sqlearn/X/test_Y.py`; every
  step and metric has `validation/sqlearn/X/validate_Y.py` (ADR 0025). The
  mirror check (Task 1) enforces it from the start, so each task creates its
  test files.
- British English in prose and docstrings, American spelling in identifiers.
  Public objects have numpydoc docstrings (`just check-docstrings`).
- SQL is built from DuckDB expression objects; SQL text is written only by the
  compositor, and every identifier in it goes through `quote()` (ADR 0015).
- DuckDB 2.0 facts: lambdas are `lambda x: ...` (the `->` arrow is refused);
  relations have `fetchall()`, not `fetchone()`; NaN is not NULL; plain
  `STDDEV` is the sample form, use `stddev_pop`; integer `1 % 0` raises.
- Messages for a user's mistake follow ADR 0019's form: step name and
  position, what went wrong, why, the fix.

## Review Focus

Inputs the spec implies but no task's main tests exercise, most likely first;
each has its test in the task named.

1. **Awkward names:** column names with spaces, quotes or reserved words
   (`my col`, `a"b`, `order`) and category values with them (`New York`,
   `O'Brien`) flow through every step and come out correctly named:
   Task 11 `test_awkward_names_survive_the_slice_steps`.
2. **Empty data:** learning from zero rows, or from a fold with no rows,
   raises a `StepError` naming the step instead of storing NULL values:
   Task 8 `test_learning_from_no_rows_is_refused`.
3. **Columns missing or retyped at `apply`:** data at `apply`/`predict` that
   lacks a learned column, or has it as text where it was numeric, raises a
   message naming the column and the step: Task 8
   `test_apply_names_a_missing_column`.
4. **Many categories:** OneHot on a column with 2,000 distinct values builds
   and runs: Task 11 `test_onehot_handles_two_thousand_categories`.
5. **Bad paths:** a path or glob matching no file raises a `SqlearnError`
   naming it: Task 3 `test_a_glob_matching_nothing_is_named`.

---

### Task 1: Groundwork: dependencies, errors, config, expressions, mirror check

**Files:**

- Modify: `pyproject.toml` (test group; coverage `fail_under`; ruff
  per-file-ignores for `validation/**`), `justfile` (`check-mirror` recipe,
  added to `check`), `src/sqlearn/__init__.py`
- Create: `src/sqlearn/_errors.py`, `src/sqlearn/_config.py`,
  `src/sqlearn/_expr.py`
- Test: `tests/src/sqlearn/test__errors.py`, `test__config.py`,
  `test__expr.py`

**Interfaces:**

- Produces:
  - `SqlearnError(Exception)`; `StepError(SqlearnError)` with attributes
    `step: str`, `position: int`; `InternalError(SqlearnError)`;
    `SqlearnWarning(UserWarning)`; `DefaultsUsedWarning(SqlearnWarning)`.
  - `set_config(*, out: str | Output | None = None, connection:
    duckdb.DuckDBPyConnection | None = None) -> None`;
    `get_config() -> Config` (frozen dataclass, fields `out`, `connection`);
    `connection() -> duckdb.DuckDBPyConnection` (the configured one, else one
    in-memory connection opened on first use and reused). `Output` is defined
    in Task 8; type it as a forward reference.
  - `_expr`: `avg(x)`, `stddev_pop(x)`, `median(x)`, `count(x)`,
    `distinct_values(x)` (`list_sort(list_distinct(list(x)))`),
    `is_missing(x)` (`x IS NULL OR isnan(x::DOUBLE)`), `const(v)`,
    `quote(name: str) -> str` (the one identifier-quoting helper). All take and
    return `duckdb.Expression` except `quote`. Exported from `sqlearn` as
    `sq.avg` etc.

- [ ] **Step 1: Add the dependencies**

Run: `uv add --group test scikit-learn numpy pandas mpmath`
Expected: `uv.lock` updated; `just check-lockfile` passes.

- [ ] **Step 2: Write the failing tests**

`test__expr.py` pins the printed SQL of every expression form sqlearn relies
on (ADR 0015), so a DuckDB upgrade that changes it fails here:

```python
def test_printed_sql_of_each_form():
    """Each expression form prints as the DuckDB SQL the compositor relies on."""
    x = duckdb.ColumnExpression("age")
    assert str(sq.avg(x)) == 'avg("age")'
    assert str(sq.stddev_pop(x)) == 'stddev_pop("age")'
    assert str(sq.distinct_values(x)) == 'list_sort(list_distinct(list("age")))'
    assert str(sq.const(float("nan"))) == "'NaN'::DOUBLE"
    assert str(duckdb.ColumnExpression("l03_scale", "v0")) == '"l03_scale"."v0"'


def test_quote_escapes_quotes_and_reserved_words():
    """quote() makes any name a safe identifier."""
    assert sq._expr.quote('a"b') == '"a""b"'
    assert sq._expr.quote("order") == '"order"'
```

`test__config.py`: `connection()` returns the same object twice;
`set_config(connection=con)` makes `connection() is con`; a fixture resets the
config after each test. `test__errors.py`: `DefaultsUsedWarning` is a
`UserWarning`; `StepError("m", step="scale", position=3)` keeps both
attributes.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --locked pytest tests/src/sqlearn -q`
Expected: FAIL (`ModuleNotFoundError: sqlearn._expr`).

- [ ] **Step 4: Implement the three modules and the exports**

- [ ] **Step 5: Add the mirror check and the coverage floor**

`justfile`: recipe `check-mirror` (group `check`, added to `check`'s list)
fails, naming each missing file, when a `src/sqlearn/**/*.py` other than
`__init__.py` has no `tests/src/sqlearn/**/test_<name>.py`, or a module under
`src/sqlearn/preprocessing/` or `src/sqlearn/metrics/` has no
`validation/sqlearn/**/validate_<name>.py`. `pyproject.toml`: replace the
"No fail_under" comment with `fail_under = 95` and a comment citing spec §13;
add `"validation/**" = ["ANN", "D2", "D3", "D4"]` to the per-file ignores.

- [ ] **Step 6: Run the checks and tests**

Run: `just check && just test`
Expected: both pass; coverage at or above 95%.

- [ ] **Step 7: Commit**

`chore(deps): add the test references` for `pyproject.toml`/`uv.lock`, then
`feat: add errors, config and expression helpers`.

### Task 2: Selectors

**Files:**

- Create: `src/sqlearn/_selectors.py`
- Test: `tests/src/sqlearn/test__selectors.py`

**Interfaces:**

- Produces: `Schema = list[tuple[str, duckdb.DuckDBPyType]]` (ordered);
  `class Selector` with `resolve(schema: Schema) -> list[str]` (in schema
  order) and `may_match(dtype: DuckDBPyType) -> bool`, operators `|`, `&`,
  `-`, `~`; `cols(*names: str) -> Selector`; `numeric() -> Selector`
  (TINYINT…HUGEINT, unsigned, FLOAT, DOUBLE, DECIMAL); `string() -> Selector`
  (VARCHAR); `to_selector(value: Selector | str | Sequence[str]) ->
  Selector`. Exported as `sq.cols`, `sq.numeric`, `sq.string`.

- [ ] **Step 1: Write the failing tests**

```python
SCHEMA = [("id", INTEGER), ("age", DOUBLE), ("city", VARCHAR), ("income", BIGINT)]


def test_numeric_except_id():
    """Selectors combine as in Polars; the result keeps schema order."""
    assert (sq.numeric() - sq.cols("id")).resolve(SCHEMA) == ["age", "income"]


def test_operators():
    """|, & and ~ behave as or, and, not."""
    assert (sq.string() | sq.cols("id")).resolve(SCHEMA) == ["id", "city"]
    assert (~sq.numeric()).resolve(SCHEMA) == ["city"]
    assert (sq.numeric() & sq.cols("age", "city")).resolve(SCHEMA) == ["age"]


def test_may_match_by_type():
    """Planning asks whether a selector could match a not-yet-named column."""
    assert sq.numeric().may_match(INTEGER) and not sq.string().may_match(INTEGER)
```

Also: a name in `cols()` absent from the schema resolves to nothing (the
pipeline reports it, Task 8); `to_selector(["a"])` equals `sq.cols("a")`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: add column selectors`)

Run: `uv run --locked pytest tests/src/sqlearn/test__selectors.py -q`
Expected: FAIL, then PASS after implementing.

### Task 3: Inputs and data keys

**Files:**

- Create: `src/sqlearn/_inputs.py`
- Test: `tests/src/sqlearn/test__inputs.py`

**Interfaces:**

- Consumes: `connection()` (Task 1).
- Produces: `DataKey` (a hashable tuple); `@dataclass(frozen=True) class
  Source: relation: duckdb.DuckDBPyRelation; key: DataKey; schema: Schema`;
  `read(data: object) -> Source`. Accepted: a `str` or `Path` ending in
  `.parquet`, `.csv`, `.json` (globs allowed) → key `("file", ((path, size,
  mtime_ns), ...))` over the sorted matches; another `str` → a table name,
  key `("table", connection id, name, row count)`; a `DuckDBPyRelation` →
  `("relation", its SQL, row count)`; a pandas `DataFrame` → `("frame",
  fingerprint)`. Anything else raises `SqlearnError` listing what is accepted
  (Polars and Arrow say "after the core: see spec §7").
- The fingerprint is one DuckDB query hashing every value and the row order
  (builder's choice of hash, spec §17).

- [ ] **Step 1: Write the failing tests**

- `test_a_file_key_changes_when_the_file_changes` (rewrite the file with
  other content and a later mtime; keys differ).
- `test_a_glob_reads_all_matches_in_order`.
- `test_a_glob_matching_nothing_is_named` (`SqlearnError` whose message
  contains the glob).
- `test_an_edited_frame_gets_a_new_key` (`df.loc[0, "age"] = 999`) and
  `test_reordered_rows_get_a_new_key`.
- `test_a_polars_frame_is_refused_with_the_reason`
  (`pytest.importorskip("polars")`).

- [ ] **Step 2: Run, implement, run, commit** (`feat: read inputs and key
  them for the store`)

### Task 4: The step contract and classification

**Files:**

- Create: `src/sqlearn/_step.py`
- Test: `tests/src/sqlearn/test__step.py`

**Interfaces:**

- Consumes: `Selector`, `to_selector`, `Schema` (Task 2); `_expr` (Task 1).
- Produces:
  - `class Step`: class attributes `static: ClassVar[bool | None] = None`,
    `creates: ClassVar[duckdb.DuckDBPyType | None] = None` (the type of the
    columns a dynamic step creates). Methods to override: `learn(self, x:
    Expression) -> Mapping[str, Expression]` (default `{}`), `apply(self, x:
    Expression, learned: Learned) -> Expression | Mapping[str, Expression]`.
    Provided: `settings(self) -> dict[str, object]` (from the `__init__`
    signature, values read from same-named attributes); `inputs(self, schema:
    Schema) -> list[str]` (resolves `self.cols`); `__getattr__` serving
    `<name>_` from the step's last learn (`dict[column, value]`), set by the
    pipeline through `_set_learned(values: dict[str, dict[str, object]])`.
    Steps take `cols`, `keep=False`, `suffix=None` in `__init__`.
  - `class Learned`: attribute access to learned values for one column. Two
    constructors: `Learned.placeholders(stage: str, names: Mapping[str, str])`
    → each name is `ColumnExpression(stage, internal_name)`; and
    `Learned.values(values: Mapping[str, object])` → scalars as
    `ConstantExpression`, lists as Python lists. Records the names read, in
    order, as `accessed: list[str]`.
  - `classify(step: Step, schema: Schema) -> Literal["static", "dynamic"]`:
    the declared class if `static` is set; otherwise call `apply` on the
    first input column with placeholders; an expression back means static;
    `TypeError` (DuckDB's for looping over or testing an expression) or any
    other exception means dynamic. Answers are cached for the session in
    `KINDS: dict[tuple[type, tuple], str]` keyed by class and settings.
  - `output_names(step_name: str, column: str, result, keep: bool, suffix:
    str | None) -> dict[str, Expression]`: one expression → `{column: e}`, or
    `{f"{column}_{suffix or step_name}": e}` with `keep`; a mapping → its own
    names. Collisions are detected by the pipeline (Task 8).

- [ ] **Step 1: Write the failing tests**

```python
class MyScale(sq.Step):
    def __init__(self, cols=sq.numeric(), keep=False, suffix=None):
        self.cols, self.keep, self.suffix = cols, keep, suffix

    def learn(self, x):
        return {"mean": sq.avg(x), "scale": sq.stddev_pop(x)}

    def apply(self, x, learned):
        return (x - learned.mean) / learned.scale


class MyEncoder(sq.Step):
    def __init__(self, cols=("city",), keep=False, suffix=None): ...
    def learn(self, x):
        return {"cities": sq.distinct_values(x)}

    def apply(self, x, learned):
        return {f"city_{c}": (x == sq.const(c)).cast(INTEGER) for c in learned.cities}


def test_an_undeclared_scale_is_static():
    assert sq._step.classify(MyScale(), SCHEMA) == "static"


def test_an_undeclared_encoder_is_dynamic(): ...  # == "dynamic"
def test_a_declaration_is_trusted_without_inspection(): ...  # apply is never called
def test_the_answer_is_cached_per_settings(): ...  # apply called once for two classify calls
def test_settings_come_from_init():
    assert MyScale().settings() == {"cols": ..., "keep": False, "suffix": None}


def test_placeholders_print_as_stage_references():
    """Placeholders are references into the learn stage."""
    learned = Learned.placeholders("l03_scale", {"mean": "v0", "scale": "v1"})
    assert (
        str(MyScale().apply(duckdb.ColumnExpression("age"), learned))
        == '(("age" - "l03_scale"."v0") / "l03_scale"."v1")'
    )
```

- [ ] **Step 2: Run, implement, run, commit** (`feat: add the step contract
  and classify user steps`)

### Task 5: The run planner

**Files:**

- Create: `src/sqlearn/_plan.py`
- Test: `tests/src/sqlearn/test__plan.py`

**Interfaces:**

- Consumes: `Step`, `classify`, `Schema`, `Selector.may_match`.
- Produces: `@dataclass class Plan: learn_run: list[int]` (per step, the run
  in which it learns; static steps that learn nothing get the run their
  inputs allow), `apply_run: list[int]`, `feed_run: int` (the run that feeds
  the model or produces `apply`'s data), `depends_on: list[frozenset[int]]`
  (per step, the earlier steps it reads from, transitively: ADR 0024);
  `plan(steps: Sequence[tuple[str, Step]], schema: Schema) -> Plan`. Runs are
  numbered from 0.
- Rules (ADR 0018, 0024): a step reads the columns its selector resolves to
  against the schema at that point; a column created by a dynamic step is
  "unknown" until the run after that step learns, and a selector that
  `may_match` an unknown column's declared type (`creates`, or any type when
  `None`) reads it; a step that reads an unknown column learns in the run
  after its producer learns; a step that changes rows (none yet; a class
  attribute `changes_rows = True` is reserved) is read by every later step.

- [ ] **Step 1: Write the failing tests** (steps from `tests/.../conftest.py`
  helpers: `static_step(cols)`, `dynamic_step(cols, creates=INTEGER)`)

| test | pipeline | `learn_run` | `feed_run` |
|---|---|---|---|
| `test_static_only_is_one_run` | Impute(age), Scale(age) | 0, 0 | 0 |
| `test_independent_dynamic_steps_share_a_run` | OneHot(x), Ordinal(y), Scale(a) | 0, 0, 0 | 1 |
| `test_reading_new_columns_waits` | OneHot(x), Scale(numeric) | 0, 1 | 1 |
| `test_earliest_run_per_step` | OneHot(x), Scale(x_*), OneHot(y), Scale(y_*) | 0, 1, 0, 1 | 1 |
| `test_a_chain_of_dynamic_steps_adds_runs` | OneHot(x), DynamicOn(numeric), Scale(numeric) | 0, 1, 2 | 2 |
| `test_string_selector_does_not_wait_for_onehot` | OneHot(city), Lower(string) | 0, 0 | 1 |
| `test_unknown_inputs_depend_on_everything` | Impute(age), UserStep(cols=None), Scale(b) | 0, 0, 0 | 0 |

`x_*` here is a test selector matching names with that prefix. Plus
`test_depends_on_follows_columns`: in Impute(age), OneHot(city), Scale(age),
`depends_on` is `{}`, `{}`, `{0}`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: plan runs from the
  graph of columns`)

### Task 6: The learning store

**Files:**

- Create: `src/sqlearn/_store.py`
- Test: `tests/src/sqlearn/test__store.py`

**Interfaces:**

- Consumes: `DataKey` (Task 3), `Plan.depends_on` (Task 5).
- Produces: `StepKey = tuple[DataKey, FoldKey | None, tuple[tuple[str, str,
  tuple], ...]]` — the data, the fold (`(n, seed, k)` or `None`), and
  `(name, class qualname, sorted settings)` for the step and each step in its
  `depends_on`, in pipeline order; `step_key(...) -> StepKey`; `@dataclass
  class Entry: values: dict[str, dict[str, object]]` (learned name → column →
  value), `columns: list[str]` (what the selector matched),
  `apply_sql: str`; `class Store` with `get(key) -> Entry | None`, `put(key,
  entry)`, `learns: Counter[str]` (learns per step name, for tests),
  `size_bytes() -> int`, `__len__`; module-level `STORE = Store()`. Settings
  that are selectors or models are keyed by their `repr`, which each defines
  deterministically.

- [ ] **Step 1: Write the failing tests**

- `test_a_changed_setting_misses_and_others_hit` (Impute strategy changed:
  impute and scale keys change, onehot's does not: ADR 0024).
- `test_another_fold_misses`, `test_other_data_misses`.
- `test_size_is_reported` (`size_bytes() > 0` after one put).

- [ ] **Step 2: Run, implement, run, commit** (`feat: add the learning
  store`)

### Task 7: The compositor

**Files:**

- Create: `src/sqlearn/_compose.py`
- Test: `tests/src/sqlearn/test__compose.py`

**Interfaces:**

- Consumes: `Step`, `Learned`, `output_names`, `Plan`, `quote`.
- Produces:
  - `stage_name(position: int, step_name: str, learn: bool = False) -> str`:
    `s03_scale` for data, `l03_scale` for learn (position zero-padded to two
    digits).
  - `@dataclass class Stage: name: str; columns: dict[str, Expression]`
    (output name → expression; untouched columns pass through), `learn:
    dict[str, Expression] | None` (internal name → aggregate) `, reads:
    list[str]` (learn stages it cross-joins).
  - `build(source_sql: str, stages: list[Stage]) -> str`: one `WITH` query
    ending in `SELECT * FROM <last data stage>`; learn stages are separate
    CTEs over the stage before the step, cross-joined into the step's data
    stage.
  - `@dataclass class Run: statements: list[str]`.
  - `execute(con, source_sql: str, stages: list[Stage], *, produce: bool) ->
    tuple[dict[str, dict[str, object]], duckdb.DuckDBPyRelation | None, Run]`:
    a run that only learns is one statement returning the learn stages' one
    row each; a run that learns and produces writes its learn stages to
    temporary tables (one statement each; spec §4), then returns the data
    query as a lazy relation reading them.
  - Internal names of learned values are `v0, v1, ...` per learn stage,
    mapped back to `(column, name)` in Python, so no column name ever needs
    escaping inside a learned-value name.

- [ ] **Step 1: Write the failing tests**

- `test_impute_then_scale_learns_from_imputed_values`: on `age = 10, NULL,
  30` with an inline fill-0 imputer and `MyScale` (Task 4), the learned mean
  is `40/3` (not `20`), in one statement.
- `test_stage_names_follow_steps` (`"s01_scale"` appears in the SQL).
- `test_a_learn_and_produce_run_uses_temp_tables` (`Run.statements` has the
  `CREATE TEMP TABLE` statements and the data query; the relation is lazy).
- `test_reserved_and_spaced_names_are_quoted` (`order`, `my col`).

- [ ] **Step 2: Run, implement, run, commit** (`feat: compose runs into
  SQL`)

### Task 8: The pipeline: `learn`, `apply`, `out=`

**Files:**

- Create: `src/sqlearn/_pipeline.py`, `src/sqlearn/_output.py`
- Test: `tests/src/sqlearn/test__pipeline.py`, `test__output.py`

**Interfaces:**

- Consumes: Tasks 2–7.
- Produces:
  - `class Pipeline(steps: Sequence[tuple[str, Step | object]])`:
    `learn(data) -> Pipeline`; `apply(data, out: str | Output | None = None)`;
    `__getitem__(key: str | int)` (the step); `steps` (the pairs);
    `named_steps: dict[str, object]`; `runs_: list[Run]` (the last call's);
    `columns_out_: list[str]` (after `learn`). `make_pipeline(*steps) ->
    Pipeline` names steps after their class, lowercased, numbered on clashes
    as scikit-learn does. `train`/`predict` come in Task 12.
  - `learn`: read → plan → for each run, look up each step's `StepKey`; learn
    the misses via `execute`; `put` entries; set step attributes; record runs.
    A selector matching nothing raises `StepError` naming the step; output
    name collisions raise `StepError` naming the column and suggesting
    `suffix=`.
  - `apply` with every value known: one run, learned values as constants,
    returning a lazy relation, or `to_output(rel, out or get_config().out)`.
  - `_output.py`: `class Output` (base); `out_parquet(path) -> Output`,
    `out_csv(path)`, `out_json(path)` (DuckDB `COPY ... TO`);
    `to_output(rel, out) -> object` for `None` (the relation), `"pandas"`,
    `"polars"`, `"numpy"` (dict of column → array), `"arrow"`, or an
    `Output`; an unknown name raises `SqlearnError` listing the names.
    Exported as `sq.Pipeline`, `sq.make_pipeline`, `sq.set_config`,
    `sq.out_parquet`, `sq.out_csv`, `sq.out_json`.

- [ ] **Step 1: Write the failing tests**

- `test_learn_then_apply_matches_hand_computed_values` (MyScale on a small
  table).
- `test_apply_is_lazy_and_keeps_names` (returns a `DuckDBPyRelation` with the
  expected `columns`).
- `test_out_pandas_and_out_parquet` (the parquet file holds the rows).
- `test_set_config_out_is_the_default_and_out_overrides_it`.
- `test_learned_values_are_attributes` (`pipe["scale"].mean_ == {"age":
  ...}`).
- `test_relearning_unchanged_steps_hits_the_store` (`STORE.learns` unchanged
  on the second `learn`).
- `test_learning_from_no_rows_is_refused` (Review Focus 2).
- `test_apply_names_a_missing_column` (Review Focus 3: the message holds the
  column and the step).
- `test_a_selector_matching_nothing_names_the_step`.
- `test_keep_adds_a_named_column` (`Scale(keep=True)` adds `age_scale`,
  keeps `age`) and `test_a_name_collision_suggests_suffix`.
- `test_selectors_are_fixed_at_learn` (`apply` on data with an extra numeric
  column leaves it unscaled).
- `test_columns_out_without_running` and `test_make_pipeline_names_steps`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: add the pipeline with
  learn, apply and out=`)

### Task 9: Failure feedback

**Files:**

- Create: `src/sqlearn/_diagnose.py`
- Modify: `src/sqlearn/_pipeline.py` (wrap building and running)
- Test: `tests/src/sqlearn/test__diagnose.py`

**Interfaces:**

- Produces: `diagnose(exc: BaseException, steps, stage_of: Callable[[str],
  int | None]) -> SqlearnError`. While building: an exception from a user
  step's `learn`/`apply` becomes a `StepError`; if the step was declared
  static and `apply` needed a learned value, the message is ADR 0019's
  example with the step's names filled in (using `Learned.accessed`). While
  running: a `duckdb.Error` is traced to a step through the stage name in its
  message (`stage_of`), then re-classified by inspection when the step is a
  user step. A failure in a built-in step (class defined in `sqlearn`) becomes
  `InternalError` saying it is sqlearn's bug, with the SQL and versions to
  report. Diagnosis runs only in these `except` paths.

- [ ] **Step 1: Write the failing tests** (a suite of broken user steps in
  `tests/src/sqlearn/broken_steps.py`, one test per step, each asserting the
  exact message):

- `test_declared_static_but_needs_values` (message contains `"MyEncoder
  (step 3) is declared static, but its apply() loops over learned.cities"`
  and `"Fix: remove static=True"`).
- `test_bad_sql_in_apply_names_the_step` (an expression calling a function
  that does not exist).
- `test_a_missing_column_names_column_and_step`.
- `test_a_builtin_failure_is_an_internal_error` (monkeypatch `Scale.apply` to
  raise; the message says "sqlearn's bug").

- [ ] **Step 2: Run, implement, run, commit** (`feat: explain failures by
  step`)

### Task 10: `Impute` and `Scale`

**Files:**

- Create: `src/sqlearn/preprocessing/__init__.py`, `impute.py`, `scale.py`
- Test: `tests/src/sqlearn/preprocessing/test_impute.py`, `test_scale.py`
- Create (stub runners, filled in Task 16, each `def cases() -> list[dict]:
  return []` for now): `validation/sqlearn/preprocessing/validate_impute.py`,
  `validate_scale.py`

**Interfaces:**

- Produces: `Impute(cols=numeric(), strategy="median" | "mean", keep=False,
  suffix=None)`, static; missing means NULL **or NaN** (scikit-learn's
  `missing_values=np.nan`): learns over non-missing values, applies `CASE WHEN
  is_missing(x) THEN value ELSE x END`. `Scale(cols=numeric(), keep=False,
  suffix=None)`, static; learns `mean`, `scale` (population standard
  deviation); applies `(x - mean) / scale`, with `scale = 0` treated as `1`
  (scikit-learn's behaviour for constant columns). Exported as `sq.Impute`,
  `sq.Scale`. An unknown `strategy` raises `SqlearnError` in `__init__`.

- [ ] **Step 1: Write the failing tests** against scikit-learn on generated
  data (seeded), with `numpy.testing.assert_allclose(rtol=1e-12)`:

- `test_impute_matches_simple_imputer[median|mean]`,
  `test_impute_treats_nan_as_missing`, `test_all_missing_column` (scikit-learn
  drops it; sqlearn raises a `StepError` naming the column, as the spec does
  not drop columns silently).
- `test_scale_matches_standard_scaler`, `test_constant_column_scales_to_zero`.
- `test_impute_then_scale_matches_sklearn_pipeline`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: add Impute and
  Scale`)

### Task 11: `OneHot` and `Ordinal`

**Files:**

- Create: `src/sqlearn/preprocessing/onehot.py`, `ordinal.py`
- Test: `tests/src/sqlearn/preprocessing/test_onehot.py`, `test_ordinal.py`
- Create (stub runners): `validation/sqlearn/preprocessing/validate_onehot.py`,
  `validate_ordinal.py`

**Interfaces:**

- Produces: `OneHot(cols, keep=False, suffix=None)`, dynamic, `creates =
  INTEGER`; learns `categories` (`distinct_values`); applies one integer column
  `<column>_<value>` per category; NULL is its own category `<column>_NULL`
  only if seen at learn (as scikit-learn treats missing values); an unseen value
  gives all zeros (`handle_unknown="ignore"`). `Ordinal(cols, keep=False,
  suffix=None)`, dynamic, `creates = INTEGER`; each value's position in the
  sorted categories; unseen → `-1`. Exported as `sq.OneHot`, `sq.Ordinal`.

- [ ] **Step 1: Write the failing tests**

- `test_onehot_matches_sklearn` (values and column names, with
  `OneHotEncoder(handle_unknown="ignore", sparse_output=False)`),
  `test_unseen_value_is_all_zeros`.
- `test_ordinal_matches_sklearn` (`OrdinalEncoder(handle_unknown=
  "use_encoded_value", unknown_value=-1)`), `test_unseen_value_is_minus_one`.
- `test_onehot_and_ordinal_learn_in_one_run` (`len(pipe.runs_) == 1` after
  `learn`; `pipe.runs_[0].statements` has one statement).
- `test_awkward_names_survive_the_slice_steps` (Review Focus 1).
- `test_onehot_handles_two_thousand_categories` (Review Focus 4).

- [ ] **Step 2: Run, implement, run, commit** (`feat: add OneHot and
  Ordinal`)

### Task 12: Models: `train`, `predict`, `sq.Model`, `feed=`

**Files:**

- Create: `src/sqlearn/_model.py`
- Modify: `src/sqlearn/_pipeline.py`
- Test: `tests/src/sqlearn/test__model.py`, additions to `test__pipeline.py`

**Interfaces:**

- Produces: `class Model(estimator: object, feed: str = "numpy")`;
  `as_model(obj) -> Model` (wraps a plain estimator); `copy_model(m: Model) ->
  Model` (scikit-learn's `clone` rule: `type(e)(**e.get_params())` when
  `get_params` exists, else `copy.deepcopy`); `hand_over(rel, feed: str) ->
  object` (numpy: a 2-D float array from `rel.fetchnumpy()`, numpy imported
  here only; a missing numpy raises `SqlearnError` saying to install it;
  `feed` other than `"numpy"` raises `SqlearnError` pointing to issue #21).
  `Pipeline.train(data, target: str, feed: str | None = None) -> Pipeline`:
  the target column is removed before planning (no step or selector sees
  it) and fetched in the same query as the features; `Pipeline.predict(data,
  out=None)`: one relation with a single column `prediction`, in input row
  order (rows are numbered in the feeding query; predictions enter DuckDB
  without pandas or pyarrow). A pipeline whose last step is not a step is
  taken as ending in a model. Exported as `sq.Model`.

- [ ] **Step 1: Write the failing tests**

- `test_train_predict_matches_sklearn_pipeline` (Impute → OneHot → Scale →
  `LogisticRegression`: predictions equal scikit-learn's pipeline with
  `ColumnTransformer`).
- `test_the_target_is_never_scaled` (`Scale(sq.numeric())` with a numeric
  target: `pipe["scale"].mean_` has no target key).
- `test_predict_returns_one_column_in_input_order`.
- `test_feed_other_than_numpy_points_to_issue_21`.
- `test_copy_model_keeps_settings`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: train and predict with
  outside models`)

### Task 13: `accuracy`

**Files:**

- Create: `src/sqlearn/metrics/__init__.py`, `accuracy.py`
- Test: `tests/src/sqlearn/metrics/test_accuracy.py`
- Create (stub runner): `validation/sqlearn/metrics/validate_accuracy.py`

**Interfaces:**

- Produces: `@dataclass(frozen=True) class Metric: name: str; expression:
  Callable[[Expression, Expression], Expression]; greater_is_better: bool`;
  `Metric.compute(rel, target: str, prediction: str = "prediction") ->
  float`; `accuracy = Metric("accuracy", lambda y, p: avg(CASE WHEN y = p THEN
  1.0 ELSE 0.0 END), True)`. Exported as `sq.accuracy`.

- [ ] **Step 1: Write the failing tests**: equals
  `sklearn.metrics.accuracy_score` on generated labels (ints and strings);
  the printed SQL is the `avg(CASE ...)` form.

- [ ] **Step 2: Run, implement, run, commit** (`feat: add accuracy in SQL`)

### Task 14: The search

**Files:**

- Create: `src/sqlearn/model_selection/__init__.py`, `search.py`,
  `methods.py`, `folds.py`, `defaults.py`
- Test: `tests/src/sqlearn/model_selection/test_search.py`,
  `test_methods.py`, `test_folds.py`, `test_defaults.py`

**Interfaces:**

- Produces:
  - `KFold(n: int = 5, seed: int = 0)` with `expression(row_alias: str) -> str`
    = `hash(<alias>, <seed>) % <n>` (a hash of the whole row and the seed).
  - `class Method` (protocol): `start(space: list[dict]) -> None`, `ask() ->
    dict | None` (`None` ends), `tell(params: dict, score: float) -> None`,
    `knows_all: bool`. `Grid()` (expands lists; a `Range` raises
    `SqlearnError` naming the setting); `@dataclass class Range: low: float;
    high: float; log: bool = False`, constructor `range(low, high, log=False)`
    exported as `sq.range`.
  - `DEFAULT_SPACES: dict[tuple[str, str], dict[str, list]]` = `{("sklearn",
    "LogisticRegression"): {"C": [0.001, 0.0068129, 0.046416, 0.31623,
    2.1544, 14.678, 100.0]}}` (`numpy.logspace(-3, 2, 7)`, five significant
    figures).
  - `Search(pipe, params: dict | list[dict] | None = None, metric: Metric =
    accuracy, method: Method | None = None, folds: KFold | None = None)` with
    `train(data, target) -> Search`, `predict(data, out=None)`,
    `best_params_`, `best_score_` (mean over folds), `results_` (relation:
    `setting` as JSON text, `fold`, `score`), `used_` (dict: each of `params`,
    `method`, `folds` → `"given"` or the default used), `best_pipeline_`,
    `transforms_: int` (data preparations performed, for tests).
  - Behaviour (spec §10, ADR 0022, 0024): settings keyed `step__setting`,
    `"model"` for candidates, lists of grids accepted; a setting a model or
    step lacks raises `SqlearnError` naming both; trials run on copies (steps
    rebuilt from `settings()`, models by `copy_model`); with `knows_all`, loop
    fold first and, per fold, per distinct preparation (settings not starting
    with `model`), prepare once and train every model setting; with no
    `params`, use `DEFAULT_SPACES` or one trial of the model's own settings,
    and warn `DefaultsUsedWarning` with the hint text of ADR 0022; at the end
    train the best setting on all data as `best_pipeline_`. Exported as
    `sq.Search`, `sq.Grid`, `sq.KFold`.

- [ ] **Step 1: Write the failing tests**

- `test_folds_are_balanced_and_repeatable` (100,000 rows: each fold within
  1% of 20,000; the same row gets the same fold twice).
- `test_grid_matches_gridsearchcv` (the slice's grid on generated data:
  `best_params_` equal; per-setting mean scores equal to scikit-learn's
  `cv_results_["mean_test_score"]` when both use the same fold assignment,
  passed to scikit-learn as `PredefinedSplit`).
- `test_changing_only_c_learns_nothing` (`STORE.learns` per step after the
  slice's search: impute 10, scale 10, onehot 5, ordinal 5).
- `test_fold_first_prepares_once_per_fold_and_preparation`
  (`search.transforms_ == 10` for 30 trainings).
- `test_the_users_pipe_is_unchanged`.
- `test_list_of_grids_for_two_models` and `test_unknown_setting_is_named`.
- `test_range_given_to_grid_is_refused`.
- `test_no_params_uses_default_space_and_warns` (`pytest.warns(
  DefaultsUsedWarning, match="LogisticRegression")`; `used_["params"]` names
  the default) and `test_unknown_model_runs_one_trial_and_warns`.

- [ ] **Step 2: Run, implement, run, commit** (`feat: add the search with
  grid and folds`)

### Task 15: The slice, end to end

**Files:**

- Create: `tests/src/sqlearn/test_slice.py`

**Interfaces:**

- Consumes: everything above; no new source code unless a test exposes a gap
  (fix it in the module that owns it).

- [ ] **Step 1: Write the tests**

- `test_the_slice_script_runs` (spec §2's script on generated Parquet files in
  `tmp_path`; `search.predict(..., out="pandas")` has one row per input row).
- `test_run_counts_for_every_combination`: parametrized over pipelines built
  from Impute, Scale, OneHot, Ordinal and the Task 4 user steps (declared and
  undeclared), with selectors by name, `numeric()` and `string()`; each case
  asserts `len(pipe.runs_)` from a table written in the test, and that the
  result equals the same pipeline run one step at a time (each step learned
  and applied in its own query) — the reference that needs no planner.
- `test_an_edited_frame_relearns` (pandas input edited between two `learn`
  calls: `STORE.learns` grows; unedited: it does not).
- `test_store_size_is_reported` (prints `STORE.size_bytes()` after the slice's
  search; asserts it is under 1 MB).
- `@pytest.mark.slow test_preparation_runs_larger_than_memory`: generate
  Parquet of 20 million rows in `tmp_path` (several times the limit), then
  set `memory_limit = '64MB'`, `threads = 1` and `temp_directory` in
  `tmp_path`, as `tests/test_environment.py` does;
  `pipe.learn(path)` then `pipe.apply(path, out=sq.out_parquet(out))`
  finishes; spot-check the learned median and mean against DuckDB's own
  aggregates on the same file.

- [ ] **Step 2: Run**

Run:
`just test && uv run --locked pytest tests/src/sqlearn/test_slice.py -m "" -q`
Expected: PASS, the slow test included.

- [ ] **Step 3: Commit** (`test: prove the slice end to end`)

### Task 16: Validation and stored results

**Files:**

- Create: `validation/__init__.py`, `validation/__main__.py`,
  `validation/_cases.py` (datasets, error measures, JSON writing),
  `validation/_tests_report.py` (a pytest plugin), the four step runners and
  `validation/sqlearn/metrics/validate_accuracy.py` (filling the Task 10, 11,
  13 stubs), `validation/pipelines/validate_slice.py`
- Modify: `justfile` (`validate` recipe; add it to `verify`)
- Test: `tests/validation/test__cases.py`, `tests/validation/test___main__.py`
- Results (committed): `validation/environment.json`,
  `validation/tests.json`, `validation/sqlearn/**/*.results.json`,
  `validation/pipelines/slice.results.json`

**Interfaces:**

- Produces: each runner exposes `cases() -> list[dict]`. A case (ADR 0025) has
  `step`, `formula`, `dataset`, `rows`, `type`, `reference`, `abs_error`,
  `rel_error`, `ulps`, `bound_ulps`, `result` (`"pass"`, `"fail"`,
  `"anomaly"`), `note`. References per formula: the canonical value
  (`mpmath` at 50 digits; `Fraction` for medians and accuracy), sqlearn,
  DuckDB's own aggregate alone, the same at `threads = 1`, numpy,
  scikit-learn, pandas. A reference library missing its own algorithm's
  precision is `"anomaly"`, not `"fail"`; only sqlearn's own cases can fail.
  Datasets generated with seed 0: small (4 rows), medium (1,000), large
  (100,000), and the edge sets: NULL, NaN, empty, single row, reserved-word
  names. Bounds are constants in each runner, set from the first measurement
  (the smallest power of two at or above the worst measured ULPs) with a
  comment; loosening one needs a written reason (ADR 0016). Encoders and
  accuracy are compared for exact equality.
- `python -m validation` runs every runner, writes the JSON (sorted keys,
  indent 2, no dates or durations), writes `environment.json`, and exits
  non-zero if any sqlearn case fails. `validation/_tests_report.py`, loaded
  with `-p validation._tests_report`, writes `tests.json` (name, area = the
  mirrored module path, tier, outcome).
- `just validate`: `uv run --locked pytest -m "" -q -p validation._tests_report
  --ignore=tests/githooks && uv run --locked python -m validation`.

- [ ] **Step 1: Write the failing tests** for `_cases.py` (`ulps(1.0,
  nextafter(1.0, 2))` is 1; a case outside its bound is `"fail"`; JSON output
  is byte-identical across two runs) and for `__main__` (a fake failing runner
  makes it exit 1).
- [ ] **Step 2: Run, implement, run.**
- [ ] **Step 3: Run `just validate`**, inspect the results, set the bounds,
  run again.
Expected: exit 0; `git status` shows the results files; a second run changes
nothing.
- [ ] **Step 4: Commit** (`feat: validate the slice and store the results`)

### Task 17: Documentation

**Files:**

- Create: `docs/guide/writing-a-step.md`, `examples/plot_slice.py`
- Modify: `docs/guide/index.md` (toctree), `docs/reference/index.md`
  (autosummary entries for the public objects), `pyproject.toml` (docs group:
  `scikit-learn`, `numpy`, `pandas`, for the example)

**Interfaces:**

- Consumes: the public API.

- [ ] **Step 1: Write the guide page**: the two-part contract (§3.1), what a
  step declares (§3.2), placeholders and how sqlearn classifies an undeclared
  step (§3.4), the messages (§12) with ADR 0019's example, and the rule that
  learned values come only through `learned`. Executable cells use the Task 4
  `MyScale`.
- [ ] **Step 2: Write the gallery example**: spec §2's script on data
  generated in the example (seeded, 10,000 rows), printing `best_params_`,
  `best_score_` and the first rows of `results_`.
- [ ] **Step 3: Build**

Run: `just build-docs && just check-docstrings`
Expected: both pass, no warnings.

- [ ] **Step 4: Run `just verify`**
Expected: pass, the slow tier and `validate` included.

- [ ] **Step 5: Commit** (`docs: document the core and show the slice`)

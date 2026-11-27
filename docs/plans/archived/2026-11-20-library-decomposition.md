---
type: plan
tags: [decomposition, pca, library-breadth, gram-matrix, numpy, plan]
summary: "Implementation plan for PCA (sq.decompose.pca) as scikit-learn 1.9.1's PCA with svd_solver='covariance_eigh': numpy as a runtime dependency (ADR 0057), a Gram learn in the core that streams centred batches into numpy (ADR 0058), the step, validation, a larger-than-memory benchmark and the docs."
related: [docs/specs/archived/library-decomposition.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0005-runtime-dependencies.md, docs/adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md]
---
# Decomposition (PCA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sq.decompose.pca` and `sq.decompose(method="pca")`, as
scikit-learn 1.9.1's `PCA(svd_solver="covariance_eigh")`, learning from data
larger than memory and applying in SQL.

**Architecture:** numpy becomes a runtime dependency (ADR 0057). The core
gains a **Gram step** (ADR 0058): a step that declares `gram = True` learns
its per-column SQL values (the means among them) in the ordinary learn
statement; the core then streams the step's centred input rows from DuckDB in
batches, builds XᵀX in numpy, and calls the step's `learned_from_gram`, whose
returned values join the step's learned values. `PCA` is a dynamic whole-row
Gram step in a new package `sqlearn.decomposition`; it keeps the whole
decomposition and cuts it to `n_components` in `apply_row`.

**Tech Stack:** Python 3.12, DuckDB and numpy (the runtime dependencies), uv,
just, pytest, scikit-learn 1.9.1 and mpmath as test-only references.

**Spec:** `docs/specs/library-decomposition.md` (approved 2026-11-20). Read
it beside this plan; section numbers below are the spec's.

## Global Constraints

- Every task runs through `just`; Python through `uv run`, never pip or a
  bare `python` (ADR 0001, 0008).
- The runtime dependencies are `duckdb` and `numpy`, nothing else: no
  pandas, no pyarrow on any path of a Gram learn (spec §5.3).
- Data passes through Python only in a Gram learn, one batch at a time;
  applying is SQL only (spec §3 rule 2, ADR 0058).
- Behaviour, defaults, signs, names and refusals are scikit-learn 1.9.1's
  `PCA(svd_solver="covariance_eigh")`; where the spec and scikit-learn
  disagree, build scikit-learn's and correct the spec in the same commit
  (spec §3 rule 1).
- Every refusal and warning has `Why:` and `Fix:` (ADR 0019, 0046).
- British English in prose, American spelling in identifiers (ADR 0010).
- Commits: Conventional Commits, no scope but `hooks`, `site`, `deps`, header
  at most 72 characters, no AI attribution, the issue number in the header.
- Before every commit: `just fmt`, `just check`, `just test`, naming every
  failure; leave the docs tagger's frontmatter edits to unrelated files out
  of commits. Before calling the work done: `just verify`.
- TDD: watch each test fail for the right reason first; tests through public
  seams, named in `GLOSSARY.md` terms.

## Review Focus

1. **Input columns differing only by case** (`a`, `A`): the centred stream
   SQL quotes each name and keeps both (HANDOFF trap: never project
   `rel.columns` back by name). Test in Task 2.
2. **An empty input** (a glob or filter giving no rows): refused with the
   core's "learned from no rows" `StepError` before any batch, never a numpy
   error on an empty array. Test in Task 2.
3. **A NaN (not NULL) in an input**, inserted into a DuckDB table (pandas
   hands NaN as NULL): refused at learn with the impute `Fix:`, as NULL is.
   Test in Task 4.
4. **INTEGER, BIGINT and DECIMAL inputs**: cast to DOUBLE before centring
   (a bare `1.0` in SQL is DECIMAL), giving scikit-learn's components on the
   same values as floats. Test in Task 4.
5. **PCA after a dynamic step** (`sq.encode.onehot()` then
   `sq.decompose.pca()`): the one-hot columns are learned in an earlier run
   and reach the stream as constants; a step after PCA sees `pca0`, … only.
   Test in Task 6.

---

### Task 0: Branch, issue and the decisions

- [ ] **Step 1:** `git switch -c decomposition` from `main`.
- [ ] **Step 2:** Open the area's issue with `gh issue create` (title
  "Library breadth: decomposition (PCA)", label `enhancement`, body linking
  the spec and ADRs 0057, 0058), add it to the board as the github-pm skill
  says, and use its number (written `#66` below) in every commit header.
- [ ] **Step 3:** Write `docs/adr/0057-numpy-is-a-runtime-dependency.md` and
  `docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md` from spec §6, each
  "Status: accepted (2026-11-20)", each amending its ADR (0005, 0002) and
  adding a one-line "Amended by" note to that ADR. Add both to
  `docs/adr/index.md` under their topics.
- [ ] **Step 4:** Commit the spec, this plan, the two ADRs, the two amended
  ADRs and the index: `docs: specify decomposition (#66)`.

### Task 1: numpy as a runtime dependency (ADR 0057)

**Files:**
- Modify: `pyproject.toml` (`dependencies`), `uv.lock`
- Modify: `CLAUDE.md` (the rule "The only runtime dependency is `duckdb`")
- Test: `tests/test_environment.py`

- [ ] **Step 1: Write the failing test**
  `test_environment.py::test_the_runtime_dependencies_are_duckdb_and_numpy`:
  `importlib.metadata.requires("sqlearn")` without extras or markers, names
  only, equals `["duckdb", "numpy"]` in any order.
- [ ] **Step 2:** Run `uv run pytest tests/test_environment.py`; expected
  FAIL (`numpy` missing).
- [ ] **Step 3:** `uv add "numpy>=2.5.4"`, with the comment above it in
  `pyproject.toml`: `# The small matrix a Gram step learns from: DuckDB has
  no eigen or solve function (ADR 0057).` Change the duckdb comment's "the
  one runtime dependency" to "the engine". Rewrite the `CLAUDE.md` rule to
  "The runtime dependencies are `duckdb` and `numpy`; any other needs a
  written reason and a permissive licence (0004, 0005, 0057)." The lazy numpy
  imports in `_feed.py` may stay; change them only if a test needs it.
- [ ] **Step 4:** Run the test, then `uv sync` and `just test`; expected
  PASS.
- [ ] **Step 5:** Checks; commit `build: make numpy a runtime dependency
  (#66)`.

### Task 2: The Gram learn in the core (spec §5.1–§5.3)

**Files:**
- Create: `src/sqlearn/_gram.py`
- Modify: `src/sqlearn/_step.py` (`Step.gram`, `Step.learned_from_gram`,
  docstring), `src/sqlearn/_plan.py` (`plan`), `src/sqlearn/_pipeline.py`
  (`_learn_run`)
- Test: `tests/src/sqlearn/test__gram.py`, `tests/src/sqlearn/test__plan.py`,
  `tests/src/sqlearn/test__pipeline.py`; a Gram test step in
  `tests/src/sqlearn/steps_for_tests.py`

**Interfaces:**
- Produces, in `_step.py`: `Step.gram: ClassVar[bool] = False`,
  `Step.before_gram(self, learned: Mapping[str, Mapping[str, object]]) ->
  None` (default: nothing) and `Step.learned_from_gram(self, gram:
  numpy.ndarray, learned: Mapping[str, Mapping[str, object]]) ->
  Mapping[str, Mapping[str, object]]` (default: raise
  `NotImplementedError`). `learned` is the step's SQL-learned values,
  learned name → column → value; a Gram step's `learn(x)` must return `mean`
  and `count`, which the core reads to centre the rows. `before_gram` is
  called before any batch, so a step refuses what it cannot learn from
  without a pass over the data. `gram` is the p × p sum of the centred rows'
  `xᵀx`, columns in input order. `learned_from_gram` returns learned name →
  column → value, plain `int`, `float` or lists of `float`, merged into the
  step's learned values (a name clash with its SQL values is an
  `InternalError`).
- Produces, in `_gram.py`:
  `gram_matrix(con: duckdb.DuckDBPyConnection, sql: str, columns:
  Sequence[str], means: Mapping[str, float]) -> numpy.ndarray`, which runs
  `sql` (the data reaching the step), centres and casts each column in SQL
  (`(x::DOUBLE - mean)`, every name quoted), fetches batches with
  `fetchnumpy` and sums `batch.T @ batch` in order;
  `batch_rows(columns: int) -> int`, from `_feed.MEGABYTES` as the streamed
  training batches size theirs; and `check_fits(con, columns: int) -> None`,
  raising `SqlearnError` when one batch plus 4 copies of the p × p matrix in
  float64 is over `_memory.allowance(con)` (`Fix:` fewer columns, or a
  larger budget with `sq.set_config(memory=...)`).
- The batches here are cut as the spike cut them: the centred rows numbered
  into a temporary table, fetched by row range, the table dropped after.
  Task 3 measures the alternatives.
- Planner rule (in `plan`): a Gram step learns in a run after every step it
  depends on that learns, and is dynamic (applies in the run after it
  learns), so its input reaches the stream with constants. ADR 0018's other
  rules are unchanged.
- In `_learn_run`, after `execute`: for each step learned in this run with
  `gram`, build the SQL of the data reaching it from the stages before it
  (each holding constants), call `before_gram`, `check_fits`, then
  `gram_matrix`, then `learned_from_gram`, and merge before the `Entry` is
  stored. The streaming
  statement is appended to the run's `statements`.

- [ ] **Step 1: Write the failing tests.** The test step `GramCovariance`
  (`gram = True`, `dynamic = True`, `rowwise = True`, learns `mean` and
  `count`, returns `{"covariance": {c: list(gram[j] / (rows - 1))}}`, and
  `apply_row` writes one column per input of its covariance with the first
  input):
  - `test__gram.py::test_gram_matrix_matches_numpy_on_centred_rows`: on 1,000
    random rows of 3 columns, `rel=1e-12` against `numpy.cov(...,
    bias=False) * (n - 1)`.
  - `test__gram.py::test_gram_matrix_keeps_columns_differing_only_by_case`
    (`a`, `A`).
  - `test__gram.py::test_check_fits_refuses_a_matrix_over_the_allowance`
    (`sq.set_config(memory="10MB")`, 2,000 columns; match `"Fix:"`).
  - `test__plan.py::test_a_gram_step_learns_after_the_steps_it_reads`:
    `impute`, `scale`, `GramCovariance` plan into learn runs 0, 0, 1 and the
    Gram step applies in run 2.
  - `test__pipeline.py::test_a_gram_step_learns_from_the_prepared_rows`:
    after `impute` then `scale`, its learned covariance equals
    `numpy.cov` of scikit-learn's `StandardScaler` output on the imputed
    frame (`rel=1e-12`); `runs_` holds the streaming statement.
  - `test__pipeline.py::test_a_gram_step_refuses_an_empty_input`: a filter
    giving no rows raises `StepError` matching `"learned from no rows"`.
  - `test__pipeline.py::test_a_gram_step_is_found_in_the_store`: a second
    `learn` on the same data runs nothing (`runs_ == []`).
- [ ] **Step 2:** Run `uv run pytest tests/src/sqlearn -k gram`; expected
  FAIL (`gram` unknown).
- [ ] **Step 3:** Implement the interfaces above; document `gram` and
  `learned_from_gram` in `Step`'s docstring as internal (spec §5.1: not for
  users' steps yet).
- [ ] **Step 4:** Run the new tests, then `uv run pytest tests/src/sqlearn`;
  expected all PASS, no other test changed.
- [ ] **Step 5:** Checks; commit `feat: learn a step from its Gram matrix
  (#66)`.

### Task 3: How the batches are cut (spec §5.3)

**Files:**
- Create: `validation/benchmarks/gram_batches.py`
- Modify: `src/sqlearn/_gram.py` (only if a way below wins)
- Test: `tests/src/sqlearn/test__gram.py`

- [ ] **Step 1:** Write `gram_batches.py` as the other benchmarks are written
  (`uptime` before and after, data generated by DuckDB and written as
  Parquet with `COPY`, one probe per subprocess). It times `gram_matrix` on
  1M rows × 50, 200 and 500 columns for each way to cut the batches that
  needs only duckdb and numpy: (a) the temporary table by row range (Task
  2's), (b) `fetchmany` of a streaming result into `numpy.array`, (c) the
  source read by `file_row_number` ranges when it is one Parquet file, and
  any other found in DuckDB's Python API docs (use context7). It prints a
  Markdown table and decides nothing.
- [ ] **Step 2:** Run it; if a way other than (a) is correct and faster at
  every width, switch `gram_matrix` to it, keeping (a) where the other does
  not apply. Record the table and the choice in
  `docs/benchmarks/gram-batches.md`, linked from `docs/benchmarks/index.md`.
- [ ] **Step 3: Test:**
  `test__gram.py::test_gram_matrix_agrees_on_one_and_many_threads`: the same
  data with `SET threads = 1` and the default agrees within ADR 0043's
  bound for a sum (no bit-equality).
- [ ] **Step 4:** `uv run pytest tests/src/sqlearn -k gram`; expected PASS.
- [ ] **Step 5:** Checks; commit `perf: cut Gram batches the cheapest way
  (#66)`, or `docs: record how Gram batches are cut (#66)` when (a) stays.

### Task 4: The group and PCA's learned values (spec §4, §4.1–§4.3)

**Files:**
- Create: `src/sqlearn/decomposition/__init__.py`,
  `src/sqlearn/decomposition/_decompose.py` (the group),
  `src/sqlearn/decomposition/pca.py`
- Modify: `src/sqlearn/__init__.py` (export `decompose`),
  `docs/reference/index.md`
- Test: `tests/src/sqlearn/decomposition/test__decompose.py`,
  `tests/src/sqlearn/decomposition/test_pca.py`

**Interfaces:**
- Produces: `class PCA(Step)` with `__init__(self, n_components: int | float
  | None = None, whiten: bool = False, cols=_numeric())`, `gram = True`,
  `dynamic = True`, `rowwise = True`, `names_are_labels = False`,
  `output_settings = frozenset({"n_components", "whiten"})`,
  `default_name() -> "pca"`, `__repr__` as
  `sq.decompose.pca(n_components=3)`.
- Learned per column, from SQL: `mean` (`sq.agg.mean`, DOUBLE), `count`,
  `missing` (NULL or NaN count), `infinite`. From `learned_from_gram`, for
  the input column at position j: `weights`, the j-th entry of every
  component (p floats, components largest first, signs chosen), and
  `variance`, the j-th largest eigenvalue (negative ones set to 0). The
  whole decomposition, never cut (spec §4.2).
- Properties, cut from those as scikit-learn's attributes: `components_:
  list[list[float]]`, `explained_variance_`, `explained_variance_ratio_`,
  `singular_values_: list[float]`, `mean_: list[float]`, `n_components_`,
  `n_samples_: int`, `noise_variance_: float`.
- Produces: `class DecomposeGroup(Group)`, `decompose =
  DecomposeGroup("decompose")`, with `__call__(*names, method="pca",
  n_components=None, whiten=False, cols=None)` and `pca(*names,
  n_components=None, whiten=False, cols=None)`, built as `SelectGroup` in
  `src/sqlearn/feature_selection/_select.py`, refusing a number as a
  positional with its `Fix:`.

The sign rule and the order, in `learned_from_gram`:

```python
values, vectors = numpy.linalg.eigh(gram / (rows - 1))
values, vectors = values[::-1].clip(min=0.0), vectors[:, ::-1]
components = vectors.T  # rows are components
signs = numpy.sign(components[numpy.arange(p), numpy.abs(components).argmax(axis=1)])
components *= signs[:, None]
```

- [ ] **Step 1: Write the failing tests** (`test_pca.py`), each against
  `sklearn.decomposition.PCA(svd_solver="covariance_eigh")` fitted on the same
  frame, `rel=1e-10` unless stated:
  - `test_pca_learns_scikit_learns_components_and_signs` (200 rows × 5
    correlated columns, `n_components=None` and `3`),
  - `test_pca_learns_scikit_learns_variances` (`explained_variance_`,
    `explained_variance_ratio_`, `singular_values_`, `noise_variance_`,
    `mean_`, `n_samples_`),
  - `test_pca_keeps_the_whole_decomposition` (the learned `weights` and
    `variance` of `n_components=2` equal those of `n_components=None`),
  - `test_pca_casts_integer_and_decimal_columns` (INTEGER, BIGINT,
    `DECIMAL(10, 2)` columns give the components of the same values as
    floats),
  - `test_pca_refuses_a_missing_value` (NULL from pandas; NaN inserted into a
    DuckDB table; match `"sq.impute"`),
  - `test_pca_refuses_an_infinite_value`, `test_pca_refuses_one_row`,
    `test_pca_refuses_a_text_column_by_name` (each matching `"Fix:"`),
  - `test__decompose.py::test_the_shortcut_is_the_general_form` (`repr`,
    `settings()` and store key equal those of `PCA(...)`),
  - `test__decompose.py::test_the_group_refuses_bad_settings`: `n_components`
    of `-1`, `1.0`, `"mle"`, `2.5`; `method="svd"`; a number positional; each
    `SqlearnError` with `"Fix:"`.
- [ ] **Step 2:** Run `uv run pytest tests/src/sqlearn/decomposition`;
  expected FAIL (`sq.decompose` missing).
- [ ] **Step 3:** Implement. The refusals of missing, infinite and one row
  are raised in `before_gram`, before any batch. The rule that turns
  `n_components` into `n_components_` (spec §4.1, `None`, a whole number or
  a fraction) is one helper here, which Task 5's `apply_row` reuses.
- [ ] **Step 4:** Run; expected PASS. Add `sqlearn.decompose`,
  `sqlearn.decompose.pca` and `sqlearn.decomposition.PCA` to
  `docs/reference/index.md`.
- [ ] **Step 5:** Checks; commit `feat: add sq.decompose.pca learning
  (#66)`.

### Task 5: Applying PCA (spec §4.1, §4.4)

**Files:**
- Modify: `src/sqlearn/decomposition/pca.py` (`apply_row`)
- Test: `tests/src/sqlearn/decomposition/test_pca.py`

**Interfaces:**
- `PCA.apply_row(xs, learned, values) -> Mapping[str, Expression]`: `pca0`,
  …, `pca{k-1}`, each `Σ weight·(x::DOUBLE − mean)` with the learned numbers
  as constants, divided by `max(sqrt(variance), eps)` when `whiten` (eps the
  machine epsilon of DOUBLE, as scikit-learn floors it). `k` is
  `n_components_`: `None` → `min(rows, p)`; a fraction → scikit-learn's
  `searchsorted(cumsum(ratios), fraction, side="right") + 1`; a whole number
  above `min(rows, p)` refused with scikit-learn's reason and a `Fix:`. A
  missing or infinite value in a row is refused when that row is fetched,
  as `Normalize._refusal` does.

- [ ] **Step 1: Write the failing tests**, each against scikit-learn's
  `transform` on the same frame, `rel=1e-9` on the outputs:
  - `test_pca_applies_as_scikit_learn_transforms` (`n_components` `None`,
    `2`, `0`),
  - `test_pca_names_its_outputs_as_scikit_learn` (on columns `id, a, b, c`
    with `cols=["a", "b", "c"]`, `columns_out_` is `["id", "pca0",
    "pca1"]`: the outputs take the first input's place; a clash with an
    existing `pca0` numbered by ADR 0035),
  - `test_pca_of_constant_columns_as_scikit_learn` (one constant column
    among others; all columns constant: the ratios NaN as scikit-learn's,
    with any warning it gives given as a `SqlearnWarning` with `Fix:`),
  - `test_pca_on_two_rows_as_scikit_learn`,
  - `test_pca_whitens_as_scikit_learn` (and with a constant column: no
    division by zero, outputs as scikit-learn's),
  - `test_pca_takes_a_fraction_of_the_variance` (a fraction met exactly by a
    cumulative ratio, `0.5` on two equal eigenvalues),
  - `test_pca_with_more_columns_than_rows` (10 rows × 20 columns:
    `n_components_` 10),
  - `test_pca_refuses_more_components_than_rows_or_columns`,
  - `test_pca_refuses_a_missing_value_at_apply` (learned on clean rows,
    applied to a row with NULL).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement `apply_row`.
- [ ] **Step 4:** Run `uv run pytest tests/src/sqlearn/decomposition`;
  expected PASS.
- [ ] **Step 5:** Checks; commit `feat: apply sq.decompose.pca in SQL
  (#66)`.

### Task 6: Pipelines, searches and saving (spec §2, §5.4, §7)

**Files:**
- Test: `tests/src/sqlearn/decomposition/test_pca_pipelines.py`,
  `tests/src/sqlearn/_saving/test_learned.py`
- Modify: `src/sqlearn/_saving/` only if a test shows a learned list of
  lists or a `weights` list is refused or let through wrongly.

- [ ] **Step 1: Write the failing or passing tests:**
  - `test_spec_examples_run` (spec §2's code, on a generated Parquet file),
  - `test_train_then_predict_matches_scikit_learn` (`scale`, `pca(3)`,
    `LogisticRegression`; the same predictions as scikit-learn's `Pipeline`
    of `StandardScaler`, `PCA(3, svd_solver="covariance_eigh")`, the same
    model),
  - `test_a_search_over_n_components_learns_each_fold_once` (as the
    feature-selection plan's Task 2 counts learns),
  - `test_pca_after_a_dynamic_step` (`encode.onehot` then `pca`; a later
    `sq.scale()` sees `pca0`, … only),
  - `test_save_then_load_gives_the_same_output`,
  - in `test_learned.py`, a crafted file for each PCA learned value:
    `weights` holding a string, a nested list, a 12-byte number, a bool, an
    int too large for a float; each refused by `sq.load` with its damaged
    message (HANDOFF's `sq.load` trap: probe every learned slot end to end).
- [ ] **Step 2:** Run them; fix only what fails, in the module the failure
  names.
- [ ] **Step 3:** Run `uv run pytest tests/src/sqlearn`; expected PASS.
- [ ] **Step 4:** Checks; commit `test: PCA in pipelines, searches and
  saved files (#66)`.

### Task 7: Validation (spec §7, ADR 0016)

**Files:**
- Create: `validation/sqlearn/decomposition/__init__.py`,
  `validation/sqlearn/decomposition/validate_pca.py`
- Generated: `validation/sqlearn/decomposition/pca.results.json`,
  `tests.json`

- [ ] **Step 1:** Write the runner as `validate_select.py` is written, with
  `_cases.measure_all`. Exact values: the covariance from `Fraction`s, and
  the eigenvalues and eigenvectors from `mpmath.eigsy` at `_cases.DIGITS`,
  signs by §4.3's rule. References: sqlearn, scikit-learn
  (`covariance_eigh`), numpy (`eigh` of `numpy.cov`). Datasets: `devdata`'s
  iris, wine and breast cancer, and generated ones (nearly collinear
  columns, a constant column, more columns than rows, values of magnitude
  1e8 with spread 1). Measured per eigenvalue and per output value; a
  component whose eigenvalue is within 1e-8 of a neighbour's is measured
  through its outputs only, with a note (spec §7).
- [ ] **Step 2:** Run it alone through
      `validation.__main__.main(["decomposition"], ROOT)`; set each bound from
      the worst sqlearn result, as the earlier areas set theirs; sqlearn passes
      every case.
- [ ] **Step 3:** `just verify`; commit the runner, its results and
  `tests.json`: `test: validate PCA against the exact values (#66)`.

### Task 8: Larger than memory (spec §3 rule 3, §7)

**Files:**
- Create: `validation/benchmarks/gram_reach.py`,
  `docs/benchmarks/gram-streaming.md`
- Test: `tests/src/sqlearn/decomposition/test_pca_large.py`

- [ ] **Step 1:**
      `test_pca_large.py::test_pca_learns_data_larger_than_the_memory_limit`
      (`@pytest.mark.slow`): a Parquet file of 2M rows × 50 columns written by
      DuckDB, learned at `SET memory_limit = '256MB'`; its components match
      numpy's `eigh` of DuckDB's own `covar_pop` matrix (`rel=1e-9`).
- [ ] **Step 2:** Run it with `uv run pytest -m slow -k larger`; expected
  PASS.
- [ ] **Step 3:** Write `gram_reach.py` from spec §6's measurements
  (12.5M × 200 at a 2 GB limit, peak memory by `resource.getrusage`, the
  agreement with `covar_pop`), run it on a quiet machine, and record the
  table in `gram-streaming.md`, linked from `docs/benchmarks/index.md`. If
  the machine is not quiet, record the load and say so (HANDOFF's waiting
  item for #46 is the precedent).
- [ ] **Step 4:** Checks; commit `test: learn PCA on data larger than
  memory (#66)`.

### Task 9: Documentation and state (spec §8, §11)

**Files:**
- Create: `docs/guide/reducing-columns.md`
- Modify: `docs/guide/index.md`, `docs/guide/from-scikit-learn.md`,
  `docs/architecture/overview.md` (3.3's areas), `GLOSSARY.md`, `CLAUDE.md`
  (the area list), `HANDOFF.md`

- [ ] **Step 1:** The guide page "Reducing columns", after "Selecting
  features": what PCA does, §2's examples, how it learns (the means in SQL,
  the batches into numpy, applying in SQL), whitening, the fraction form,
  and the refusals with their fixes. Add
  `PCA(n_components=3)` → `sq.decompose.pca(n_components=3)` to the mapping
  page.
- [ ] **Step 2:** `GLOSSARY.md`: **Gram step**: a step that learns from the
  matrix XᵀX of its centred input columns, built by the core in numpy from
  batches (ADR 0058). Describe the Gram learn where `overview.md` describes
  learning, and quote ADR 0002's and 0005's amendments wherever those rules
  are stated.
- [ ] **Step 3:** Rebuild the docs (`rm -rf docs/reference/generated
  docs/_build && just build-docs`); expected no warning.
- [ ] **Step 4:** `just verify`; expected PASS. Update `CLAUDE.md`'s area
  list ("Its tenth, decomposition (PCA), is built: spec …, plan …, ADRs
  0057–0058, summary in issue #66"), `HANDOFF.md` (just finished, next up),
  and the issue with a summary and any deferred findings.
- [ ] **Step 5:** Commit `docs: guide and state for decomposition (#66)`.

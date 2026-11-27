---
type: plan
tags: [datasets, generators, bundled-data, random-numbers, library-breadth]
summary: "Builds the datasets area: SplitMix64 random numbers in SQL, three bundled datasets and four generators under sq.datasets, each a DuckDB relation, with their validation."
related: [docs/specs/archived/library-datasets.md, docs/adr/0006-local-and-offline.md, docs/adr/0034-a-grouped-api.md]
---
# Library datasets: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sq.datasets` with `iris`, `wine`, `breast_cancer`, `blobs`,
`regression`, `classification` and `customers`, every one a DuckDB relation.

**Architecture:** A new package `src/sqlearn/datasets/`: `_random.py`
(SplitMix64 in SQL and in Python), `bundled.py` (the three CSV datasets),
`generated.py` (the four generators), `__init__.py` (the group). The
generators are SQL over `range(rows)`, built as text with every identifier
through `sqlearn._expr.quote`, run on `sqlearn._config.connection()`.

**Tech Stack:** Python 3.12+, DuckDB 2.0, pytest, uv, just; scikit-learn
1.9.1 in the dev group only (validation and the one-off copy of the CSVs).

**Spec:** `docs/specs/library-datasets.md`.

## Global Constraints

- Computation is SQL run by DuckDB; Python is the glue (ADR 0002). Python may
  draw a handful of constants from the seed (centres, coefficients, matrices),
  never a value per row.
- The only runtime dependency is `duckdb` (ADR 0004); nothing needs the
  network (ADR 0006). scikit-learn is used only in tests, validation and the
  one-off copy.
- Every function returns a `duckdb.DuckDBPyRelation` on
  `sqlearn._config.connection()`; the target column is named `target`, last.
- Settings: scikit-learn's names, except `rows=` (for `n_samples`) and
  `seed=` (for `random_state`, an `int`, default 0).
- Refusals: `SqlearnError` in the house form (what happened, `Why:`, `Fix:`).
- Random values are a pure function of `(seed, row, stream)`. Keys and
  uniforms are exact integer arithmetic: the same seed gives the same values
  bit for bit on any thread count, machine and DuckDB version. Normals go
  through `ln`, `cos` and `sqrt`, which libm does not promise to round alike
  on every platform or build: bit for bit on one machine (tested), the same
  within rounding elsewhere (ADR 0043).
- Test names read as sentences (`test_<behaviour>`), through the public seam
  (`sq.datasets.*`) unless a task names a private function.
- British English in prose, American spelling in identifiers (ADR 0010).
- Every new module gets its test module; every public `datasets` module its
  validation (`just check-mirror`, extended in Task 1).
- Commits: `feat: ...`, `test: ...`, `docs: ...`; no AI attribution.
- Before each commit: `just fmt`, `just check`, `just test`. Before the
  branch is called done: `just verify`, and the docs rebuilt clean
  (`rm -rf docs/reference/generated docs/_build && just build-docs`).

## Review Focus

1. **SQL that grows faster than linearly.** SplitMix64 reads each
   intermediate value twice (`z ^ (z >> 30)`): written as nested text, the
   SQL doubles at every step. Task 1 tests that the SQL of 1, 10 and 100
   uniforms grows linearly.
2. **`rows=0` and `rows=1`.** `rows=0` is refused (scikit-learn refuses it
   too); `rows=1` gives one row. Task 3 tests both.
3. **A slice equals the whole.** The first 1,000 rows of a 1,000,000-row
   relation equal a 1,000-row relation, and 1 thread equals 8. Task 3 tests
   it for `blobs`; Task 4 for `classification`.
4. **Huge `rows`.** `rows=10**12` creates the relation at once and
   `limit(3)` returns at once (no `count(*)` or `ORDER BY` over the whole).
   Task 3 tests it.
5. **A column named `target` among the features.** No generator or dataset
   makes one; `customers`' `churned` is renamed. Task 5 tests the columns.

---

### Task 1: SplitMix64 in SQL and Python, and the group

**Files:**

- Create: `src/sqlearn/datasets/__init__.py`, `src/sqlearn/datasets/_random.py`
- Create: `tests/src/sqlearn/datasets/test__random.py`
- Modify: `src/sqlearn/__init__.py` (import and `__all__`: `datasets`)
- Modify: `justfile` `check-mirror` (add `datasets|datasets/*` to the
  validated directories)
- Create: `docs/adr/0045-datasets-are-relations-built-in-sql.md` (the
  spec's section 3 and 4 as a decision: the group and names, relations,
  `rows=`/`seed=`, `target`, SplitMix64 not `hash()`/`random()`, bundled
  CC BY 4.0 data, no fetchers), listed in `docs/adr/index.md`

**Interfaces (produces):**

- `splitmix64(x: int) -> int`: the standard step, all arithmetic mod 2**64:
  `z = x + 0x9E3779B97F4A7C15; z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EB; return z ^ (z >> 31)`.
- `key(seed: int, row: int, stream: int) -> int`:
  `splitmix64(splitmix64(splitmix64(seed mod 2**64) ^ row) ^ stream)`.
- `uniform(seed: int, row: int, stream: int) -> float`:
  `(key(...) >> 11) * 2.0**-53`.
- `normal(seed: int, row: int, stream: int) -> float`: Box-Muller,
  `sqrt(-2 * log(1 - u1)) * cos(2 * pi * u2)` with
  `u1 = uniform(seed, row, 2 * stream)`,
  `u2 = uniform(seed, row, 2 * stream + 1)`.
- `CONSTANT_ROW = 2**63`: constants drawn in Python use rows
  `CONSTANT_ROW + i`, so they never meet a data row.
- `random_columns(seed, rows, uniforms, normals) -> str` (`seed: int`,
  `rows: int`, `uniforms` and `normals: Mapping[str, int]`, name to stream):
  the SQL of a query over `range(rows)` with column `i` (the row) and one DOUBLE
  column per name: a uniform of the given stream, or a normal. The generators
  select from it. It computes each SplitMix64 step as a column of a subquery
  over the previous one, so its text grows linearly with the columns (Review
  Focus 1); the multiplications go through `UHUGEINT` and
  `% 18446744073709551616`, results cast back to `UBIGINT`.

- [ ] **Step 1: Write the failing tests**:
  - `test_splitmix64_matches_its_published_values`: the first three outputs
    of a SplitMix64 stream from state 0, `splitmix64(k * 0x9E3779B97F4A7C15
    mod 2**64)` for k = 0, 1, 2, are `0xE220A8397B1DCDAF`,
    `0x6E789E6AA1B965F4`, `0x06C45D188009454F` (checked).
  - `test_sql_uniforms_equal_the_python_reference`: `random_columns(7, 1000,
    {"u": 3}, {"n": 5})` fetched equals `uniform(7, i, 3)` and
    `normal(7, i, 5)` for every `i`, bit for bit (`==` on the floats).
  - `test_random_sql_grows_linearly`: the SQL length for 1, 10 and 100
    uniform columns: `len(100) / len(10) < 12`.
  - `test_the_same_seed_gives_the_same_values_on_any_thread_count`: one
    thread vs eight (`SET threads`), 100,000 rows, equal.
  - `test_sq_datasets_is_a_group`: `sq.datasets` is importable and listed in
    `sq.__all__`.
- [ ] **Step 2: Run them and watch each fail.**
- [ ] **Step 3: Implement** as in Interfaces; `__init__.py` holds the
  module docstring and, for now, nothing else public.
- [ ] **Step 4: Measure**
      `random_columns(0, 10**7, {}, {f"n{k}": k for k in range(20)})` summed
      over every column, idle, and record the time in the report (no limit
      asserted; it tells Tasks 3-5 the cost of a normal).
- [ ] **Step 5: Run the whole suite**, `just check` (the mirror check now
  asks validation for public `datasets` modules; `_random.py` is private).
- [ ] **Step 6: Commit**
      `feat: draw repeatable random numbers in SQL for the datasets`.

### Task 2: The bundled datasets

**Files:**

- Create: `src/sqlearn/datasets/data/iris.csv`, `wine.csv`,
  `breast_cancer.csv`, `README.md` (source, creators, citation and licence
  per dataset, from scikit-learn's `datasets/descr/*.rst`: UCI Machine
  Learning Repository, CC BY 4.0)
- Create: `src/sqlearn/datasets/bundled.py`; export in `datasets/__init__.py`
- Create: `tests/src/sqlearn/datasets/test_bundled.py`
- Create: `validation/sqlearn/datasets/__init__.py`,
  `validation/sqlearn/datasets/validate_bundled.py`; add it to
  `validation/__main__.py`'s `RUNNERS`
- Modify: `docs/reference/index.md` (the three functions)

**Interfaces (produces):** `iris() -> DuckDBPyRelation`,
`wine() -> DuckDBPyRelation`, `breast_cancer() -> DuckDBPyRelation`. Columns:
scikit-learn 1.9.1's `feature_names` in order (DOUBLE), then `target`
(BIGINT). The CSVs are written once by a throwaway script from
`load_*(as_frame=True).frame` (not committed); read with `read_csv` and
explicit `columns=` types; the file path from `importlib.resources`.

- [ ] **Step 1: Write the failing tests**:
  `test_iris_has_150_rows_of_4_features_and_a_target` (names, types, count,
  `target` values {0, 1, 2}); the same for wine (178,
  13) and breast cancer (569, 30); `test_bundled_datasets_equal_scikit_learns`
      (each, against `load_*(as_frame=True).frame`,
      `pandas.testing.assert_frame_equal` with `check_exact=True`, dtypes
      aside).
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Write the CSVs and `README.md`, implement `bundled.py`.**
  Check the wheel carries the data: `uv build` then list the wheel's files.
- [ ] **Step 4: Validation**: `validate_bundled.py` in the shape of the other
  runners (`cases()` returning the house records; read one, e.g.
  `validation/sqlearn/metrics/validate_accuracy.py`): one case per dataset,
  0 ULPs worst over every value.
- [ ] **Step 5: Run the whole suite**, the new runner, and commit
  `feat: bundle iris, wine and breast cancer as relations`.

### Task 3: `blobs` and `regression`

**Files:**

- Create: `src/sqlearn/datasets/generated.py`; export in `__init__.py`
- Create: `tests/src/sqlearn/datasets/test_generated.py`
- Create: `validation/sqlearn/datasets/validate_generated.py`; in `RUNNERS`
- Modify: `docs/reference/index.md`

**Interfaces:**

- Consumes: `random_columns`, `uniform`, `CONSTANT_ROW` (Task 1).
- Produces, each returning a `DuckDBPyRelation`:

  ```python
  def blobs(
      rows: int = 100,
      n_features: int = 2,
      centers: int | Sequence[Sequence[float]] = 3,
      cluster_std: float | Sequence[float] = 1.0,
      center_box: tuple[float, float] = (-10.0, 10.0),
      seed: int = 0,
  ) -> DuckDBPyRelation: ...
  def regression(
      rows: int = 100,
      n_features: int = 100,
      n_informative: int = 10,
      bias: float = 0.0,
      noise: float = 0.0,
      seed: int = 0,
  ) -> DuckDBPyRelation: ...
  ```

  and a shared private `_check_rows(rows: object) -> int` and
  `_check_seed(seed: object) -> int` raising the house refusals, used by Tasks 4
  and 5.

Values as the spec's section 5. Streams: number them per function in one
documented place (a docstring table), so no two values of one row share a
stream.

- [ ] **Step 1: Write the failing tests**:
      `test_blobs_gives_rows_features_and_a_target`;
      `test_blobs_rows_cluster_round_their_centres` (10,000 rows,
      `cluster_std=0.1`, given `centers=[[0, 0], [5, 5]]`: each row within 1 of
      its target's centre);
      `test_regression_target_is_the_linear_model_without_noise` (`noise=0`:
      least squares on 1,000 rows recovers a target with residual below 1e-9,
      exactly `n_informative` non-zero coefficients);
      `test_one_row_is_given_and_zero_rows_are_refused` (Review Focus 2);
      `test_a_slice_equals_the_whole` (Review Focus 3, `blobs`);
      `test_a_trillion_rows_are_created_at_once` (Review Focus 4: under 1 s,
      `limit(3)` 3 rows); a refusal test per bad setting of the spec's section 3
      that these two take, each asserting `Why:` and `Fix:`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Validation**: `validate_generated.py` with the uniform's and
  the normal's moments and quantiles, and `blobs`' and `regression`'s
  properties of the spec's section 7, at 1,000,000 rows; each bound several
  standard errors wide, its reason in a comment.
- [ ] **Step 5: Run the whole suite**, the runner, and commit
  `feat: generate blobs and regression data in SQL`.

### Task 4: `classification`

**Files:** Modify `src/sqlearn/datasets/generated.py`,
`tests/src/sqlearn/datasets/test_generated.py`,
`validation/sqlearn/datasets/validate_generated.py`,
`docs/reference/index.md`.

**Interfaces:**

- Consumes: Task 3's `_check_rows`, `_check_seed`, Task 1's helpers.
- Produces:

  ```python
  def classification(
      rows: int = 100,
      n_features: int = 20,
      n_informative: int = 2,
      n_redundant: int = 2,
      n_classes: int = 2,
      n_clusters_per_class: int = 2,
      weights: Sequence[float] | None = None,
      flip_y: float = 0.01,
      class_sep: float = 1.0,
      seed: int = 0,
  ) -> DuckDBPyRelation: ...
  ```

As scikit-learn 1.9.1's `make_classification` (read its source for the
hypercube vertices, the per-cluster matrix `2 * rand - 1`, the redundant
combinations `2 * rand - 1`, and `weights` with fewer entries than classes),
less the settings the spec leaves out. Each row draws its cluster from one
uniform against the cumulative cluster weights (a class's weight shared
equally by its clusters).

- [ ] **Step 1: Write the failing tests**:
      `test_classification_gives_its_columns_in_order` (x0..x19, target; BIGINT
      classes 0..n_classes-1);
      `test_classification_classes_follow_their_weights` (100,000 rows,
      `weights=[0.8, 0.2]`, `flip_y=0`: shares within 0.01);
      `test_redundant_features_are_combinations_of_the_informative_ones` (least
      squares residual below 1e-9); `test_flip_y_flips_that_share`
      (`flip_y=0.5`, two classes, against the same seed with `flip_y=0`: the
      labels differ in about a quarter of rows, within 0.01: half are redrawn,
      half of those land elsewhere); `test_a_slice_equals_the_whole` for
      classification; a refusal test per bad setting in the spec's section 3.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Validation** cases for class shares and flip rate.
- [ ] **Step 5: Whole suite, runner, commit**
  `feat: generate classification data in SQL`.

### Task 5: `customers`, the example and the guide

**Files:**

- Modify: `src/sqlearn/datasets/generated.py`, its test and validation
- Modify: `examples/plot_tuning.py` (its customers from
  `sq.datasets.customers(rows=5_000, seed=0)` written to Parquet; the numpy
  block goes; the prose says where the data comes from)
- Create: `docs/guide/datasets.md` (what each function gives, the seed, the
  relation is a query, writing one to Parquet, larger than memory), listed in
  `docs/guide/index.md`
- Modify: `docs/reference/index.md`

**Interfaces (produces):**
`customers(rows: int = 1000, seed: int = 0) -> DuckDBPyRelation`, columns `age`,
`income`, `city`, `plan`, `target` with the types and distributions of the
spec's section 5.

- [ ] **Step 1: Write the failing tests**:
      `test_customers_has_its_columns_and_types` (Review Focus 5: no other
      column named `target`); `test_customers_have_the_promised_gaps_and_shares`
      (100,000 rows: a tenth of `age` and a twentieth of `income` NULL within
      0.005; plan shares within 0.01);
      `test_a_pipeline_learns_customers_end_to_end` (impute, one-hot, scale,
      then `sq.Model` of scikit-learn's `LogisticRegression` trains on 2,000
      rows and predicts better than the majority class on 1,000 others);
      `test_a_pipeline_learns_ten_million_rows_under_64_mb` (`sq.set_config` of
      a 64 MB budget, `sq.impute.median()` then `sq.scale.standard()` learned
      from `customers(rows=10**7)`; mark it as the suite marks its other slow
      large-data tests, read `tests/` for the marker).
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement**; rewrite the example; write the guide page.
- [ ] **Step 4: Validation** cases for the missing and category shares.
- [ ] **Step 5: Whole suite, `just build-docs`, the example runs
  (`uv run python examples/plot_tuning.py`), commit
  `feat: generate a customers table with gaps and text`.

### After the tasks

- [ ] `just verify`; the docs rebuild clean.
- [ ] `CLAUDE.md`'s "Done" line names the datasets area (spec, plan, ADR
  0045, summary issue); `HANDOFF.md` updated; `docs/architecture/overview.md`
  unchanged unless it lists areas done.
- [ ] A summary issue for the area (as #30, #33, #34) with the rulings and
  deferred findings.

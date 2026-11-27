---
type: note
tags: [testing, validation, scikit-learn-parity, sqlearn, tolerances, snapshots]
summary: "Audit of the tests and correctness validation in the sqlearn-desktop attempt: parity tolerances, snapshots, gaps, and the impute-then-scale defect."
related: [docs/questions/earlier-attempts/tomosius-sqlearn/notes/C-tests.md]
mdindex: [type=edb465, tags=16c85c, summary=317b49, related=1ee240]
---
# C: Tests and validation in Tomosius/sqlearn (sqlearn-desktop)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-desktop`.
Citations `OLD:path:Lnn` are relative to it. "Inference" marks my reading, not a
stated fact. Nothing was run; no `.env` was opened; no read hung. Compiled
`__pycache__` files were listed, not read.

## Summary

- Correctness against scikit-learn was checked by about 40 pytest functions
  that fit a tiny DuckDB table, run `Pipeline.fit_transform`, and compare with
  the scikit-learn class on the same numbers using `np.testing.assert_allclose`.
  That is roughly 1.5% of about 2,600 test functions in 52 test files. The rest
  are contract, constructor, AST, repr, clone and pickle tests, plus
  hand-computed expectations.
- Only six transformers were ever compared with scikit-learn: StandardScaler,
  MinMaxScaler, MaxAbsScaler, RobustScaler, Normalizer, and (less) Imputer,
  OneHotEncoder, OrdinalEncoder. Window, datetime, string, outlier, target,
  frequency, hash, feature-selection and data (merge, concat, lookup) steps
  have no external reference at all.
- No Decimal, Fraction or mpmath ground truth, no ULP bound, no recorded
  measurement behind any tolerance. Tolerances are hand-picked: `atol=1e-10`
  (77 uses), `rtol=1e-10` (14), `rtol=1e-6` (14), and `atol=0.5` for every
  RobustScaler comparison.
- No datasets and no network. Every table is a `VALUES` literal (5 to 7 rows)
  or a seeded `numpy.random.default_rng` array of 50 to 1000 rows inserted row
  by row. Nothing is larger than memory, and nothing probes the out-of-core
  claim.
- No property tests. `hypothesis` is a dev dependency and `CLAUDE.md` says it is
  "used in test files", but no test file imports it.
- Nothing is marked or gated: no `compare` marker, `slow` and `integration`
  markers are declared and never used, and the only skip is the snapshot
  `--update-snapshots` path. `filterwarnings = error` is the one strict gate.
- The suite contains direct evidence of the "learn from raw input" defect: the
  Imputer-then-Scaler snapshot learns the scaler's mean from the raw column
  while the imputer fills a different value, and the test loosens its tolerance
  to `atol=0.1` to hide it.
- Compared with v0.4: this attempt has the same shape, smaller, and without
  v0.4's improvements (datasets, `PRECISION.md`, float32, compare marker,
  Hypothesis). v0.4 inherited the habit of hand-picked tolerances and parity
  tests without measurement. Nothing here is better than v0.4.
- Worth keeping: the divergence-test pattern (assert both the scikit-learn
  value and sqlearn's value where they differ, with a comment saying why), odd
  row counts to dodge interpolation, golden SQL snapshots with a
  `--update-snapshots` flag, a SQL-reserved-words test, and a no-NULLs-after-
  imputation check.

## How correctness was checked

Layers, with counts from `def test_` per file (inference: grep count, not a
collected total; parametrised tests count once):

- **Contract and unit tests** (the bulk). Constructor validation, `get_params`,
  `set_params`, repr, clone independence, pickle round-trip, `columns=`
  selection, error messages. Examples: `OLD:tests/core/test_transformer.py` (112
  tests), `OLD:tests/core/test_schema.py` (164),
  `OLD:tests/core/test_pipeline.py` (110, `+` operators from
  `OLD:tests/core/test_pipeline.py:L440-L580`).
- **AST tests.** Assert the sqlglot node tree, for example that StandardScaler
  is `Div(Paren(Sub(...)), Nullif(...))`
  (`OLD:tests/integration/test_sql_ast.py:L47-L70`) and that many scalers expose
  `AVG`/`STDDEV_POP` in their discovery output
  (`OLD:tests/scalers/test_standard.py:L98`, `L135`). These check how the SQL is
  built, not whether the numbers are right.
- **Golden SQL snapshots.** Six one-line `.sql` files
  (`OLD:tests/integration/snapshots/`) compared as text. The helper fails when
  a snapshot is missing and skips (not passes) after a rewrite
  (`OLD:tests/integration/test_sql_snapshots.py:L38-L50`). This is stricter than
  v0.4, where the first run auto-wrote and passed. Snapshot values embed learned
  floats (for example `1.4142135623730951`), so a snapshot also freezes the
  learned statistics (`OLD:tests/integration/snapshots/standard_scaler.sql`).
- **Inline SQL pattern tests.** `assert "NULLIF" in sql_upper`,
  `"COALESCE"`, `"WITH" not in sql_upper` for an expression-only pipeline
  (`OLD:tests/integration/test_sql_snapshots.py:L138-L155`, inference from the
  grep of asserts). These are substring checks.
- **scikit-learn parity tests** (below).
- **Hand-computed expectations** for everything without a reference: window
  functions (`pytest.approx(10.0)` for a rolling mean,
  `OLD:tests/features/test_window.py:L634-L640`), rolling std
  `8.16496580927726` with `rel=1e-4` (`OLD:tests/features/test_window.py:L816`),
  outlier bounds (`OLD:tests/features/test_outlier.py:L212-L258`).
- **Edge cases:** SQL reserved-word column names `order`, `group`, `select`
  (`OLD:tests/integration/test_sql_keywords.py:L19-L90`), constant column,
  single row, all-NULL column, `1e100` values
  (`OLD:tests/scalers/test_standard.py:L527`).
- **Tooling tests:** `OLD:tools/test_projectdb.py` (28 tests) exercises the
  project-knowledge database (`refresh`, `export`, `dump`, `restore`). It is
  project tooling, not library validation; it writes `project.duckdb` in the
  repository root when run (`OLD:tools/test_projectdb.py:L20-L27`, inference
  from `DB_PATH` use). `OLD:tests/test_init.py:L5` pins
  `__version__ == "0.2.0"`.

### scikit-learn parity tests

Two forms exist, and both are inline literals, not shared fixtures:

1. Central file `OLD:tests/integration/test_sklearn_equivalence.py` (11 tests,
   329 lines). It builds a `VALUES` table, runs the sqlearn pipeline, reads the
   same table back with `fetchall()` into numpy, runs the scikit-learn class on
   that array, and calls `assert_allclose(rtol=1e-6)`
   (`OLD:tests/integration/test_sklearn_equivalence.py:L60-L72`). Covered:
   StandardScaler default, `with_mean=False`, `with_std=False`; Imputer mean,
   median, most_frequent (object array, `missing_values=None`, exact equality at
   `L256-L275`); OneHotEncoder on 3 categorical columns and a single category.
2. Per-transformer `TestSklearnEquivalence` / `Test*Equivalence` classes inside
   `tests/scalers/test_{standard,minmax,maxabs,robust,normalizer}.py` (3 to 4
   tests each: basic, parameter variants, and a seeded multi-column array with
   scale spread `[1, 10, 100, 0.1, 50]` and offsets `[0, 50, -100, 3, 200]`,
   `OLD:tests/scalers/test_standard.py:L625-L630`), plus two tests in
   `OLD:tests/encoders/test_ordinal.py:L415-L460`.

The sklearn import is a function-local `from sklearn... import` in the scaler
files and top-level in the central file. Only `test_ordinal.py` uses
`pytest.importorskip("sklearn.preprocessing")` (`L417`, `L440`). scikit-learn is
in the `dev` dependency group (`OLD:pyproject.toml:L256-L267`, inference from
the grep), so nothing skips for a missing reference; the tests just do not run
in an environment without the dev group.

## Tolerances and references

Counted across `tests/` and `tools/` (grep of `rtol=`/`atol=`):

| Tolerance | Count | Where |
|---|---|---|
| `atol=1e-10` | 77 | scalers, features, keywords, parity |
| `rtol=1e-10` | 14 | (inference: window/arithmetic) |
| `rtol=1e-6` | 14 | `test_sklearn_equivalence.py` |
| `atol=0.5` | 4 | RobustScaler vs scikit-learn only |
| `atol=0.1` | 3 | pipeline "mean near zero" checks |
| `atol=1e-15` | 1 | one-off |
| `pytest.approx` `rel=1e-4` | 1 | rolling std |

- The reference is always scikit-learn's own output on the same float64 array.
  There is no higher-precision reference. A tolerance of `1e-10` is plausibly
  one to four orders above DuckDB's summation error (v0.4 later measured about
  1e-12 on 20,000 rows), but nothing in this attempt measured it (inference).
- `atol=0.5` for RobustScaler (`OLD:tests/scalers/test_robust.py:L412`,
  `L432`, `L452`, `L474`) is far too loose: robust-scaled values live in
  roughly [-3, 3], so a 0.5 error would hide a wrong quantile definition. The
  comment says "enough data points that quantile interpolation differences
  vanish" (`L398`). DuckDB `quantile_cont` and scikit-learn's default
  percentile both interpolate linearly (inference), so the loosening was a
  workaround for an unmeasured gap, and it is the one place where the suite
  admits the two libraries differ. Result: RobustScaler parity is effectively
  unverified.
- Absolute only; `rtol=1e-6` in the central file is the one relative bound and
  is applied to z-scores that can be near zero (inference: `assert_allclose`
  with `atol=0` makes near-zero entries fail on tiny error, so these pass only
  because the 7-row inputs have clean values).
- Distinct dtype handling: none. Every comparison is DOUBLE; no float32,
  integer or DECIMAL input appears in the parity tests (inference from the
  fixtures, which all use `1.0`-style literals or `DOUBLE` columns).

## Datasets

- No dataset files, no `datasets/` folder, no downloaders, no network call
  anywhere in `tests/` (a grep for `fetch_`, `load_iris`, `urlopen`,
  `requests`, `http` found nothing).
- Shared fixtures are literal: a 7-row numeric table "odd row count ensures
  median tests avoid interpolation differences", with NULLs in two columns
  (`OLD:tests/conftest.py:L38-L57`); a 7-row categorical table with clear modes
  and no ties (`L60-L78`); a mixed table with NULLs (`L81-L96`).
- Larger arrays: `default_rng(42)` (and 123/456/789 in RobustScaler) of 50 to
  1000 rows, inserted one row at a time with `INSERT` in a Python loop
  (`OLD:tests/scalers/test_standard.py:L631-L634`). Nothing exceeds 1,000 rows.
- Consequence: the suite needs no network, which matches ADR 0006, but it also
  never tests scale. There is no performance, memory or large-table test.

## Gaps and false confidence

- **The Impute-then-Scale defect is in the tests and was papered over.**
  `test_numeric_columns_scaled` states in its own docstring: "imputed NULL
  values shift the mean slightly from zero, since the scaler learns stats from
  original data but transform includes the imputed values", and asserts only
  `atol=0.1` (`OLD:tests/integration/test_pipeline_transformers.py:L59-L71`).
  The golden SQL shows it: `(COALESCE("quantity", 35.0) - 32.5)` in
  `OLD:tests/integration/snapshots/full_pipeline.sql`, where 35.0 is the median
  fill and 32.5 is the mean of the raw column. The snapshot freezes the wrong
  behaviour as "expected". `test_coalesce_nested_in_arithmetic` asserts only
  that the SQL contains `COALESCE` and no `WITH`
  (`OLD:tests/integration/test_pipeline_transformers.py:L129-L151`). There is
  no scikit-learn `Pipeline([SimpleImputer, StandardScaler])` comparison, which
  would have failed. This is the strongest single piece of evidence in the
  attempt.
- **Divergences are accepted, not resolved.** Constant column: scikit-learn
  returns 0, sqlearn returns NULL (`NULLIF`); the test asserts both and calls
  them "both valid"
  (`OLD:tests/integration/test_sklearn_equivalence.py:L102-L131`). All-NULL
  column: scikit-learn drops it, sqlearn leaves it NULL (`L155-L196`). Single
  row: all NaN (`L133-L149`). These are honest and documented, which is better
  than silence, but they are departures that the ADR-0003 rule would require a
  decision for.
- **Tests compare against themselves.** Several "equivalence" checks are mean
  near 0 and std near 1 (`OLD:tests/scalers/test_standard.py:L540-L555`), which
  is a property of the algorithm, not of scikit-learn.
- **Most steps have no reference.** Window, datetime, string, outlier, target,
  frequency, hash, SelectKBest, DropCorrelated, Sample, merge, concat, lookup
  have 70 to 170 tests each of constructor and SQL-shape checks, but values are
  asserted against hand-worked numbers only. SelectKBest accepts
  `score_func="f_classif"` and `"mutual_info"` in constructor tests
  (`OLD:tests/feature_selection/test_kbest.py:L38-L41`, `L35`) and never
  compares scores with `sklearn.feature_selection` (grep: no sklearn import in
  `tests/feature_selection/`).
- **OneHotEncoder parity is on 7 rows and 3 columns** with the alphabetical
  order assumed (`OLD:tests/integration/test_sklearn_equivalence.py:L281-L307`).
  No unknown-category, `drop`, `handle_unknown` or NULL-category parity.
- **Imputer parity only for mean, median (odd count) and most_frequent with no
  ties.** Even-count median, ties in mode, `constant` strategy, all-NULL, and
  mixed dtypes are not compared; the fixture is chosen to avoid them
  (`OLD:tests/conftest.py:L38-L43`). The tests dodge the known difference
  instead of testing it.
- **No property tests** despite the stated standard
  (`OLD:CLAUDE.md:L235`, "Used in test files") and the dev dependency. No
  generated data, no invariants (idempotence of `transform`, order independence,
  fit on a permutation, scale invariance).
- **No mutation result.** `mutmut` is in the dev group and `make mutant`, but no
  stored score; `CLAUDE.md` demands "zero surviving mutants in compiler.py and
  transformer.py" (`OLD:CLAUDE.md:L201-L202`) with no evidence it was met.
- **No CI file in this snapshot.** `ls -a` of OLD shows no `.github/` and no
  `.pre-commit-config.yaml`; the gate is `make check` run by hand
  (`OLD:Makefile:L33-L44`; `make test` is `pytest --failed-first -x`).
  Coverage has no `fail-under` in `pyproject.toml` (inference from the section
  at `OLD:pyproject.toml:L222-L245`); only docstring coverage has one (95).
  `test/sqlearn`, the git copy, may differ; it was not read.
- **Process claims exceed the suite.** `CLAUDE.md` demands "All 11 mandatory
  tests + cross-library validation" per new transformer
  (`OLD:CLAUDE.md:L179`); the cross-library part exists for six classes.
- **Stub and vulture residue.** `OLD:vulture_whitelist.py:L5-L20` whitelists
  unused parameters (`y_column`, `exprs`, `backend`, `batch_size`, `dialect`)
  "used when Pipeline/Compiler/Backend land". It is a dead-code check, not
  validation, and shows API parameters declared before the code used them
  (inference).
- **Snapshot weakness.** Snapshots freeze floats printed to 17 digits, so a
  harmless summation change in DuckDB would fail them, and an incorrect value
  accepted once is locked in. There is no snapshot of results, only of SQL.
- **Warnings gate is global.** `filterwarnings = ["error", ...]`
  (`OLD:pyproject.toml:L205-L210`) makes any deprecation fail the suite; the
  only suppression added is for sqlglot-rs. This is good hygiene (keep).

## Against v0.4

Compared with `D-validation.md` of v0.4 (which came after this attempt):

- **Inherited by v0.4:** pytest + `assert_allclose` parity against scikit-learn
  as the main check; hand-picked `1e-10`-style tolerances (v0.4 had 164 uses of
  `atol=1e-10`; here 77); the scikit-learn-in-dev-group arrangement; sqlglot AST
  shape tests; SQL snapshot tests; the "same tiny `VALUES` table" fixture
  habit; the stated standard that outruns the enforced one.
- **Improved by v0.4:** real datasets (iris, housing, titanic) and a measured
  tolerance for Scale (`PRECISION.md`, 1e-11/1e-14); float32 and magnitude tests
  (1e15/1e-15); a `compare` marker and Hypothesis for SQL structure; a
  verification ledger; a written three-tier reference idea (exact, library,
  SUT). Here none exist: no markers, no `PRECISION.md` analogue, no datasets,
  no Hypothesis.
- **Worse in v0.4, better here:** snapshot behaviour. This attempt fails on a
  missing snapshot and skips after rewriting; v0.4 auto-wrote and passed. This
  attempt has no dataset tests that silently skip in CI, because it has none.
  It also documents divergences (constant, all-NULL, single row) in the test
  itself instead of a separate file; arguably more discoverable.
- **Same failure, earlier:** the loosened tolerance (`atol=0.5`, `atol=0.1`)
  to make a failing comparison pass is the same pattern v0.4 showed when it
  loosened `rtol=1e-14` after housing failed.
- Net: v0.4 is a refinement of this approach, not a different method. The
  method the new project wants (exact reference, measured bound, enforced in the
  gate) is absent from both.

## New against the baseline

- Direct test-level evidence of the staged-fit defect (a new source for the
  "How fit runs" bullet): `OLD:tests/integration/snapshots/full_pipeline.sql`
  plus the docstring at
  `OLD:tests/integration/test_pipeline_transformers.py:L59-L71`. The defect was
  seen, described in a docstring, and tolerated with `atol=0.1`.
- A third kind of "false pass": the tolerance is widened until the test passes
  (`atol=0.5`, RobustScaler), with a comment instead of a measurement.
- Accepted divergences from scikit-learn as test content: constant column gives
  NULL not 0, all-NULL column stays NULL, single row gives NaN
  (`OLD:tests/integration/test_sklearn_equivalence.py:L102-L196`). The new
  library must decide each deliberately (ADR 0003 territory), not inherit
  `NULLIF`.
- The test fixtures are chosen to avoid known differences (odd row count for the
  median, no ties for the mode) rather than to expose them
  (`OLD:tests/conftest.py:L38-L43`, `L60-L65`). So the "all parity passes"
  statement carries no information about even counts or ties.
- `tools/projectdb.py` (1,392 lines) plus its test are a project knowledge
  database (AST scan of the source, markdown parsing of backlog and ideas, git
  churn) loaded into DuckDB for an MCP server
  (`OLD:tools/projectdb.py:L1-L18`). It is process tooling that grew with the
  repository; this supports "plans and standards outgrew the product" with a
  concrete size, and the test file mutates the real `project.duckdb`.
- A global `filterwarnings = error` is the only enforced gate that is stricter
  than anything the baseline records.

## Contradicts the baseline

- The baseline says validation used "datasets downloaded over the network".
  This attempt did not: it has no datasets and no network use. (The baseline
  came from `sqlearn_000` and v0.4; this attempt is the oldest of the line, so
  the habit began later.)
- The baseline says parity tests "skipped". Here only one file
  (`test_ordinal.py`) can skip, via `importorskip`; the others fail hard if
  scikit-learn is absent. No silent skipping exists.
- The baseline says a "strong method was written". Not here: this attempt wrote
  only a sentence ("compare with sklearn/scipy where possible",
  `OLD:CLAUDE.md:L200`). The strong method arrived in v0.4. So the order is
  weak-method-weakly-applied, then strong-method-weakly-applied.

## Confirms the baseline

- "Hand-picked or correlation-only tolerances": confirmed, with `atol=0.5` and
  `atol=0.1` as the extreme cases and no measurement behind any value.
- "Validators outside the gate; method never enforced": confirmed, with no CI,
  no coverage floor, no mutation score, and `make test` as `-x --failed-first`.
- "Learned a later step's statistics from raw input": confirmed in SQL form
  (`full_pipeline.sql`, `composition.sql`: scaler mean and std over the raw
  column).
- "Failures: float literals never checked": confirmed. Learned statistics are
  inlined as 17-digit float literals in the SQL
  (`OLD:tests/integration/snapshots/standard_scaler.sql`), and tests only
  compare snapshots of those strings, never round-trip or re-run them.
- "Portability was never tested beyond parsing": confirmed.
  `to_sql(dialect= "postgres")` is checked to return a `str` only
  (`OLD:tests/scalers/test_standard.py:L609-L614` in the snapshot class,
  inference from the grep of `test_sql_custom_dialect`).
- "Plans and standards outgrew the product": confirmed (`CLAUDE.md` rules,
  subagent contract, `ideas/`, `architecture/INDEX.yaml`, `projectdb.py`).

## Worth keeping

For the new validation method (inference, not decisions):

- The **divergence test**: assert both the scikit-learn value and the sqlearn
  value where they differ, with a one-line reason. Pair each with a recorded
  decision, so a divergence is a documented departure, not a surprise.
- **Mirror fixtures built from the same rows**: read the table back with
  `fetchall()` and feed scikit-learn that exact array, so both sides see
  identical floats.
- **Fixtures that expose known differences** instead of avoiding them: even row
  counts and mode ties are not to be dodged; they are cases to include.
- **Golden SQL snapshots** with an explicit `--update-snapshots` flag and
  "missing snapshot fails". Keep only for SQL shape, not for validation of
  numbers.
- **`filterwarnings = error`** as part of the gate.
- **SQL reserved-word column names** (`order`, `group`, `select`) as a standing
  edge-case fixture.
- **Seeded wide-spread data** (scales `[1, 10, 100, 0.1, 50]`, offsets
  `[0, 50, -100, 3, 200]`): a cheap way to catch scale-dependent error.
- **A pipeline-level reference check** that the old suite never wrote:
  `Pipeline([SimpleImputer, StandardScaler])` of scikit-learn against sqlearn's
  one-query pipeline. It would have failed here.

Do not keep: `atol=0.5` and other widened bounds, tolerances without a
measurement, substring SQL checks as evidence of correctness, "mean near zero"
as equivalence, constructor-test volume as a measure of coverage.

## Files covered

Legend: [x] read in full or in the relevant part, [~] skimmed by grep and
sampled. Counts are `def test_` per file. Cache files (`__pycache__/*.pyc`, 41
files) are compiled output of the files below and were listed only.

### Root, conftest, tools

- [x] `OLD:tests/conftest.py` (122 lines): `--update-snapshots`, three literal
  `VALUES` fixtures, `backend`, `_table_to_numpy`.
- [x] `OLD:tests/__init__.py`: empty.
- [x] `OLD:tests/test_init.py` (1 test): pins `__version__ == "0.2.0"`.
- [~] `OLD:tests/test_custom.py` (48): user-defined transformer mode checks;
  10 `assert_allclose`; no reference library.
- [x] `OLD:vulture_whitelist.py` (20 lines): unused-parameter whitelist.
- [~] `OLD:tools/projectdb.py` (1,392 lines): project knowledge DB refresh,
  export, dump, restore; function index read, bodies sampled (L1-L60).
- [~] `OLD:tools/test_projectdb.py` (28): tests over the real
  `project.duckdb`, read L1-L50 and the test names.

### tests/core (package marker `OLD:tests/core/__init__.py`, empty)

- [~] `OLD:tests/core/test_backend.py` (29): backend connection, features.
- [~] `OLD:tests/core/test_columns.py` (39): column selectors, 1 sklearn
  mention (naming only).
- [~] `OLD:tests/core/test_compiler.py` (79): `compose_transform`,
  classification verification flag (L444), discover failure handling.
- [~] `OLD:tests/core/test_errors.py` (9): error classes.
- [~] `OLD:tests/core/test_io.py` (12): pandas and arrow input conversion.
- [~] `OLD:tests/core/test_pipeline.py` (110): constructor, fit, transform,
  `+` operators; heading index read (L72-L580).
- [~] `OLD:tests/core/test_schema.py` (164): Schema operations.
- [~] `OLD:tests/core/test_transformer.py` (112): base class,
  `__sklearn_is_fitted__` (L137-L142), `get_params`, `set_params`.
- [~] `OLD:tests/core/test_union.py` (39): Union `get_params` (L538).

### tests/scalers (package marker `OLD:tests/scalers/__init__.py`, empty)

- [x] `OLD:tests/scalers/test_standard.py` (64): read L540-L741 (parity,
  snapshot, composition).
- [x] `OLD:tests/scalers/test_robust.py` (47): read L385-L474 (`atol=0.5`).
- [x] `OLD:tests/scalers/test_minmax.py` (41): read L320-L385 (parity).
- [x] `OLD:tests/scalers/test_maxabs.py` (38): read L300-L333 (parity).
- [x] `OLD:tests/scalers/test_normalizer.py` (46): read L350-L400 (l1, l2, max).

### tests/encoders (package marker `OLD:tests/encoders/__init__.py`, empty)

- [x] `OLD:tests/encoders/test_ordinal.py` (56): read L405-L470
      (`importorskip`).
- [~] `OLD:tests/encoders/test_onehot.py` (55): 2 `assert_allclose`; no sklearn.
- [~] `OLD:tests/encoders/test_frequency.py` (66): hand expectations.
- [~] `OLD:tests/encoders/test_hash.py` (52): determinism; no reference.
- [~] `OLD:tests/encoders/test_auto.py` (60): column-type dispatch.

### tests/imputers

- [~] `OLD:tests/imputers/__init__.py`: empty.
- [~] `OLD:tests/imputers/test_imputer.py` (75): 8 `assert_allclose`; no sklearn
  here (parity is in the integration file).

### tests/features (package marker `OLD:tests/features/__init__.py`, empty)

- [~] `OLD:tests/features/test_arithmetic.py` (122): 15 `assert_allclose`.
- [~] `OLD:tests/features/test_auto.py` (133).
- [~] `OLD:tests/features/test_datetime.py` (97).
- [~] `OLD:tests/features/test_outlier.py` (74): `pytest.approx` bounds
  (L141, L212-L258), all-same-value case (L790).
- [~] `OLD:tests/features/test_string.py` (100).
- [~] `OLD:tests/features/test_target.py` (69): 8 `assert_allclose`.
- [~] `OLD:tests/features/test_window.py` (170): rolling mean and std
  (L634-L640, L803-L816), hand-worked.

### tests/feature_selection

- [~] `OLD:tests/feature_selection/__init__.py`: empty.
- [~] `OLD:tests/feature_selection/test_kbest.py` (47): read L1-L110; no
  sklearn.
- [~] `OLD:tests/feature_selection/test_correlated.py` (44).
- [~] `OLD:tests/feature_selection/test_drop.py` (39).
- [~] `OLD:tests/feature_selection/test_variance.py` (43).

### tests/data, tests/ops

- [~] `OLD:tests/data/__init__.py`: one-line marker.
- [~] `OLD:tests/data/test_concat.py` (34).
- [~] `OLD:tests/data/test_lookup.py` (52).
- [~] `OLD:tests/data/test_merge.py` (43).
- [~] `OLD:tests/ops/__init__.py`: empty.
- [~] `OLD:tests/ops/test_cast.py` (59).
- [~] `OLD:tests/ops/test_deduplicate.py` (45).
- [~] `OLD:tests/ops/test_filter.py` (51).
- [~] `OLD:tests/ops/test_rename.py` (43).
- [~] `OLD:tests/ops/test_sample.py` (57): `seed` stored and cloned (L34-L37,
  L94-L112, L328-L352); sampling reproducibility not checked against a
  reference.

### tests/integration (package marker `OLD:tests/integration/__init__.py`, empty)

- [x] `OLD:tests/integration/test_sklearn_equivalence.py` (11): read in full.
- [x] `OLD:tests/integration/test_sql_snapshots.py` (12): read L1-L120 and the
  assert index.
- [x] `OLD:tests/integration/test_sql_ast.py` (7): read L1-L70.
- [x] `OLD:tests/integration/test_sql_keywords.py` (3): read in full.
- [x] `OLD:tests/integration/test_pipeline_transformers.py` (10): read L1-L72,
  L125-L153.
- [x] `OLD:tests/integration/snapshots/standard_scaler.sql`: read.
- [x] `OLD:tests/integration/snapshots/imputer_mean.sql`: read.
- [x] `OLD:tests/integration/snapshots/imputer_auto.sql`: read.
- [x] `OLD:tests/integration/snapshots/onehot_encoder.sql`: read.
- [x] `OLD:tests/integration/snapshots/composition.sql`: read.
- [x] `OLD:tests/integration/snapshots/full_pipeline.sql`: read (scaler/imputer
  mismatch).
- [x] `OLD:tests/integration/snapshots/.gitkeep`: empty.

### Compiled output (listed, not read)

- [~] 41 `__pycache__/*.pyc` files under `OLD:tests/`, `OLD:tests/*/` and
  `OLD:tools/` (Python 3.14, pytest 9.0.2): one per test module above. They
  show the suite last ran on Python 3.14; `test_pipeline.cpython-314.pyc`
  without a pytest tag suggests a plain import.

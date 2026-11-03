---
type: note
tags: [validation, testing, sqlearn, parity, tolerances, ci]
summary: "Review of how the old sqlearn v0.4 validated correctness: pytest parity tests, hand-picked tolerances, skipped dataset tests in CI, and a near-empty verificatio"
related: [docs/testing-standards.md, docs/execution-standards.md, tests/PRECISION.md, features/verification/README.md, features/verification/scale.md, features/verification/results.csv, features/scalers.md, docs/releases/2026-04-12-v0.4-summary.md]
mdindex: [type=edb465, tags=d67fda, summary=2f1b3b, related=9dc9c6]
---
# D: Validation in the old sqlearn (v0.4)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn`.
Citations `OLD:path:Lnn` are relative to it. "Inference" marks my reading, not a
stated fact.

## Summary

- Parity was checked by pytest tests that ran the pipeline and compared the
  output to scikit-learn/pandas/numpy/scipy with `np.testing.assert_allclose`.
  About 2,750 test functions in 114 test files. About 95 carry
  `@pytest.mark.compare`, and most of the rest are contract/AST/edge tests.
  (`OLD:pyproject.toml:L151-161`)
- Ground truth was meant to be a Decimal(50 digits) reimplementation, with the
  references ranked by distance from it
  (`OLD:docs/execution-standards.md:L405-L550`). In practice Decimal50 was run
  once, by hand, for `Scale` only, and written into `tests/PRECISION.md`. No
  test code uses Decimal against sqlearn. mpmath and Fraction are never used.
- Tolerances were mostly hand-picked, and the "empirical, one decade above
  observed" rule was applied only to Scale. 164 uses of `atol=1e-10`, 183 of
  `rtol=1e-14, atol=0`, a few `1e-11`/`1e-14` for Scale, `1e-5`/`rtol=1e-5` for
  float32. No ULP bounds.
- Datasets: iris, california_housing (20,640 rows), titanic, plus synthetic
  parquet (temporal, mixed_types, float32). They are fetched by
  `datasets/download.py` from sklearn and seaborn, which needs network once.
  They are gitignored, so CI never had them and every dataset-backed compare
  test silently skipped in CI (inference from `OLD:.github/workflows/ci.yml`
  having no download step and `OLD:tests/conftest.py:L22-39` skipping on
  absence).
- Hypothesis was used only for SQL structure properties (deterministic, parses,
  immutability, round-trip), never for numerical parity. The `seed` argument is
  ignored, so every example runs on the same 5-row table
  (`OLD:tests/property/test_compiler_properties.py:L257-267`).
- Mutation testing (mutmut) was configured and recipes exist, but it is not in
  CI. The only artefact is a test-to-function map, with no recorded score
  (`OLD:mutants/mutmut-stats.json`).
- CI gated ruff, pyright, pytest on Python 3.10-3.13 (`-x -q`), and coverage >=
  90% (branch). Not gated: datasets, `-m compare` as a distinct step,
  benchmarks, mutation, the verification ledger.
- The verification ledger (`features/verification/`) has one feature,
  `sq.Scale`, a documentation-only backfill with blank `test_path`/`test_name`.
  8 CSV rows, 1 INDEX row. Roughly 55 of ~65 transform rows and most helpers in
  `features/*.md` still read `Compared? = No`.
- Several "comparisons" are weak or tautological: normality tests call scipy on
  both sides, PowerScale/QuantileScale only check correlation > 0.90/0.95,
  outlier counts allow +-2, OneHot sorts rows before comparing.
- Worth keeping: the three-tier idea (exact reference, library references, SUT),
  the `PRECISION.md` registry of known divergences with root cause, the
  per-dtype tolerances, the CSV schema, skip-not-fail for optional references,
  deterministic generated datasets. Do not keep: network dataset download,
  unmeasured tolerances, parity tests that skip silently.

## How correctness was checked

Test layers (`OLD:docs/testing-standards.md:L1-L30`, claimed layout; actual
layout differs, see Gaps):
- Contract/unit tests of class attributes, `discover()` AST shape, repr (e.g.
  `OLD:tests/transforms/scalers/test_scale.py:L64-L121` asserts the AST node is
  `Anonymous("STDDEV_POP")`). A large share of the 2,750 functions are this kind
  (inference from file samples).
- Integration/accuracy tests (`@pytest.mark.integration`, 397 uses): build a
  tiny parquet in a `TemporaryDirectory` from `VALUES`, learn + apply with
  `out="numpy"`, compare with sklearn on the same raw array.
  `test_scale.py:L51-` onwards.
- Real-dataset `compare` tests (`TestScaleCompare`, `TestOneHotCompare`,
  `Test*DeepCompare` ...): fixtures `housing_df`, `iris_df`, `titanic_df` +
  `*_path` parquet. 26 test functions take these fixtures; they are the only
  tests that skip when datasets are absent (12 files: scalers, encoders, impute,
  config, lazy, correlations).
- Self-generating `compare` tests: seeded numpy data (`default_rng(42)`) fed to
  pandas/scipy/numpy and sqlearn (`OLD:tests/comparison/*.py`,
  `OLD:tests/transforms/test_deep_compare.py`: lag/lead/rolling/rank/substring
  vs pandas, arithmetic vs numpy across DOUBLE/FLOAT).
- Multi-dtype: float64 and float32 parametrization (`test_scale.py:L474-502`,
  `test_scalers_deep.py`). Float32 uses `atol=1e-5` or `rtol=1e-5`, float64
  `1e-14` to `1e-11`.
- Snapshot tests of generated SQL (11 `.sql` files in `OLD:tests/snapshots/`).
  First run auto-writes the snapshot and passes
  (`OLD:tests/compiler/test_snapshots.py:L45-L66`).
- Dialect tests: parse/transpile with sqlglot to 6 dialects; nothing executes on
  non-DuckDB engines (`OLD:tests/compiler/test_dialect_compat.py:L1-L60`).
- Hypothesis property tests (2 files, ~22 tests, `max_examples` 10-20):
  determinism, parseable SQL, immutability, `sql()` idempotence, round-trip,
  apply-twice. No numerical property (e.g. mean 0 / std 1) is tested with
  generated data.
- Benchmarks: wall-clock bounds only
  (`OLD:tests/bench/test_v04_performance.py`), generated corpora of 10K-1M rows
  (session-scoped fixtures), no accuracy.
- Planned-but-absent: tests/PRECISION says Cramer's V "pending investigation...
  test bug" (`OLD:tests/PRECISION.md:L29-32`).

Known DuckDB-vs-sklearn pitfalls the old project found and tested: `STDDEV_POP`
(ddof=0) vs sample std; NULL skipping; categorical order (compare sorted);
integer promotion; zero-variance columns produce 0; large (1e15) and tiny
(1e-15) magnitudes (`test_scale.py:L545-583`).
(`OLD:docs/testing-standards.md:L170-L190`)

## Tolerances and references

- Written policy: tolerance = one decade above the worst observed diff from
  Decimal50 ground truth; "never pick a tolerance without a ground-truth
  measurement" (`OLD:docs/execution-standards.md:L478-L496`). Per-dtype
  tolerances required. A divergence needs a `PRECISION.md` entry (L498-L520).
- Tiers in testing-standards: arithmetic 1e-10, aggregation 1e-7, categorical
  exact, float32 1e-5 (`OLD:docs/testing-standards.md:L150-L165`). These
  disagree with the execution-standards rule and with real tests (1e-11 / 1e-14
  / rtol 1e-14).
- Actual Scale numbers: DuckDB parallel summation causes ~2.66e-15 error in the
  mean, ~1.42e-12 max abs diff in z-scores on housing (rel 9.6e-9 on near-zero
  values); numpy was closer to Decimal50 (`OLD:tests/PRECISION.md:L8-L27`).
  Chosen `atol=1e-11` (20K rows), `1e-14` (iris). Tolerance is absolute because
  near-zero z-scores make relative error meaningless.
- That history is instructive: the first tests used `rtol=1e-14` and failed on
  housing; they were "loosened" afterwards
  (`OLD:tests/transforms/scalers/test_scale.py:L445-453`). Sub-1e-14 `rtol` on
  small hand-made data still stands in ~183 asserts.
- Reference library map (primary/secondary/specialist per operation) in
  `OLD:docs/execution-standards.md:L551-L627`: sklearn for
  scalers/encoders/impute, pandas for window/corr, scipy/statsmodels/pingouin
  for stats. All test-time only, imported via `pytest.importorskip`. Reality:
  sklearn and pandas imported unconditionally at module top in many files (e.g.
  `test_scale.py:L16-17`), because they are in the dev dependency group
  (`OLD:pyproject.toml:L44-62`); `importorskip` only for scipy, statsmodels,
  pyarrow, polars.
- No ULP, Fraction, mpmath. Float formulas for Decimal ground truth are given in
  `OLD:features/verification/scale.md:L26-37` (population variance,
  `Decimal(str(v))`).
- Per-feature registry `features/*.md`: columns sqlearn | reference |
  Compared? | test file | outcome | max diff (`OLD:features/scalers.md`).
  Registered upfront with "No", then flipped.

## CI and gates

- `OLD:.github/workflows/ci.yml`: jobs lint (ruff check + format check),
  typecheck (pyright), test (matrix py3.10/3.11/3.12/3.13,
  `uv run pytest -x -q`), coverage (needs test;
  `--cov-branch --cov-fail-under=90`). Triggers: push/PR to main.
  `OLD:.github/workflows/publish.yml`: PyPI trusted publishing on release, no
  tests in that workflow.
- pytest default `addopts = "-m 'not slow'"` (`OLD:pyproject.toml:L161`): so
  compare/benchmark/property tests all run in CI by default. Dataset-backed ones
  skip (no download step; parquet is gitignored: `OLD:.gitignore` "Datasets").
  Inference: CI never exercised the 20K-row Scale/MinMax/Robust/Normalize/OneHot
  real-data parity.
- `pytest-randomly` installed (random order in CI), `pytest-timeout` used only
  in mutmut config.
- `just` recipes: `check` = lint + fmt-check + typecheck + test; `test-compare`
  (`-m compare`), `test-full` (`-m ""`), `cov`, `mutate*` (mutmut),
  `compare-report`, `download-data` (`OLD:justfile`). The `just test` comment
  says "no datasets needed", i.e. dataset tests skipped.
- `scripts/compare_report.py` runs `-m compare -v` and parses test names with
  regex (`::\w+Compare::`, `on_<dataset>`, "sklearn"/"numpy" substring) into a
  Transform/Dataset/Reference/Match table. It reports pass/fail only, not diffs,
  and exits 1 when nothing is found. Reference is guessed from the method name,
  which is fragile (default "numpy").
- Mutation: `OLD:mutmut.toml` runs the whole suite per mutant with
  `--timeout=60 -p no:hypothesis -p no:randomly`,
  `mutate_only_covered_lines = true`. Local only. `mutants/` holds 601 files;
  `.hypothesis/` 279 (not read).
- Required-by-doc but not enforced: coverage 100% compiler (doc) vs 90% (CI);
  file size limits 400/600 lines (several test files exceed: `test_window.py`
  1145, `test_deep_compare.py` 1089); "no logic in tests" (loops exist:
  `test_scale.py:L75`); `tests/integration/`, `tests/benchmarks/` directories
  named in the doc do not exist (actual `tests/bench`, `tests/comparison`,
  `tests/transforms/...`).

## Verification records

- Ledger design (`OLD:features/verification/README.md`): `results.csv` (17
  columns, append-only, one row per feature x dataset x dtype x reference:
  version, max_abs_diff, max_rel_diff vs Decimal50, closest_to_truth, atol/rtol,
  run_date, test_path, test_name), per-feature `<feature>.md` with YAML
  frontmatter (status lifecycle not-started -> in-progress -> verified |
  divergent), `INDEX.md`, `TEMPLATE.md`; a `.. verification::` docstring
  directive; "symbol authoritative, path derived"; plan-execution gate
  (`execution-standards.md:L539-L548`). Queryable with DuckDB.
- State: 8 rows, all `sq.Scale` (iris and housing, references
  decimal50/numpy/sklearn/sqlearn), run_date 2026-04-11, version 0.3.0,
  `test_path`/`test_name` blank (`OLD:features/verification/results.csv`).
  `scale.md` states it is a documentation-only backfill and the test locations
  are "to be populated". INDEX has one row. No other feature has a record. v0.4
  release summary admits "no entries in this release" and defers
  (`OLD:docs/releases/2026-04-12-v0.4-summary.md:L166-168, L331-351`).
- Staleness is possible by design: nothing checks the CSV against code;
  `verification-check` and `verification-report` are listed as "Future work (not
  built)" (`README.md:L137-L153`). The CSV's sklearn row for housing shows
  5.6e-17 (a std figure) next to the sqlearn row 1.42e-12 — rows mix different
  quantities (inference; the max_rel_diff cell is empty).
- Process records: `REVIEW.md` is a hand-kept table of (source file, test file,
  count, compare against) per phase with test totals; `features/*.md`
  registries. They track counts, not measured agreement.
- Process weight: `execution-standards.md` is 1,423 lines of agent workflow
  (resumption, deploy convention, release summaries, post-release review), most
  of it unrelated to numerical validation (inference: it grew faster than the
  ledger it describes).

## Gaps and false confidence

1. Dataset parity skipped in CI (see CI). Local runs had the parquet; CI did
   not.
2. Ledger covers 1 of ~65 comparable features; registry shows most transforms
   uncompared; yet the docs describe a "gate" requiring records. Gate never
   enforced.
3. Tautological compare tests: `test_normality_vs_scipy.py` passes the same
   float64 array to `scipy.stats.shapiro` on both sides and asserts bit equality
   (`L35-39`, `L66`); it proves wiring, not correctness.
4. Weak thresholds: PowerScale and QuantileScale vs sklearn only assert Pearson
   correlation > 0.90/0.95
   (`OLD:tests/transforms/scalers/test_power_scale.py:L125-165`,
   `test_quantile_scale.py:L117-132`); outlier counts allow +-2 rows
   (`OLD:tests/comparison/test_outliers_vs_manual.py`); OneHot compares after
   `lexsort` of rows, so row-order or alignment bugs pass
   (`test_onehot.py:L400-403`).
5. Hypothesis tests ignore their generated input (unused `seed`), single fixed
   5-row table; they check shape of SQL, not numbers. `max_examples` 10-20 with
   health checks suppressed.
6. Snapshot tests auto-create on first run, so a missing snapshot passes; the
   snapshot set (11 files) covers few transformers versus ~40 in the suite.
7. Dialect tests only parse; Postgres/BigQuery/Snowflake/etc. semantics (e.g.
   STDDEV_POP, integer division, NULL ordering) never executed.
8. Tolerances loosened after the fact (rtol 1e-14 -> atol 1e-11) and justified
   in comments; only Scale has Decimal evidence. All others depend on guess.
   `atol=1e-10` on data with scale 1e5+ is not tight. rtol 1e-5 with atol 0 on
   float32 near-zero values can fail or hide error.
9. NaN vs NULL: data goes through f-string `VALUES` SQL with float `repr`, so
   float32 values are re-parsed as float64 in some tests (inference,
   `test_scale.py:L474-502`), weakening the float32 test.
10. Mutation testing unrun in CI and no score recorded; unknown test strength.
    Many tests assert internals (AST node types), which couple to implementation
    and kill mutants without proving parity.
11. Docs vs reality drift: doc promises `tests/integration`, `tests/benchmarks`,
    `just bench`, `pytest-cov` 100%; actual config differs. `PRECISION.md`
    Cramer's V entry "test bug".
12. Test naming: `test_phase3.py`, `test_phase6.py`, ... organise by delivery
    phase, not by feature, which made coverage by feature hard to see.
13. Only one numerical regime tested for most scalers (well-conditioned data);
    no adversarial cancellation inputs (large mean small variance) beyond a 1e15
    five-row case, which is where sum-of-squares formulas and parallel DuckDB
    aggregation diverge.

## Worth keeping

- Keep the idea of an exact reference plus "who is closest" analysis, but
  implement it in code. For the new project use `fractions.Fraction`/mpmath
  references computed in the test (answers `validation-method.md`): compute
  reference once, compare sklearn, numpy and sqlearn all against it, record max
  diff, and set tolerance from the measurement. Make the measurement an
  automated test or script, not a hand write-up.
- Keep `PRECISION.md`-style divergence registry (dataset, rows, dtype,
  per-library diff, closest, root cause, chosen tolerance). The DuckDB
  parallel-summation finding is a real, reusable fact (aggregates are not
  order-deterministic; consider `threads=1` or compensated sums where stability
  matters, inference).
- Keep per-dtype tolerance tables and "absolute not relative near zero"
  reasoning; add ULP bounds as in sqlearn-000 for elementwise ops where exact is
  possible.
- Keep deterministic synthetic datasets (seeded, written to parquet by DuckDB
  `COPY ... VALUES`) as the primary parity input; they need no network. Include
  an adversarial set: constant column, single row, all-NULL, 1e15/1e-15, large
  mean/small variance, float32, ties, unicode names.
- Keep the edge-case matrix (`testing-standards.md:L96-L113`) as parametrized,
  shared across transformers.
- Keep `pytest.importorskip` for optional references, but make "reference
  library missing" a CI failure for the parity job (do not allow silent skip).
  Pin scikit-learn in the dev group and record `reference_version` with each
  result.
- Keep the CSV ledger schema, trimmed (feature, dataset, dtype, reference,
  version, max_abs/max_rel/ULP, tolerance, test id) but generate it from tests
  (a pytest hook or a script) instead of hand-typing, and add the
  `verification-check` that was never built. Given the new project's `docs/`
  tooling, a generated table in docs beats a hand-maintained ledger.
- Keep hypothesis but give it real data: generate arrays (floats, NULLs,
  constants) and assert parity vs the exact reference within the measured bound;
  property "mean 0, std 1" for scale; idempotence; row-count preservation.
- Keep snapshots only for compiled SQL, and require explicit update (fail when
  absent, update via a flag).
- Run mutation testing on the numerical core on a schedule, not per commit;
  record a score.
- Network: datasets must be bundled or generated. sklearn's bundled
  `load_iris`/`load_wine`/`load_diabetes`/`load_breast_cancer` ship in the wheel
  (no network), while `fetch_california_housing` and seaborn `load_dataset`
  download. Use committed small parquet files (or generated data) and treat any
  large real data as optional, local, never in CI. (Old:
  `OLD:datasets/download.py:L17-L56` needs network,
  `OLD:datasets/README.md:L29-35` claims "no external accounts" but still
  downloads.)
- Fixtures worth copying: fresh `duckdb.connect()` per test with try/finally
  close; `rng` fixture seeded 42;
  `generate_test_data(rows, cols, seed, include_nulls)`;
  `assert_numerical_accuracy(actual, expected, atol, rtol=0)` wrapper;
  `_require_dataset` skip-with-hint (but fail in CI); shared per-package
  `conftest.py` creating small `VALUES` tables
  (`OLD:tests/transforms/scalers/conftest.py`,
  `OLD:tests/transforms/window/conftest.py`).
- Cap on file size, naming by behaviour and AAA are fine, but organise tests by
  feature, not by phase.

## Files covered

Legend: [x] read substantially, [~] skimmed (grep/size/sample). Paths relative
to OLD.

### Config, docs, scripts
- [x] docs/testing-standards.md - full read; test layers, tolerance tiers,
      edge-case matrix, benchmark design.
- [x] docs/execution-standards.md - full read of sections 1-2 skim, 5.3, 6-9,
      10-12; verification protocol and ledger spec; rest is agent workflow.
- [x] datasets/README.md - five datasets, not committed, `just download-data`.
- [x] datasets/download.py - sklearn/seaborn fetch (network) plus synthetic
      temporal/mixed_types/float32.
- [x] mutmut.toml - src/ mutate, covered lines only, whole suite.
- [x] .github/workflows/ci.yml - lint, typecheck, test matrix 3.10-3.13,
      coverage 90%.
- [x] .github/workflows/publish.yml - PyPI OIDC publish on release, no tests.
- [x] justfile - check/test/compare/mutate/download recipes.
- [x] scripts/compare_report.py - parses -v pytest output into a table;
      pass/fail only.
- [x] tests/PRECISION.md - Scale divergence entry, Decimal50, Cramer's V
      pending.
- [x] tests/conftest.py - dataset skip fixtures, conn, rng, generate_test_data,
      assert wrapper, snapshot loader.
- [x] pyproject.toml (extra) - dev group, markers, addopts.

### features/
- [x] features/INDEX.md - registry index.
- [~] features/composition.md - registry table, mostly Yes.
- [~] features/core.md - registry table.
- [~] features/encoders.md - 5 of 5 rows No (no Compared yes) per grep counts.
- [~] features/helpers.md - 11 Yes / 9 No.
- [~] features/impute.md - 2 Yes / 4 No.
- [x] features/scalers.md - Scale/MinMax/Robust/MaxAbs Yes;
      Normalize/Quantile/Power No.
- [~] features/transforms.md - 6 Yes / 55 No.
- [x] features/verification/README.md - ledger schema, lifecycle, future work
      not built.
- [x] features/verification/TEMPLATE.md - per-feature template.
- [x] features/verification/results.csv - 8 Scale rows, blank test ids.
- [x] features/verification/INDEX.md - one row.
- [x] features/verification/scale.md - Decimal50 formula, backfilled.

### tests/ (top)
- [x] tests/__init__.py - package marker (listed).
- [~] tests/test_package.py - 2 tests, import/version smoke.
- [x] tests/PRECISION.md, tests/conftest.py - see above.

### tests/backend
- [~] tests/backend/__init__.py - marker.
- [~] tests/backend/test_dataframe_input.py - pandas/arrow/polars input equals
  parquet output; importorskip pyarrow/polars.
- [~] tests/backend/test_duckdb.py - backend contract, 27 tests.
- [~] tests/backend/test_duckdb_deep.py - deeper backend tests, 19.

### tests/bench
- [~] tests/bench/__init__.py - marker.
- [x] tests/bench/test_v04_performance.py - wall-clock bounds on generated
      10K-1M row corpora; no accuracy.

### tests/comparison
- [~] tests/comparison/__init__.py - marker.
- [x] tests/comparison/test_distribution_vs_pandas.py - mean/median/std/min/max
      vs pandas, rtol 1e-10/1e-14.
- [x] tests/comparison/test_normality_vs_scipy.py - tautological scipy-vs-scipy.
- [x] tests/comparison/test_outliers_vs_manual.py - counts +-2.

### tests/compiler
- [~] tests/compiler/__init__.py - marker.
- [~] tests/compiler/test_classify.py - transformer static/dynamic
  classification, 17.
- [~] tests/compiler/test_classify_deep.py - 11.
- [~] tests/compiler/test_compile.py - compile to SQL, 17.
- [~] tests/compiler/test_compile_deep.py - 13.
- [~] tests/compiler/test_compose.py - expression composition, 36.
- [~] tests/compiler/test_compose_deep.py - 15.
- [~] tests/compiler/test_cte.py - CTE promotion, 20.
- [~] tests/compiler/test_cte_deep.py - 11.
- [x] tests/compiler/test_dialect_compat.py - parse/transpile to 6 dialects, no
      execution.
- [~] tests/compiler/test_layers.py - layering, 24.
- [~] tests/compiler/test_layers_deep.py - 11.
- [x] tests/compiler/test_snapshots.py - auto-create-on-first-run SQL snapshots.

### tests/snapshots (SQL snapshot files)
- [~] tests/snapshots/expression_ln.sql
- [~] tests/snapshots/filter_age.sql
- [~] tests/snapshots/filter_then_scale.sql
- [~] tests/snapshots/impute_mean.sql
- [~] tests/snapshots/impute_then_scale.sql
- [~] tests/snapshots/minmax_numeric.sql
- [~] tests/snapshots/nested_impute.sql
- [~] tests/snapshots/onehot_categorical.sql
- [~] tests/snapshots/ordinal_categorical.sql
- [~] tests/snapshots/robust_scale_numeric.sql
- [~] tests/snapshots/scale_numeric.sql (all 11: expected SQL strings compared
  after strip; not opened individually beyond names.)

### tests/core
- [~] tests/core/__init__.py
- [~] tests/core/test_columns.py - 14.
- [~] tests/core/test_config.py - to_config/from_config round trip, 28 (one
  compare test with dataset).
- [~] tests/core/test_lazy.py - LazyResult, 29 (3 dataset fixtures).
- [~] tests/core/test_pipeline.py - 62.
- [~] tests/core/test_pipeline_composition.py - 20.
- [~] tests/core/test_pipeline_deep.py - 29.
- [~] tests/core/test_row_identity.py - 11.
- [~] tests/core/test_selectors.py - 49.
- [~] tests/core/test_transformer.py - 30.
- [~] tests/core/test_transformer_params.py - 53.

### tests/helpers
- [~] tests/helpers/__init__.py
- [~] tests/helpers/test_analyze.py - 25 (6 compare).
- [~] tests/helpers/test_attach.py - 6.
- [~] tests/helpers/test_concat.py - 22.
- [~] tests/helpers/test_concat_deep.py - 10.
- [~] tests/helpers/test_connect.py - 9.
- [~] tests/helpers/test_correlation_methods.py - 23, compare.
- [~] tests/helpers/test_correlations.py - 31, 2 compare with datasets.
- [~] tests/helpers/test_lineage.py - 16.
- [~] tests/helpers/test_merge.py - 29.
- [~] tests/helpers/test_merge_deep.py - 12.
- [~] tests/helpers/test_peek.py - 6.
- [~] tests/helpers/test_profile.py - 17.
- [~] tests/helpers/test_sklearn_adapter.py - mock-based adapter tests, 17; no
  sklearn parity.

### tests/property
- [~] tests/property/__init__.py
- [x] tests/property/test_compiler_properties.py - hypothesis, unused seed,
      fixed 5-row table.
- [~] tests/property/test_compiler_properties_deep.py - same pattern, multi-step
  pipelines.

### tests/transforms (top level)
- [~] tests/transforms/__init__.py
- [~] tests/transforms/test_branch.py - 28.
- [~] tests/transforms/test_composition_edges.py - 12.
- [~] tests/transforms/test_custom.py - 19.
- [x] tests/transforms/test_deep_compare.py - pandas/numpy comparisons:
      arithmetic multi-dtype, lag/lead/rolling/rank, substring, union/lookup.
- [~] tests/transforms/test_expression.py - 12.
- [~] tests/transforms/test_fill.py - 33.
- [~] tests/transforms/test_group_aggregate.py - 27.
- [~] tests/transforms/test_impute.py - 36 (dataset compare 1).
- [~] tests/transforms/test_impute_deep.py - sklearn SimpleImputer across
  dtypes, housing with injected NULLs.
- [~] tests/transforms/test_lookup.py - 34.
- [~] tests/transforms/test_nested.py - 27.
- [~] tests/transforms/test_outlier.py - 57.
- [~] tests/transforms/test_outlier_deep.py - 8.
- [~] tests/transforms/test_phase10_11.py - TargetTransform, Quick, FromSklearn,
  ModelInfo, 24.
- [x] tests/transforms/test_phase3.py -
      MissingIndicator/Binarize/Deduplicate/Sample/Sort with sklearn/pandas
      compare classes.
- [~] tests/transforms/test_phase6.py - Bin/Interaction/Polynomial, 19.
- [~] tests/transforms/test_phase7_8.py - Cumulative*, Winsorize and compare
  classes, 31.
- [~] tests/transforms/test_phase9.py -
  DropLowVariance/DropCorrelated/SelectKBest, 28.
- [~] tests/transforms/test_ratio.py - 29.
- [~] tests/transforms/test_sql.py - 25.
- [~] tests/transforms/test_union.py - 37.

### tests/transforms/arithmetic
- [~] __init__.py
- [~] conftest.py - small VALUES table fixture.
- [~] test_arithmetic.py - 60.
- [~] test_arithmetic_compare.py - numpy compare, 7 compare classes.
- [~] test_arithmetic_edges.py - 17.
- [~] test_new_arithmetic.py - 26, 6 compare.

### tests/transforms/datetime
- [~] __init__.py
- [~] conftest.py
- [~] test_cyclical.py - 36 (rtol 1e-14 compare).
- [~] test_date_diff.py - 19.
- [~] test_date_parts.py - 23.
- [~] test_datetime_edges.py - 13.
- [~] test_is_weekend.py - 13.
- [~] test_quarter.py - 14.

### tests/transforms/encoders
- [~] __init__.py
- [~] conftest.py
- [~] test_binary_encode.py - 14.
- [~] test_count_encode.py - 27.
- [~] test_frequency_encode.py - 21.
- [~] test_hash_encode.py - 29.
- [x] test_onehot.py - OneHotEncoder on titanic columns, rows lexsorted.
- [~] test_ordinal.py - OrdinalEncoder compare, 20.
- [~] test_target_encode.py - 10 (registry says target encode not compared).

### tests/transforms/ops
- [~] __init__.py
- [~] conftest.py
- [~] test_cast.py - 25.
- [~] test_drop.py - 16.
- [~] test_filter.py - 17.
- [~] test_ops_edges.py - 15.
- [~] test_rename.py - 27.

### tests/transforms/scalers
- [~] __init__.py
- [x] conftest.py - 5-row numeric table with one NULL.
- [~] test_maxabs_scale.py - 24, sklearn MaxAbsScaler.
- [~] test_minmax_scale.py - 24, sklearn, housing.
- [~] test_normalize.py - 33, sklearn Normalizer (registry says not compared;
  datasets used).
- [x] test_power_scale.py - correlation > 0.90 only.
- [x] test_quantile_scale.py - correlation > 0.95 only.
- [~] test_robust_scale.py - 38.
- [x] test_scale.py - contract, AST, accuracy, edge cases, Compare class on
      housing/iris/dtypes.
- [x] test_scalers_deep.py - multi-dtype housing/iris, tightest-tolerance small
      data, float32, zero variance, norms.

### tests/transforms/string
- [~] __init__.py
- [~] test_regex.py - 29.
- [~] test_stats.py - 24.
- [~] test_string.py - 57.
- [~] test_string_compare.py - 12, 5 compare classes vs pandas.
- [~] test_string_edges.py - 18.

### tests/transforms/window
- [~] __init__.py
- [x] conftest.py - time_series_table fixture.
- [~] test_window.py - 80 tests, 1145 lines.

### tests/unit/helpers
- [~] tests/unit/__init__.py
- [~] tests/unit/helpers/__init__.py
- [~] test_analyze.py - 13.
- [~] test_cardinality.py - 51.
- [~] test_distribution.py - 46.
- [~] test_explain.py - 14.
- [~] test_explore.py - 46.
- [~] test_missing.py - 42.
- [~] test_normality.py - 58, statsmodels importorskip.
- [~] test_outliers.py - 42.
- [~] test_primitive_base.py - 5.
- [~] test_render.py - 14.
- [~] test_sample.py - 11.
- [~] test_target.py - 56.

### Not read (by instruction)
- mutants/ (601 files; only mutmut-stats.json head, a test-to-function map) and
  .hypothesis/ (279 files): counted only.
- Also read for context: REVIEW.md, docs/releases/2026-04-12-v0.4-summary.md
  (sections), .gitignore.

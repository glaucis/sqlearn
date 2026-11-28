---
type: note
tags: [testing, validation, tolerances, specification, sqlearn]
summary: "Batch D of an archived April 2026 planning review: specs for sqlearn's test and validation methods, tolerances, datasets and gates, read but not run."
related: []
mdindex: [type=edb465, tags=49371b, summary=6f008c]
---
# D: Test and validation specs in the April planning repo

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn-private`
(GitHub `glaucis/sqlearn-private`, 9-24 April 2026). Batch D of five. Read only;
nothing was run.

Citation form: `OLD:path:Lnn`, where `path` is relative to
`OLD/_old/projects/sqlearn/` unless it starts with `templates/`, which is
`OLD/_old/templates/`. "Inference" marks my reading, not a stated fact.
Everything in this batch is a specification in Markdown: the Python in the
files is a design for tests that were to be written in the public repo, not
code that ran (`OLD:tests/INDEX.md:L10`, `OLD:tests/src/INDEX.md:L14-L17`).
The `standards/validation.md` page that the validations folder defers to for
"the rules" is outside this batch and was not read.

## Summary

- Two separate things were specified. **Tests** (`tests/src/`, 60 files
  for v0.5 to v1.0) check that code runs. **Validation** (`validations/`, 5
  files) checks numbers against an exact reference. The spec says they are
  "separate" (`OLD:validations/INDEX.md:L31-L33`).
- The validation method is the strongest of any attempt on paper: one Python
  file per formula, a reference computed in arbitrary precision
  (Decimal, Fraction or mpmath) from a primary source, never from another
  library, 12 baseline cases, and a JSON report per function
  (`OLD:templates/validator.py:L11-L26`).
- Tolerances are a five-layer cascade in `tolerances.toml`, in ULPs and in
  absolute/relative error: function, then operation kind, then library, then
  dtype, then a default of 4 ULP (`OLD:templates/tolerances.toml:L8-L37`).
  The values are guesses ("expected max ULPs" are predictions in the
  manifest, `OLD:validations/manifest.md:L119`), to be adjusted "empirically".
- Gates are specified: `just validate <path>` per function, `run_all
  --strict` on every PR, a release gate on tags that reads the version file
  (`OLD:validations/framework.md:L627-L675`, line numbers approximate for the
  YAML). None of it existed: the registries are empty templates and no
  validator file is in this repo.
- **Pipeline-level parity against scikit-learn was never specified.** The
  baseline is confirmed, with one nuance: `Pipeline` is marked "n/a" in the
  manifest because "end-to-end pipeline validators" are "future, not in
  current scope" (`OLD:validations/manifest.md:L296`,
  `OLD:validations/framework.md:L891-L892`). The validator template takes
  one 1-D column per case, so it cannot express a multi-step pipeline
  (inference, `OLD:templates/validator.py:L148-L205`).
- The test specs **lock in the fit defect as a feature.** A golden SQL
  snapshot for `Impute` then `Scale` has the scale constant learned from the
  raw column; a query-count test requires `Impute, Scale, MinMaxScale,
  Winsorize, RobustScale` to fit in one query
  (`OLD:tests/src/compiler/sql_snapshots.md:L361-L364`,
  `OLD:tests/src/compiler/layer_batching.md:L76-L89`).
- The cross-library check inside the per-transformer contract is
  `np.allclose(..., rtol=1e-6)` against sklearn, scipy or pandas: far looser
  than the ULP cascade, and "skip if no reference"
  (`OLD:tests/src/_shared/transformer_contract.md:L243-L260`).
- Property tests: two hypothesis properties only (never crashes,
  deterministic), no numerical property. Mutation testing: not specified in
  this batch (the word appears only for object mutation).
- Datasets: nothing is downloaded in the specs. Shared fixtures are 7-row
  hand-made DuckDB tables; the validation fixtures are bundled parquet files
  (iris, diamonds, california_housing) plus fixed-seed generated ones.
- New and worth keeping: the 11-test transformer contract with 12 edge cases
  (SQL keyword and Unicode column names), snapshots that fail when missing,
  a classification audit that fails when a new built-in is not listed,
  a read-only source-table invariant, and exact DECIMAL(38,18) tests with a
  1,000,000-row ground truth.

## Validation method as specified

Source: `OLD:validations/framework.md` (908 lines, read fully),
`manifest.md` (414, read fully), `INDEX.md`, the starter `templates/`.

- **Unit of validation:** one validator per distinct formula, "atomicity"
  (`OLD:validations/manifest.md:L330-L333` and `OLD:validations/INDEX.md:L22`).
  `Scale(mode="zscore")`, `minmax`, `robust`, `Log`, `Log(base=10)` are five
  separate validators. Mirrors `src/`.
- **Single Python file per validator,** even for R (rpy2), Julia
  (juliacall), Postgres, Snowflake and BigQuery drivers. If a bridge is not
  installed the adapter returns `None` and that comparison is skipped
  (`OLD:validations/framework.md:L46-L110`).
- **Reference ("canonical"):** computed in Decimal (40 digits in the
  template) or mpmath (200 bits for transcendentals), from a primary source
  cited by URL with a retrieval date, "never from another library"
  (`OLD:templates/validator.py:L12-L14`, `L85-L110` via the template text).
  For iterative fits (Box-Cox lambda) the canonical is a from-scratch Brent
  solver in mpmath, with the note that scipy's own optimiser is
  non-deterministic below about 1e-10
  (`OLD:validations/manifest.md:L196-L197`).
- **Baseline cases per validator (12):** float64, float32, int64 promotion,
  NULL propagation, empty, single value, constant, large N (1,000,000), and
  so on (`OLD:templates/validator.py:L148-L205`, cases shown up to `large_n`;
  the rest I did not read).
- **Output:** a JSON report per function, validated against a schema; each
  library gets `max_absolute_error`, `max_relative_error`, `max_error_ulps`
  and `passed` (`OLD:templates/validator.py:L19-L21`).
- **Dtype is checked as well as value** (integers stay integers; the
  promotion list is in `OLD:templates/tolerances.toml:L233-L255`).
- **Libraries compared** (per manifest entry): sklearn, numpy, scipy, pandas,
  statsmodels, DuckDB; optionally R, Julia, Postgres, Snowflake, BigQuery
  (`OLD:validations/framework.md:L56-L72`).
- **Who writes validators:** an agent. A Sonnet "hardener" subagent per
  function, three attempts, then Opus for three, then a human; "never Haiku"
  for anything numerical (`OLD:validations/framework.md:L399-L440`, `L551`).
  A manifest entry (model, primary source, gotchas, escalation hints,
  "expected max ULPs") must exist before a function is dispatched; a missing
  entry means the main agent refuses (`OLD:validations/manifest.md:L30-L36`).
- **Framework tests itself:** `validations/meta_tests/` test `verify.py`, the
  cascade, ULP computation, the gate, run under pytest in CI
  (`OLD:validations/framework.md:L282-L288`, `L636`).
- **Audit trail:** failures write escalation files committed under
  `validations/escalations/`, resolved ones moved to `_resolved/`
  (`OLD:validations/framework.md:L296-L303`).

Separately, the **tests** specify a different, weaker comparison: contract
test 9, "Cross-library equivalence", with sklearn, scipy or pandas as
reference and `np.allclose(rtol=1e-6)`
(`OLD:tests/src/_shared/transformer_contract.md:L53`, `L258-L260`). Two
sources of truth for "correct" therefore coexist and disagree by about nine
orders of magnitude (inference from L258-L260 against the cascade default).

## Tolerances and references

- **Cascade, most specific wins:** `by_function`, `by_operation`,
  `by_library` (absolute or a multiplier), `by_dtype`, `default`
  (`OLD:templates/tolerances.toml:L8-L14`).
- **Default:** absolute and relative 2.3e-16, 4 ULP (`L32-L37`). float32
  1.2e-7 (`L50-L54`). Integers 0 (`L56-L70`). Library entries: sklearn 10
  ULP (`L95-L98`), pandas x10 absolute (`L100-L103`), DuckDB 10 ULP
  (`L105-L108`), Snowflake and BigQuery 20, R 50.
- **By operation:** basic 2 ULP, sum and mean 1e-14 and 50 ULP, variance and
  stddev 1e-13 and 100 ULP, log and exp 2.3e-15 and 10 ULP, sqrt 1 ULP,
  quantile 1e-12 and 1000 ULP, power 1e-12, encoding and binning exact
  (`L128-L218`).
- **How tolerances are set:** by hand in the starter file, with the rule that
  every change is a commit with old value, new value, reason, and a link to
  the run, and "never loosen a tolerance without investigating"
  (`L19-L26`). The rationales are written as lore ("pandas uses Welford",
  "DuckDB uses SIMD summation"), not measured; the manifest's "expected max
  ULPs" are predictions (`OLD:validations/manifest.md:L119`). Inference: this
  is the same gap v0.4 had, a method that says "measure" with nothing
  measured.
- **ULP is first-class here** (`compare.py` computes it,
  `OLD:validations/framework.md:L240`; the PASS line prints "max 1 ULP",
  `L391`). This is new against v0.4, which had no ULP bounds.
- **References:** exact reference first, libraries second, sqlearn is one
  of the compared libraries, held to the default ("fix the code; don't
  loosen", `OLD:templates/tolerances.toml:L76-L81`). Reference mapping per
  formula is in each manifest entry (e.g.
  `OLD:validations/manifest.md:L100-L120` for zscore: sklearn, numpy, scipy,
  pandas, duckdb).
- **Tests' tolerances:** `rtol=1e-6` in the contract
  (`OLD:tests/src/_shared/transformer_contract.md:L259`);
  `rtol=1e-12` for `Log` in decimal mode against the float pipeline
  (`OLD:tests/src/precision/comparison.md:L216`); `< 1e-9` between cached and
  uncached explore scores
  (`OLD:tests/src/helpers/explore_caching_correctness.md:L47`, approximate
  line).
- **Errors in the specification (my reading, from scikit-learn's documented
  behaviour):** the zscore entry says scikit-learn's `StandardScaler` "uses
  n-1 by default - override with ddof=0"
  (`OLD:validations/manifest.md:L107-L108`).
  `StandardScaler` uses the population standard deviation and has no such
  option. It also says `pd.get_dummies` orders by first appearance (`L224`
  region); I believe it sorts, but did not check. Hand-written "critical
  notes" were wrong in at least one place.

## Datasets

- **Validation fixtures (bundled, parquet, committed):** `iris`, `diamonds`,
  `california_housing`, `synthetic_normal_1k` (fixed seed),
  `synthetic_normal_1m` ("large-N precision checks"), `edge_cases` (NaN, Inf,
  near-float64-limit) (`OLD:validations/framework.md:L262-L269`). Test data
  inside validators is generated: `rng = default_rng(seed=42)`, 1,000 normal
  samples, 1,000,000 for `large_n` (`OLD:templates/validator.py:L148-L205`).
- **How fixtures are shared is an open question,** deferred "until 5+
  validators" (`OLD:validations/framework.md:L898-L899`).
- **Tests:** no download, no named public dataset. Shared fixtures are
  7-row DuckDB tables built from `VALUES`: `sample_numeric_conn` (odd row
  count, NULLs in non-uniform places), `sample_categorical_conn` (clear
  modes, one deliberate tie), `sample_mixed_conn`
  (`OLD:tests/src/_shared/fixtures.md:L47-L134`). Snapshot fixtures are 5-row
  tables (`OLD:tests/src/compiler/sql_snapshots.md:L90-L155`).
- **Generated at test time:** CSV files written with the `csv` module in a
  `tmp_path` for almost every other test, e.g. 10,000 rows for the explore
  speed-up test; the DECIMAL tests write a 1,000,000-row CSV of `Decimal`
  values in Python (`OLD:tests/src/precision/comparison.md:L31-L48`). Inference:
  that loop and the `sum()` over 1M `Decimal`s would take noticeable time per
  module; the 20,000-row case is the cheap one.
- Contrast with v0.4: it fetched iris, housing and titanic from the network
  and gitignored them, so dataset tests skipped in CI. The planning repo's
  answer is bundling parquet (validations) and tiny synthetic tables (tests).
  It never states a licence or size check for the bundled files (inference).

## Gates

What would block a merge, as specified:

- **Per function:** `just validate <path>` must print PASS: `summary.failed ==
  0`, every declared library produced a result or was skipped as "not
  installed", all required baseline cases present, dtypes match
  (`OLD:validations/framework.md:L380-L397`). The same script is used by the
  agent, the orchestrator and CI.
- **Per PR:** job `test` (`pytest tests/ validations/meta_tests/`), then job
  `validate` (`python -m validations.run_all --strict`), reports uploaded
  as an artefact (`OLD:validations/framework.md:L627-L650`, approximate).
- **On tags:** a `release_gate` job re-runs everything with the optional
  extras (Postgres, Snowflake, BigQuery, rpy2) and runs `release_gate.py`,
  which reads the private repo's version file and requires every row's
  Validation column to be `yes`, `yes, waived`, or `n/a`
  (`OLD:validations/framework.md:L612-L624`, `L652-L675`;
  `OLD:validations/function_registry.md:L98-L110` for the status legend,
  including `pending` "blocks release").
- **Spot check:** the main agent re-runs `just validate` after every fifth
  successful subagent return (`OLD:validations/framework.md` "Spot-check
  policy").
- **Test-side gates, named in the specs:** the classification audit is
  "CI-gated" and also fails if a new built-in is missing from its list
  (`OLD:tests/src/_shared/classification_audit.md:L8-L26`); the contract's skip
  list "must cite a reason" and "being short is a quality signal"
  (`OLD:tests/src/_shared/transformer_contract.md:L484-L500`); a static
  no-`print()` check (`OLD:tests/src/logging/no_prints.md`); and
  wall-clock gates: explore speed-up >= 5x, multi-connection parallelism
  >= 6x (`OLD:tests/src/helpers/explore_shared_prefix_regression.md:L202-L251`,
  `OLD:tests/src/concurrency/INDEX.md`).
- **Not specified anywhere in this batch:** a coverage threshold, a mutation
  score, a type-check or lint gate, a docs gate. (Those live in standards
  files outside this batch.)
- **Status of the gates:** none implemented. `function_registry.md` and
  `function_registry_actual.md` contain only placeholder rows in every table
  (`OLD:validations/function_registry_actual.md:L60-L90`, approximate), and
  the diff tool `just diff-registry` is "to be built". The whole system
  depends on dispatching hundreds of agent runs
  (`OLD:validations/framework.md:L478-L520`, approximate); that is the
  process-outgrows-product pattern the baseline records.

## Pipeline-level parity

**Confirmed: no attempt in this batch specified a pipeline compared against a
scikit-learn pipeline.** Evidence:

- The manifest marks `sqlearn.Pipeline` as "n/a": "Pipeline is plumbing...
  validated end-to-end by pipeline validators (future, not in current
  scope)" (`OLD:validations/manifest.md:L293-L297`). `pipe.sql()` is "n/a ...
  tested via per-formula validators" (`L353`). `Columns`, `Union` and
  `sq.quick()` are also "n/a".
- The framework puts "End-to-end pipeline validators ... future work under
  `validations/pipelines/`" under Out of scope
  (`OLD:validations/framework.md:L889-L892`). No such folder appears in the
  layout (`L218-L330`). That is a one-line deferral, with no design.
- A validator takes one 1-D `data` array per case and one `canonical()`
  function (`OLD:templates/validator.py:L85`, `L148-L205`), so a
  `Pipeline([Imputer, Scaler])` has no place in the template (inference).
- The test specs that do build pipelines assert SQL text, query counts and
  internal consistency, not agreement with another library: composition
  snapshots (`OLD:tests/src/compiler/sql_snapshots.md:L285-L364`),
  `Impute -> Scale` cached against uncached within 1e-9
  (`OLD:tests/src/helpers/explore_caching_correctness.md:L24-L50`), and
  round-trip equality (`OLD:tests/src/precision/roundtrip.md:L128-L180`).
  The closest thing is contract test 9, single transformer, `rtol=1e-6`.
- **Worse than absent: the specs encode the defect.** The golden snapshot
  `composition.sql` for `Pipeline([Impute("mean"), Scale()])` on
  `a = 1,2,NULL,4,5` and `b = 10,NULL,30,40,50` is
  `(COALESCE("a",3.0) - 3.0) / NULLIF(1.5811388300841898, 0)` and the same
  for `b` with `32.5` and `14.79019945774904`
  (`OLD:tests/src/compiler/sql_snapshots.md:L361-L364`). My arithmetic: the
  population standard deviation of the four non-null `a` values is
  sqrt(10/4) = 1.5811..., while after mean imputation (five values) it would
  be sqrt(10/5) = 1.4142...; for `b`, sqrt(875/4) = 14.790... against
  sqrt(875/5) = 13.229. So the constants were learned from the un-imputed
  column, which is exactly what scikit-learn's
  `Pipeline([SimpleImputer(), StandardScaler()])` would not do (inference
  on the sklearn side; the arithmetic is mine). The spec calls this "the
  key composition result" (`L366-L380`, approximate). A single parity test
  against scikit-learn would have failed on it.
- The query-count test makes it a requirement: `Impute, Scale, MinMaxScale,
  Winsorize, RobustScale` must run as one aggregate query, "if the counter
  reads 5, batching is broken"
  (`OLD:tests/src/compiler/layer_batching.md:L76-L89`),
  and `test_expression_inlining` only substitutes static steps into
  aggregates (`OLD:tests/src/compiler/fit_queries.md:L99-L114`). The layer
  boundary rule tested is "a boundary only after a step that is dynamic AND
  changes the schema" (`OLD:tests/src/compiler/layer_planning.md:L125-L148`);
  a dynamic step that only changes values never ends a layer, which is the
  fit defect stated as a test (inference from the rule and the
  one-query expectation). `OneHot` after `Impute, Scale` does get a layer
  boundary, so the set query and `MinMaxScale` are staged
  (`layer_batching.md:L100-L115`), but the values `Scale` learns are
  still not staged after `Impute`.

## Against v0.4 as built

What v0.4 built is in `sqlearn-v04/notes/D-validation.md`; compared here.

- **Reference.** April: arbitrary precision, per formula, from a primary
  source. v0.4: Decimal(50) run once by hand for `Scale`; scikit-learn and
  pandas as reference.
- **Tolerance.** April: five-layer cascade in ULP and abs/rel. v0.4:
  hand-picked `atol`/`rtol`, no ULP.
- **Datasets.** April: bundled parquet plus fixed-seed generated. v0.4:
  downloaded, gitignored, skipped in CI.
- **Gate.** April: per-PR `run_all --strict` plus a release gate. v0.4: ruff,
  pyright, pytest and coverage 90; no parity gate.
- **Pipeline parity.** April: deferred. v0.4: none.
- **Snapshots.** April: six goldens that fail when missing (fixtures
  harness). v0.4: auto-create on first run, so they pass.
- **Hypothesis.** April: 2 properties in the contract. v0.4: 2 files of
  SQL-structure properties.
- **Mutation.** April: none in this batch. v0.4: `mutmut` configured, not in
  CI.
- **Contract.** April: 11 tests x about 28 built-ins, "inherited from the old
  project". v0.4: contract-style tests per file, no single parametrised
  contract.
- **Verification ledger.** April: `function_registry` tables, empty. v0.4:
  `features/verification/`, one feature.

Further notes:

- The spec **inherits from v0.4 and keeps its flaws.** The fixtures, six
  snapshots, `TestClassifyStepTier*`, `TestPlanFit`, `TestBuildFitQueries`
  are "ported verbatim" from the older project
  (`OLD:tests/src/compiler/INDEX.md:L14-L19`). Inference:
  v0.4 has a snapshot called `impute_then_scale.sql` (its `D-validation.md`
  file list; contents not checked), so the April plan probably froze v0.4's
  behaviour rather than reviewing it. The "older project" is
  `/Users/tomas/Desktop/coding/sqlearn`, not necessarily v0.4 itself.
- The snapshot harness is stricter than v0.4's: a missing golden file
  fails (`OLD:tests/src/_shared/fixtures.md:L183-L187`; the other copy in
  `sql_snapshots.md:L62` asserts existence too, but its update branch ends in
  `pytest.skip`). Two harness versions exist in the spec and differ in
  detail.
- The April plan also admits v0.4 shipped a claim that was not true:
  "v0.4 claims shared-prefix caching but delivers full-config metric
  memoization" (`OLD:tests/src/helpers/INDEX.md`, "Implementing agent
  notes"), and writes a regression test that "fails on v0.4 code" for it.
  This is evidence for the baseline point that documents drifted from code.
- Nothing from the April validation framework is in v0.4: v0.4 ended on 12
  April, the framework is dated 13 April (`OLD:validations/INDEX.md:L3`).
  The framework was therefore designed after seeing v0.4 and does answer
  its gaps (ULP, bundled data, a gate) but never ran.

## New against the baseline

- **ULP as a unit,** a library-by-library cascade, and per-operation default
  bounds. The baseline says early attempts used fixed tolerances and later
  ones wrote "bounds set from measurement" but enforced nothing; this adds a
  fully drafted cascade with a layer order and a commit-message rule for
  changing it.
- **A validation architecture for 200+ functions run by agents:** manifest,
  3-strike escalation, `meta_tests`, committed escalation files, spot
  checks. Worth knowing as a warning more than a design (see Worth keeping).
- **Exact arithmetic inside the engine:** the `precision="decimal38"` mode
  (DuckDB `DECIMAL(38,18)`), with tests that compare to Python `Decimal` at
  50 digits over 1,000,000 rows and a 20,000-row case of 2.7e-15 float drift
  (`OLD:tests/src/precision/comparison.md:L72-L139`, `L219-L264`), stats
  stored as strings in the config so they survive JSON
  (`OLD:tests/src/precision/roundtrip.md:L26-L60`), per-column dtype override
  winning over the pipeline mode (`overrides.md`), an overflow that warns and
  falls back to DOUBLE rather than raising (`comparison.md:L266-L295`), and
  per-adapter behaviour (arrow, polars, DuckDB keep DECIMAL; numpy and pandas
  convert with a warning, `output_adapters.md`). This bears on the open
  question about "exact reference" in `validation-method.md`.
- **Transformer contract with 12 named edge cases** (single row, two rows,
  constant, empty, all-NULL, 1e308, 1e-300, mixed extremes, NaN distinct from
  NULL, Unicode names, names with spaces, names that are SQL keywords),
  4 composition scenarios, pickle and clone independence, and 2 hypothesis
  properties, for about 530 generated tests
  (`OLD:tests/src/_shared/transformer_contract.md:L326-L481`).
- **Classification audit:** a parametrised test that every built-in's
  declared static/dynamic class matches its `discover()` and that the list is
  exhaustive (`OLD:tests/src/_shared/classification_audit.md:L113-L242`).
- **Read-only invariant:** after every operation the user's source table is
  "byte-identical"; scratch work lives in a separate schema
  (`OLD:tests/src/helpers/connect_readonly_invariant.md:L1-L60`).
- **Query-count regression** via a `query_counter` wrapper
  (`OLD:tests/src/compiler/layer_batching.md:L20-L70`) as a way to test "one
  query per pipeline" claims. The wrapper ignores `DESCRIBE`, `SHOW`, `SET`
  and `PRAGMA` by prefix.
- **Guarding queries that read, not just values:** `audit` must not execute
  a query (`OLD:tests/src/core/audit/trace_correctness.md:L132-L150`), `check`
  never raises (`OLD:tests/src/helpers/check.md:L141-L160`).
- **Mutation testing: absent** from this batch (the matches for "mutation"
  are object mutation in `immutability.md:L59` and
  `pipeline_thread_safety.md:L124`). The baseline row on v0.4's unused
  mutmut stands; nothing newer is specified here.
- **Wall-clock thresholds as tests** (5x, 6x), marked slow
  (`OLD:tests/src/helpers/explore_shared_prefix_regression.md:L202-L251`). The
  baseline does not mention timing gates; v0.4 had wall-clock bounds only in
  benchmarks.

## Contradicts the baseline

- **"v0.4 and `sqlearn_000` wrote a strong method and never enforced it":**
  true here too, but the April plan is not the same method. v0.4's method
  (Decimal(50), "one decade above observed") was a prose rule; this spec
  uses Decimal/Fraction/mpmath, primary-source canonicals and a ULP
  cascade (though the lines about `Fraction` are in the template's
  docstring, not enforced). So "never enforced" holds, "same method" does
  not.
- **"No attempt ever compared a whole pipeline":** survives, but it is not
  true that no attempt *mentioned* it. The manifest and framework defer it
  explicitly (see above). It had a named home (`validations/pipelines/`) and
  was pushed behind per-formula work.
- **"Portability was never tested beyond parsing":** this spec adds
  adapters that would execute the same formula on Postgres, Snowflake and
  BigQuery (`OLD:validations/framework.md:L56-L72`) and a comparison of
  library results across engines. Still unbuilt, so the factual claim about
  what was *tested* is unchanged; the claim about what was *planned* is
  incomplete.
- **"Parity tests were few, hand-tuned, sometimes skipped":** here, parity
  is a contract test applied to every built-in (about 28), not a hand-picked
  few. In the spec it is skipped when `_get_reference_impl` returns `None`
  (`transformer_contract.md:L243-L248`), so skipping is designed in.

## Confirms the baseline

- **Fit defect:** designed in again, and now golden-tested (see Pipeline-level
  parity). `Tomosius/sqlearn`'s "substitute non-learning steps into later
  aggregates" is exactly the `AVG(col * 2)` inlining test
  (`OLD:tests/src/compiler/fit_queries.md:L99-L114`); dynamic steps ahead of
  a learning step are not substituted.
- **Tests that assert a known divergence with its reason:** the manifest
  entries do this (`OLD:validations/manifest.md:L100-L120`), e.g. library
  differences for ddof, quantile interpolation and tie handling, and
  `test_scale_float64_drifts` "documents the gap" (`comparison.md:L93-L109`).
  Snapshots that fail when missing: the fixtures harness (`fixtures.md:L183`).
- **Process outgrew the product:** a 908-line framework page, a 414-line
  manifest, escalation tiers, spot-check policy, per-function registries,
  and two empty tables for status kept by hand, with no library code behind
  them. Status in several places (version file, registry expected, registry
  actual, escalation files) is the pattern the baseline calls drift.
- **Hand-typed numbers wrong:** counts such as "28 transformers x 11 = 308"
  versus "15 x 28 = 420 + 112 = ~530" in the same page
  (`OLD:tests/src/_shared/transformer_contract.md:L478-L481` against `L515`);
  the contract is titled "11 tests" but grows to 15 plus extras. Also the
  manifest's `StandardScaler` claim above.
- **Hypothesis for structure, not numbers** (v0.4 pattern): same here.
- **Parity tolerances loosened to fit:** `rtol=1e-6` in contract test 9
  while the cascade says 4 ULP.
- **API:** the specs assume `learn`/`apply`, `columns=`, `target`, `out=`
  rather than scikit-learn's `fit`/`transform`/`fit_transform`
  (e.g. `OLD:tests/src/_shared/transformer_contract.md:L106-L113`), and
  `sq.Scale`, `sq.MinMaxScale` as names. This repeats the renames the
  baseline says need an ADR; a `sq.connect()` global is also assumed in every
  test.

## Worth keeping

- The **separation** of "does it run" tests from "does it match the exact
  answer" validation, as separate gates.
- An exact reference built from a primary source and never from a library;
  per-function citation with date; a reference computed in the same
  precision the claim is made in (Fraction for rational results, mpmath for
  transcendentals, a stated rule for iterative fits).
- **ULP and the layered tolerance cascade,** provided every number in it is
  measured and recorded with the run that produced it (the commit-message
  rule at `OLD:templates/tolerances.toml:L19-L26` is good).
- A **dtype check** next to the value check; integer-valued results exact.
- The **12 edge cases**, especially NaN versus NULL, SQL-keyword and Unicode
  column names, and the two-row case.
- **Classification audit with exhaustiveness check,** and a contract skip
  list that needs a reason.
- **Snapshot harness that fails on a missing file** (not the update branch
  with `skip`), and snapshots of SQL as the review artefact.
- **Query-count tests** as a regression guard on "one query" claims, once
  they count what the user would expect (staged fit may cost more than one
  query; the test should say how many and why).
- **Read-only source invariant** and `audit`/`check` "never executes /
  never raises" tests.
- **DECIMAL mode tests,** with the caveats below.
- Do not copy: the agent-dispatch machinery before there is a library; a
  `Pipeline` marked "n/a"; the `rtol=1e-6` contract check; goldens that
  record the unstaged-fit SQL; hand-written "critical notes" (the ddof one is
  wrong).

Caveats on the DECIMAL tests (inference): the float64 test asserts the mean
drifts by more than 1e-10 on 1,000,000 rows of about 12,345
(`comparison.md:L93-L109`),
yet v0.4 measured about 2.66e-15 on 20,000 rows (`D-validation.md` of v0.4),
so that assertion may well fail on real DuckDB. The title says "bit-exact"
but the check is `< 1e-17` against a 18-digit fixed scale, which is
exactness up to the scale, not bit-identity. `Decimal.sqrt()` at 50 digits is
used as truth for the standard deviation.

## Files covered

Folder `OLD/_old/projects/sqlearn/validations/` (5 files)

- [x] validations/INDEX.md - folder index; "validation is separate from tests".
- [x] validations/framework.md - runner, `just validate`, 3-strike chain, CI,
  release gate, fixtures list, out-of-scope pipelines.
- [x] validations/manifest.md - dispatch manifest, 10 sample entries, roster of
  formulas, Pipeline "n/a".
- [x] validations/function_registry.md - expected-state tables, all empty
  (second half read after first pass).
- [x] validations/function_registry_actual.md - hardener-filled tables, all
  empty; diff tool unbuilt.

Also read for context (outside the assigned folders, one file each, not
counted): `OLD/_old/templates/tolerances.toml` (full) and
`OLD/_old/templates/validator.py` (first 215 lines and greps).

Folder `OLD/_old/projects/sqlearn/tests/` (60 files)

- [x] tests/INDEX.md - states the specs describe tests, code lives elsewhere.
- [x] tests/src/INDEX.md - subsystem table, "tests flow private to public".
- [x] tests/mcp/INDEX.md - empty stub.
- [x] tests/gui/INDEX.md - empty stub.
- [x] tests/src/_shared/INDEX.md - shared fixtures, contract, audit.
- [x] tests/src/_shared/fixtures.md - 7-row fixtures, snapshot harness.
- [x] tests/src/_shared/transformer_contract.md - 11 (to 15) tests, 12 edge
  cases, hypothesis, rtol 1e-6.
- [~] tests/src/_shared/classification_audit.md - heads, purpose, structure.
- [x] tests/src/compiler/INDEX.md - which tests are ported from the older
  project.
- [~] tests/src/compiler/_mocks.md - shared mock classes; not read beyond the
  names imported by others.
- [~] tests/src/compiler/classification.md - three tiers and defensive cases.
- [~] tests/src/compiler/schema_change.md - detect_schema_change cases.
- [x] tests/src/compiler/layer_planning.md - boundary rule tests.
- [x] tests/src/compiler/fit_queries.md - batching, inlining of static steps.
- [~] tests/src/compiler/compose_transform.md - composition cases, list only.
- [x] tests/src/compiler/layer_batching.md - query_counter; one query for five
  dynamic steps.
- [x] tests/src/compiler/sql_snapshots.md - six goldens including
  `composition.sql`.
- [x] tests/src/precision/INDEX.md - DECIMAL mode plan and order.
- [x] tests/src/precision/comparison.md - Decimal(50) ground truth, 1M rows.
- [~] tests/src/precision/roundtrip.md - stats as strings; head and test list.
- [~] tests/src/precision/overrides.md - dtype override precedence.
- [~] tests/src/precision/output_adapters.md - arrow/polars/duckdb/numpy/pandas.
- [x] tests/src/errors/INDEX.md - hierarchy plan.
- [~] tests/src/errors/hierarchy.md - not opened beyond the index.
- [~] tests/src/errors/messages.md - not opened beyond the index.
- [~] tests/src/errors/chaining.md - not opened beyond the index.
- [~] tests/src/errors/backward_compat.md - dual inheritance (ValueError,
  RuntimeError); test list.
- [x] tests/src/logging/INDEX.md - logger plan.
- [~] tests/src/logging/hierarchy.md - not opened beyond the index.
- [~] tests/src/logging/levels.md - not opened beyond the index.
- [~] tests/src/logging/extra_dict.md - not opened beyond the index.
- [~] tests/src/logging/no_prints.md - static no-print check, test list.
- [x] tests/src/warnings/INDEX.md - eight checkers plan.
- [~] tests/src/warnings/checkers.md - checker positive/negative cases, list.
- [~] tests/src/warnings/api.md - suppression and threshold API, list.
- [~] tests/src/warnings/integration.md - no extra queries with warnings, list.
- [x] tests/src/helpers/INDEX.md - explore caching, v0.4 gap note.
- [~] tests/src/helpers/check.md - leakage, ordering, drift; test list.
- [~] tests/src/helpers/explore_caching_correctness.md - cache equals no cache,
  1e-9.
- [~] tests/src/helpers/explore_caching_lifecycle.md - persist and resume.
- [~] tests/src/helpers/explore_persist_resume.md - kill and resume.
- [~] tests/src/helpers/explore_shared_prefix_regression.md - 5x speed-up test.
- [~] tests/src/helpers/connect_readonly_invariant.md - source tables untouched.
- [~] tests/src/helpers/connect_registry.md - connection registry.
- [~] tests/src/helpers/connect_byo.md - bring your own connection.
- [~] tests/src/helpers/connect_migration.md - migration of connect calls.
- [~] tests/src/helpers/connect_pipeline_binding.md - pipeline-to-connection.
- [x] tests/src/concurrency/INDEX.md - parallelism factor >= 6x.
- [~] tests/src/concurrency/single_connection_threads.md - not opened beyond
  the index.
- [~] tests/src/concurrency/multi_connection_parallel.md - timing test.
- [~] tests/src/concurrency/pipeline_thread_safety.md - cross-thread errors,
  clone.
- [~] tests/src/concurrency/async_wrapping.md - not opened beyond the index.
- [x] tests/src/core/INDEX.md - FrozenPipeline and audit specs.
- [~] tests/src/core/frozen_pipeline/freeze_basic.md - freeze basics.
- [~] tests/src/core/frozen_pipeline/schema_validation.md - strict schema check.
- [~] tests/src/core/frozen_pipeline/immutability.md - immutable params.
- [~] tests/src/core/frozen_pipeline/roundtrip.md - config round-trip.
- [~] tests/src/core/audit/trace_correctness.md - audit trace; no query run.
- [~] tests/src/core/audit/column_drilldown.md - not opened beyond the index.
- [~] tests/src/core/audit/pretty_print.md - not opened beyond the index.

Folders `OLD/_old/projects/sqlearn/mcp/`, `gui/` and
`OLD/_old/projects/sqlearn-pro/` (tests, mcp, gui)

- [x] sqlearn/mcp/INDEX.md - "planned, not yet implemented".
- [x] sqlearn/gui/INDEX.md - "planned, not yet implemented".
- [x] sqlearn-pro/tests/INDEX.md - empty stub.
- [x] sqlearn-pro/tests/src/INDEX.md - stub; says each architecture file "has
  a matching test spec here" but none is present.
- [x] sqlearn-pro/tests/mcp/INDEX.md - empty stub.
- [x] sqlearn-pro/tests/gui/INDEX.md - empty stub.
- [x] sqlearn-pro/mcp/INDEX.md - stub (10 lines, size from file list).
- [x] sqlearn-pro/gui/INDEX.md - stub (10 lines, size from file list).

Notes on coverage: `sqlearn-pro/tests/` holds four index files only, no test
specs. The "skimmed" files were read by headings, test names and their first
20 to 30 lines; their subject is not numerical validation, so they bear on
the conclusions only through the greps for sklearn, tolerance, hypothesis,
mutation, dataset and download terms across the whole `tests/src` tree,
which returned the hits cited above and no others. No file hung or failed to
read.

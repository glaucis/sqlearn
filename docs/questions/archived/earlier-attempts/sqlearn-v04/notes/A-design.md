---
type: architecture
tags: [sqlearn, sql-compiler, fit-layers, sqlglot, design-decisions, old-version]
summary: "Design and decisions review of the old sqlearn v0.4 SQL compiler: fit layering, learned state, sqlglot usage and documented failures."
related: [docs/questions/archived/earlier-attempts/sqlearn-v04/notes/A-design.md]
mdindex: [type=4ca303, tags=77aa7e, summary=21080e]
---
# Batch A — design and decisions (old sqlearn v0.4)

OLD = "/Users/tomas/Desktop/Desktop - Tomas’s MacBook
Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn". Read only. Citations
are `OLD:path:Lnn`. "Doc says" means what a document claims; "admits" means a
document records a failure. Four citations go outside the batch, into `src/` and
`tests/`, to check a load-bearing claim. They are marked **[src check]**.
Inference is marked *(inference)*.

## Summary

- **Shape:** a "compiler". Each transformer returns sqlglot ASTs from
  `discover()` (aggregates), `discover_sets()` (DISTINCT queries),
  `expressions()` (column exprs, with automatic passthrough) and `query()`
  (a whole SELECT, for windows and joins). Learned values are flat
  string-keyed dicts `params_`/`sets_`, inlined as literals at `sql()` time
  (OLD:docs/architecture/transformer-contract.md:L35-L129,
  OLD:docs/architecture/serialization.md:L11-L27).
- **Fit:** "layers". Every dynamic step's aggregates go into one SELECT
  against the layer's input. A new layer, over a temp view, starts only after
  a step that is both dynamic and schema-changing
  (OLD:docs/architecture/compiler.md:L130-L196).
- **Same defect as sqlearn_000, in another form:** inside a layer a later
  step learns from the raw input. In `Impute → Scale`, Scale's std comes from
  un-imputed data. A test admits this and weakens its assertion to
  `sql() is not None`
  (OLD:tests/transforms/scalers/test_scalers_deep.py:L109-L113 **[src check]**).
- **API:** departed from scikit-learn on purpose, in ADR-002:
  `learn`/`apply`/`sql`, no `get_params`/`set_params`/`fit_transform`, `learn()`
  returns a new object, short names (`Scale`, `OneHot`). It argues that "fit"
  means model training
  (OLD:docs/decisions/ADR-002-learn-apply-naming.md:L14-L44). This contradicts
  the new project's ADR 0003.
- **sqlglot:** the IR from day one (ADR-001). Six dialects are "tested" only
  by checking that the SQL compiles. The doc itself admits a breaking change:
  "v30 broke pyright with 292 errors", so the dependency is pinned `<30`
  (OLD:docs/decisions/ADR-001-sqlglot-ast.md:L52-L62, OLD:pyproject.toml:L24).
- **Runtime deps:** `sqlglot`, `duckdb` and `numpy`, plus optional
  `scipy`/`statsmodels` (OLD:pyproject.toml:L23-L31). numpy is used for
  Mahalanobis and target inverse (OLD:docs/benchmarks/v0.4.0-report.md:L80-L86,
  OLD:TODO.md:L117-L130).
- **Scope drift:** v0.4 was an EDA release (six analysis primitives,
  `explore`/`explain`, seven transformers) built on a core with known bugs
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L60-L81). Its
  CHANGELOG says "Fixed: None" (OLD:CHANGELOG.md:L135-L137).
- **Docs contradict their measurements:** the release notes say deep analyse
  in under 10 s was "met" (OLD:docs/notes/what-is-new-in-v0.4.md:L158). The
  benchmark report measured ~39 s and relaxed the bound to 60 s
  (OLD:docs/benchmarks/v0.4.0-report.md:L88-L92).
- **Validation was mostly weak:** rtol 1e-14 for the basic scalers, but
  `corr>0.95` and `corr>0.90` for the quantile and power scalers, and "N/A"
  for TargetEncode, which was broken: every category got the same value
  (OLD:REVIEW.md:L67-L77, OLD:TODO.md:L7-L15).
- **Worth keeping:** expressions return only the columns they change, with
  passthrough automatic (OLD:docs/architecture/transformer-contract.md:L75-L96);
  "if not provably static, treat as dynamic"
  (OLD:docs/architecture/compiler.md:L311-L322); the JSON-state invariant
  (ADR-003); `sql()` as a code-generation step that needs no data
  (OLD:docs/architecture/overview.md:L49-L55); the sampling-caveat discipline
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2234-L2278).

## Fit execution

**Doc says:**

- `learn()` runs "1–3 queries per layer, batched"
  (OLD:docs/architecture/overview.md:L33-L37).
- "3–4 queries for the entire pipeline, regardless of step count"
  (OLD:docs/architecture/compiler.md:L196).
- A layer boundary comes only after a step that is both dynamic and
  schema-changing (OLD:docs/architecture/compiler.md:L132-L134). Code agrees
  (OLD:src/sqlearn/compiler/layers.py:L206-L224 **[src check]**).
- Layer 0's aggregates for Impute and Scale run in one SELECT against
  `'train.parquet'` (OLD:docs/architecture/compiler.md:L164-L175). The next
  layer queries the previous layer's output as a temp view
  (OLD:docs/architecture/compiler.md:L183-L194).
- `discover(columns, schema, y_column)` gets no upstream expressions
  (OLD:docs/architecture/transformer-contract.md:L35-L62). It therefore
  cannot see what earlier steps in its layer did.
- The aggregate query is `FROM <source>` per layer
  (OLD:src/sqlearn/compiler/compile.py:L181-L198 **[src check]**).
- Set queries are separate, one per column. The doc says they run
  "after all discover()" and may be batched with UNION ALL beyond three
  columns (OLD:docs/architecture/compiler.md:L199-L208). This contradicts
  "3–4 queries regardless of step count": the count grows with the number of
  categorical columns.
- Layers are "a fit-time optimization". Transform is always one statement
  (OLD:docs/architecture/compiler.md:L158-L160).
- Depth > 8 auto-promotes to a CTE, by heuristic
  (OLD:docs/architecture/compiler.md:L85-L91). No evidence it was measured.

**Admits failed:**

- The layer rule lets a mean or std be learned before an upstream imputation.
  The deep scaler test notes that "sqlearn learns Scale stats on ORIGINAL
  data… sklearn imputes first… Compare SQL only"
  (OLD:tests/transforms/scalers/test_scalers_deep.py:L109-L113 **[src check]**).
  The difference was filed as "behavioral, not a precision issue" instead of
  being fixed.
- Lazy or late learning went wrong twice:
  - TargetEncode's `_mark_fitted` was dead code, so all categories got the
    global mean (OLD:TODO.md:L7-L15).
  - PowerScale's lambda was computed inside `expressions()`, so it was lost
    when serialised before `apply()`/`sql()` (OLD:TODO.md:L145-L191).

  Both are fit work done outside the fit plan.
- The TargetEncode "fix" queries the backend from `expressions()` with an
  f-string, and swallows errors into the global-mean fallback
  (OLD:TODO.md:L39-L80). The shipped code does the same
  (OLD:src/sqlearn/transforms/encoders/target_encode.py:L103-L135
  **[src check]**). After deserialisation, with no learn source, it falls
  back silently to the global mean. That is wrong output with no error.
- DropLowVariance's `output_schema` depended on call order
  (OLD:TODO.md:L321-L332).
- The universal `group_by`/`order_by` were "stored but not yet consumed by the
  compiler", a silent no-op (OLD:TODO.md:L274-L289,
  OLD:CHANGELOG.md:L150). This matches sqlearn-000-review's finding on
  universal parameters.

**For decision (1):**

- Batching all aggregates against one input is wrong whenever a later
  aggregate reads a column an earlier step rewrote. That holds even when the
  schema does not change. Both old repos made this mistake.
- The rule that would have been right *(inference)*: start a new stage when
  a dynamic step reads a column whose expression an earlier dynamic step in
  the stage modified. Alternatively, let `discover` take the upstream
  expression (e.g. `STDDEV_POP(COALESCE(price, <learned median>))`). That
  forces ordering, because the literal must already be known.
- `explore()` fits per fold and caches fitted prefixes in a Python dict keyed
  by `(prefix_hash, fold_idx)`
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L1751-L1754). This
  is useful precedent for model selection over stage-wise fit.
- Folds come from a *view* with `ROW_NUMBER() OVER (ORDER BY RANDOM())`
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L1748-L1750).
  *(Inference)* A non-materialised view re-evaluates `RANDOM()` on each
  reference, so folds may differ between candidates and between the
  train/test sides. Not verified.

## Learned state

**Doc says:**

- State is `params_: dict[str, scalar]` and `sets_: dict[str, list[dict]]`,
  plus resolved `columns_` and schemas. All of it must be JSON. ASTs are
  derived, never stored (OLD:docs/architecture/serialization.md:L9-L27).
- Keys are flat strings: `"price__mean"`, with the step name added as a
  prefix in the layer query, e.g. `scale__price__mean`
  (OLD:docs/architecture/transformer-contract.md:L45-L51,
  OLD:docs/architecture/compiler.md:L166-L174).
- ADR-003's reasons: `to_config`, `to_python`, diffing, cross-language, no
  pickle (OLD:docs/decisions/ADR-003-json-serialization.md:L15-L40).
- Values are inlined as SQL literals: `(… - 44.2) / 12.3`
  (OLD:docs/architecture/overview.md:L84-L92).
- CountEncode puts the whole category→count map in a CASE. The doc accepts
  this: "this CASE expression gets long. That's fine"
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2103-L2123).

**Admits failed or contradicts itself:**

- Per-category TargetEncode state is encoded in key names,
  `{col}__cat__{cat}__mean` (OLD:TODO.md:L59-L76). Parsing keys with
  `rsplit("__")` breaks if a category or column contains `__`
  *(inference, from OLD:src/sqlearn/transforms/encoders/target_encode.py:L70-L74
  **[src check]**)*.
- The sentinel problem shows up again. DropCorrelated's `()` was falsy, so
  `None` was needed (OLD:TODO.md:L95-L109). A custom step with an all-NULL
  learned value left `{param}` unresolved (OLD:CHANGELOG.md:L230). This is the
  reverse case of sqlearn-000-review's "None means not fitted".
- ADR-003 promised `to_config` "deferred"
  (OLD:docs/decisions/ADR-003-json-serialization.md:L10-L11), and
  serialization.md calls it "not implemented yet"
  (OLD:docs/architecture/serialization.md:L104). Yet the v0.2 CHANGELOG lists
  `to_config`/`from_config`/`save`/`load` as shipped
  (OLD:CHANGELOG.md:L214-L215). The docs went stale.
- Nobody discusses float literal precision *(none found in batch)*. That
  agrees with sqlearn-000-review: it was never tested.
- *(Inference)* No DuckDB-table state was ever considered. The trade-off,
  large maps as CASE literals against a join to a learned table, is missing.
  CountEncode, TargetEncode and OneHot over high cardinality are where it
  bites.

## SQL representation / sqlglot / dialects

**Doc says:**

- ADR-001: sqlglot AST everywhere, "no f-string SQL… anywhere"
  (OLD:docs/decisions/ADR-001-sqlglot-ast.md:L26-L39). Rationale:
  "Multi-database support is free" and safe composition (L43-L49). A custom AST
  and string templates were rejected (L64-L84).
- The IR is "language-neutral". DuckDB is only the default backend
  (OLD:docs/architecture/overview.md:L146-L158).
- A degradation table covers `FILTER`, `MEDIAN`, `HASH` and Parquet reads
  (OLD:docs/architecture/compiler.md:L338-L352). The doc claims "Each
  transformer documents which dialects it supports".

**Evidence:**

- The doc admits a cost: sqlglot v30 broke pyright with 292 errors, and the
  dependency is pinned `<30` (OLD:docs/decisions/ADR-001-sqlglot-ast.md:L52-L62,
  OLD:pyproject.toml:L24). Pyright strict had to downgrade
  `reportUnknownMemberType` because "sqlglot stubs use **opts: Unknown"
  (OLD:pyproject.toml:L140-L147).
- AST node reuse without `.copy()` corrupted trees in three transformers
  (OLD:TODO.md:L217-L270). This is a sqlglot-specific bug class.
- The "no f-strings" rule was broken in the core:
  - TargetEncode builds SQL by f-string with unescaped `'{cat}'`
    (OLD:TODO.md:L64-L69).
  - `connect()` interpolates `memory_limit` into SQL, an injection
    (OLD:TODO.md:L195-L213).
  - Ruff `S608` (SQL injection) is ignored globally (OLD:pyproject.toml:L110).
- Dialect "tests" are six dialects × N transforms that "compile the SQL for
  each dialect and validate syntax", with Snowflake and BigQuery mocked.
  "Equivalence testing… where feasible"
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2405-L2419,
  OLD:REVIEW.md:L142). No result equivalence across engines is evidenced.
  This agrees with sqlearn-000-review.
- In practice the semantics were DuckDB-specific:
  `USING SAMPLE … (BERNOULLI, 42)`, `approx_quantile`, `histogram()`,
  `IGNORE NULLS` (claimed portable "handled by sqlglot")
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2224-L2230,
  L572-L575, L2199-L2201).

**For decision (3):** sqlglot gave composition and quoting, but the old repo
paid for it in type-checker noise, a version pin, and an AST-aliasing bug
class. Its portability claim was never verified past syntax. The
alternative-analysis in ADR-001 treats multi-database support as "a core
requirement" (L73-L74). The new project has DuckDB as its only runtime
dependency and treats multi-engine as future work, so that premise no longer
holds.

## API naming and scikit-learn conformance

- **ADR-002 rationale:**
  - "the sklearn names… told a lie"
    (OLD:docs/decisions/ADR-002-learn-apply-naming.md:L14-L23).
  - `fit()` returning `self` "prevents immutable pipelines" (L25-L28).
  - Users were "surprised". *(Inference)* There were no users before release:
    every version is "Unreleased" (OLD:CHANGELOG.md:L8, L145, L186, L241).
- **ADR-002 decisions:**
  - no `fit_transform`, no public `get_params`/`set_params`;
  - an `as_sklearn()` adapter for GridSearchCV
    (OLD:docs/decisions/ADR-002-learn-apply-naming.md:L32-L44);
  - its stated cost: "two lines instead of one", not a drop-in (L57-L63).
- **It contradicts itself:** serialization.md says constructor parameters are
  "accessible via `get_params()`"
  (OLD:docs/architecture/serialization.md:L76-L79). ADR-002 says no public
  `get_params` (L36). There is also `sq.from_sklearn()` (OLD:CHANGELOG.md:L169).
  *(Inference)* Interop kept pulling the API back towards scikit-learn.
- **Column handling:**
  - Auto column routing by `_default_columns` (`numeric`, `categorical`,
    `all`), resolved at `learn()` and cached in `columns_`
    (OLD:docs/architecture/column-routing.md:L14-L57).
  - `Columns({...}, remainder="passthrough"|"drop"|transformer)` replaces
    `ColumnTransformer` (OLD:docs/architecture/column-routing.md:L109-L152).
  - This is the "column handling" pain point the new survey names.
  - *(Inference)* `Impute` defaulting to `"all"`, with a strategy that
    "adapts per type" (L200-L201), hides a per-type default that a scikit-learn
    user would set explicitly.
- **Passthrough:** `expressions()` returns only the columns it changes, and the
  base merges the rest (OLD:docs/architecture/transformer-contract.md:L75-L96).
  This gives the uniform column rule that sqlearn-000-review found missing.
- **Universal SQL parameters:** `where`, `drop_null`, `group_by`, `order_by`
  and `dtype` on every transformer (OLD:CLAUDE.md:L199-L202). Two were never
  implemented (OLD:TODO.md:L274-L289). Same lesson as sqlearn_000.
- **Immutability:** `learn()` returns a new pipeline, and `+=` makes a new
  one (OLD:docs/architecture/transformer-contract.md:L274-L284). This is the
  same departure as sqlearn_000's deep copy.
- **Pipeline is a Transformer:** nests at zero SQL cost
  (OLD:docs/architecture/transformer-contract.md:L272-L284).

## Validation

- **Process:** "comparison-first": register the feature in `features/`, then
  implement, compare, and update the registry. On failure, check against
  `Decimal` at 50 digits and record it in `tests/PRECISION.md`
  (OLD:CLAUDE.md:L163-L177).
- **ADR-009 ledger:** `features/verification/` is a CSV ledger. It holds
  ground truth (`Decimal` ≥50 digits), a primary reference and secondary
  references (OLD:docs/decisions/ADR-009-execution-workflow.md:L64-L68).
  Inference: `features/` now holds only INDEX.md and composition.md, so the
  ledger may never have been populated. Outside batch, not verified.
- **Tolerances, as recorded:**
  - rtol 1e-14 "machine precision" against StandardScaler, MinMaxScaler,
    RobustScaler, SimpleImputer and OneHotEncoder (OLD:CHANGELOG.md:L221);
  - rtol 1e-14 against numpy for exp and log (OLD:REVIEW.md:L42-L44);
  - QuantileTransformer `corr>0.95` and PowerTransformer `corr>0.90`
    (OLD:REVIEW.md:L67-L68), which cannot detect a wrong formula;
  - TargetEncode "N/A (smoothing differs from sklearn)" (OLD:REVIEW.md:L76),
    while the encoder was broken (OLD:TODO.md:L7-L15);
  - DropCorrelated and SelectKBest "N/A" (OLD:REVIEW.md:L110-L112);
  - the v0.4 spec's default is `rtol=1e-10, atol=1e-14`
    (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2389-L2393).
- **Admits:** the test for the Impute→Scale mismatch with scikit-learn was
  weakened to a shape check (src check above).
- **Bugs found by agent code review, not by comparison tests:** three review
  agents found six bugs and five warnings after the v0.3 suite passed with
  2,278+ tests (OLD:TODO.md:L1-L3, OLD:REVIEW.md:L145).
- **Datasets:** `just download-data` fetches about 50 MB, "no API keys"
  (OLD:README.md:L129-L134, OLD:CLAUDE.md:L122). That is network at
  test-setup time, which ADR 0006 now forbids; the same finding as
  sqlearn-000-review. Benchmark corpora are generated in DuckDB with
  `RANGE()`, `RANDOM()` and `HASH()`, which is offline and good
  (OLD:docs/benchmarks/v0.4.0-report.md:L10-L12).
- **Property ideas:**
  - percentiles monotone; missing patterns sum to the row count;
    `cardinality_ratio ∈ [0,1]`
    (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2421-L2428);
  - the z-score Chebyshev bound, written as `≤ 100/threshold²` (L2426), which
    is a *percentage*. *(Inference)* It is correct only if read as percent;
    as stated it is ambiguous.
- **Iterative or no-closed-form:** no rule. PowerScale's lambda (iterative)
  was accepted at `corr>0.90`. That is evidence that the "iterative
  algorithms" open point needs an explicit rule, not a correlation.

## Other ideas worth keeping

- **Hard safety rule:** "If the compiler cannot prove… a step is static, it
  MUST treat it as dynamic". A false static gives silent corruption; a false
  dynamic costs one query (OLD:docs/architecture/compiler.md:L311-L322).
  Classification has three tiers, with CI checking declared against actual
  for built-ins (L243-L309).
- **Interface resolution:** `query()` (own CTE) wins over `expressions()`
  (inline). If neither is implemented, raise `CompilationError`
  (OLD:docs/architecture/compiler.md:L57-L72).
- **Execute against export:** `apply()` needs data and a backend; `sql()`
  needs neither (OLD:docs/architecture/overview.md:L129-L144). This is a
  clean seam for the node editor.
- **Schema-change detection:** compare `output_schema()` structurally on names
  *and* types, and treat a raise as "changed"
  (OLD:docs/architecture/compiler.md:L324-L336).
- **Row identity for branch merges:** inject `ROW_NUMBER()` only when a branch
  has row operations, or use `row_key=`. The doc admits non-determinism
  without a key (OLD:docs/architecture/composition.md:L24-L59, L139-L153).
  There are four merge strategies (L61-L120). Sort is allowed only as the
  last step (L132).
- **Custom-transform levels:** an `Expression` template, `custom(learn={…})`,
  or a full subclass (OLD:docs/architecture/transformer-contract.md:L210-L237).
- **Result objects:** frozen dataclass with `__str__`, `_repr_html_` and
  `to_dict()`, and no plotting dependency
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L281-L337).
  Errors name close matches via `difflib`, and a timeout returns no partial
  result (L339-L367).
- **Sampling honesty:** every sampled result carries `sampled`,
  `sample_size` and a warning, and the docs list what uniform sampling breaks
  (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2241-L2278).
- **No hosted execution** (ADR-006) is consistent with the new ADR 0006
  (OLD:docs/decisions/ADR-006-no-hosted-execution.md:L22-L25).
- **Benchmarks that fail on regression**
  (OLD:docs/benchmarks/v0.4.0-report.md:L16-L17). The relaxations are documented
  in-repo with reasons (L69-L97). That is honest, even though the notes
  contradict it.

## What went wrong

1. **Fit ordering:**
   - Within-layer aggregates read the raw input.
   - The mismatch with scikit-learn was suppressed in a test instead of fixed
     (src check). The same root defect as sqlearn_000.
2. **Fit work leaked into transform:** TargetEncode and PowerScale learned
   inside `expressions()` (OLD:TODO.md:L7-L191). Serialisation, purity and
   correctness all broke.
3. **Silent fallbacks:**
   - `except Exception: …global_mean` (OLD:TODO.md:L77-L79);
   - "document that apply() must be called before save()" offered as a fix
     (OLD:TODO.md:L176-L177);
   - `try: self.sql() except Exception: pass` (OLD:TODO.md:L183-L187).
4. **The ADR rule was broken by its own fixes:** f-string SQL and injection
   (OLD:TODO.md:L64-L69, L195-L213), with `S608` ignored
   (OLD:pyproject.toml:L110).
5. **Connection model:**
   - ADR-008's title says "per process". Its body says "per database file"
     (OLD:docs/decisions/ADR-008-single-connection.md:L25-L30), then "One
     connection per process" again (L68).
   - It rejected "user-managed connections", with
     `sq.connect(...)` as the example (L131-L140). v0.3 then shipped
     `sq.connect()` (OLD:CHANGELOG.md:L152).
   - The module-level mutable state is admitted (L117-L120).
6. **Scope:**
   - v0.4 added six EDA primitives and search on top of a core with open
     correctness bugs.
   - The spec says the primitives are "Tool-only, not advisory"
     (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L87-L89), yet
     ships `recommendation` and `encoding_recommendation` fields (L958-L964,
     L1273-L1282).
   - `explore()` scores rmse and r2 with no model defined anywhere in the
     spec (L1641-L1761), while the overview says sqlearn is "Not a model
     trainer" (OLD:docs/architecture/overview.md:L165-L168). *(Inference)*
     The predictions' source is unspecified.
   - Mutual information was in scope (spec L118), proposed through
     `sklearn.feature_selection` at runtime (L1435-L1437). It is absent from
     the CHANGELOG description (OLD:CHANGELOG.md:L36-L40).
7. **Claims against measurements:**
   - Spec: `profile` under 250 ms and `analyze deep` under 10 s on 1M×50
     (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2329-L2332).
   - Report: `profile` target 5 s; `deep` measured ~39 s with the target
     raised to 60 s (OLD:docs/benchmarks/v0.4.0-report.md:L63, L88-L92).
   - Notes and CHANGELOG still say "<10 s… met"
     (OLD:docs/notes/what-is-new-in-v0.4.md:L158, OLD:CHANGELOG.md:L91).
   - The spec's `large` (10M) and `wide` (500-column) corpora
     (DESIGN-SPEC L2316-L2317) are absent from the report (L21-L25).
   - "100GB Parquet… ~1GB peak memory"
     (OLD:docs/architecture/compiler.md:L362-L364) has no benchmark behind it.
8. **Docs drift:**
   - CLAUDE.md lists ADR-001 to 008 (OLD:CLAUDE.md:L151). The index lists
     001, 002, 003, 006 and 008 (OLD:docs/decisions/INDEX.md:L5-L11).
   - ADR-009 exists but is not indexed.
   - The spec cites a missing ADR-004
     (OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md:L2719).
   - *(Inference)* The missing ADRs 004, 005 and 007 were removed under the
     "public-safety" rules (OLD:CLAUDE.md:L68-L81).
   - Serialisation docs say "not implemented" after it shipped (see Learned
     state).
   - Python floor is 3.10 (OLD:pyproject.toml:L7).
9. **Process overhead:**
   - Four Opus "max thinking" subagents (OLD:CLAUDE.md:L204-L215).
   - An ADR (009) entirely about agent execution workflow
     (OLD:docs/decisions/ADR-009-execution-workflow.md:L42-L83).
   - "Never edit the spec mid-execution" (OLD:CLAUDE.md:L28), with a
     gitignored plan folder holding the spec
     (OLD:docs/decisions/ADR-009-execution-workflow.md:L146-L150).
   - This agrees with sqlearn-000-review's "process outweighed product".

**Agreements with sqlearn-000-review:** fit sees raw input; universal params
unimplemented; no cross-engine result tests; network-fetched datasets; the
scikit-learn naming departure had no evidence of users; process-heavy.
**Contradictions or new findings:**

- This repo *did* have a uniform passthrough rule (transformer-contract
  L75-L96), where sqlearn_000 had none.
- It *did* batch multi-column aggregates in one SELECT per layer; sqlearn_000
  ran one query per aggregate.
- It reached real consuming steps (Impute→Scale), so the ordering defect is
  *demonstrated*, not inferred.
- It had more than one connection mode (`sq.connect`), against its own ADR.

## Files covered

- [x] OLD:CLAUDE.md: agent rules. `learn`/`apply`/`sql` naming,
  sqlglot-as-IR, JSON state, single connection, comparison-first process,
  transformer contract, universal parameters.
- [x] OLD:README.md: pitch ("one SQL query", any dialect, "Not sklearn"),
  `as_sklearn`, `download-data` (network).
- [x] OLD:REVIEW.md: per-phase test tables for v0.3. Weak tolerances
  (correlation), many "N/A" comparisons.
- [x] OLD:TODO.md: v0.3 post-review: six bugs and five warnings. Lazy fit,
  sentinel, AST reuse, injection, silent no-op parameters. Partly fixed in
  src (TargetEncode, DropCorrelated) but never closed in docs.
- [x] OLD:CHANGELOG.md: v0.1 to v0.4, all "Unreleased". v0.4 "Fixed: None".
  Test counts 200 → 2934.
- [x] OLD:pyproject.toml: runtime `sqlglot<30`, `duckdb`, `numpy`; optional
  `scipy` and `statsmodels`; MIT; Python ≥3.10; `S608` ignored; pyright
  relaxations for sqlglot stubs.
- [x] OLD:docs/architecture/INDEX.md: map of six architecture docs.
- [x] OLD:docs/architecture/overview.md: compiler identity, IR = sqlglot AST
  plus learned constants, execute against export, backend protocol.
- [x] OLD:docs/architecture/compiler.md: expression composition, CTE
  promotion, layer system (the fit defect), three-tier classification, the
  "treat as dynamic" rule, dialect fallbacks, unbacked performance claims.
- [x] OLD:docs/architecture/transformer-contract.md: `discover`,
  `discover_sets`, `expressions`, `query`, `output_schema`; automatic
  passthrough; custom-transform levels; Pipeline as Transformer.
- [x] OLD:docs/architecture/column-routing.md: `_default_columns`,
  selectors, `Columns` with `remainder`.
- [x] OLD:docs/architecture/composition.md: column-only against row-op
  branches, `ROW_NUMBER` row id, four merge strategies.
- [x] OLD:docs/architecture/serialization.md: JSON invariant, `params_` and
  `sets_` shapes, `to_config` "not implemented" (stale).
- [x] OLD:docs/decisions/INDEX.md: lists ADRs 001, 002, 003, 006 and 008
  (gaps; 009 missing).
- [x] OLD:docs/decisions/ADR-001-sqlglot-ast.md: sqlglot IR. Admits the v30
  break and the pin.
- [x] OLD:docs/decisions/ADR-002-learn-apply-naming.md: departure from
  scikit-learn naming and conventions, adapter for interop.
- [x] OLD:docs/decisions/ADR-003-json-serialization.md: JSON-only learned
  state, no pickle.
- [x] OLD:docs/decisions/ADR-006-no-hosted-execution.md: data stays local
  (matches new ADR 0006).
- [x] OLD:docs/decisions/ADR-008-single-connection.md: module-level
  connection; internally inconsistent; later contradicted by `sq.connect`.
- [x] OLD:docs/decisions/ADR-009-execution-workflow.md: agent execution
  workflow, verification ledger, release summaries.
- [x] OLD:docs/notes/what-is-new-in-v0.4.md: release notes. Performance
  "met" claims contradict the benchmark report.
- [x] OLD:docs/benchmarks/v0.4.0-report.md: wall-clock bounds. Two relaxed
  (deep 39 s against 10 s). Large and wide corpora missing.
- [x] OLD:plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md (all 2,719
  lines): v0.4 EDA primitives, `explore` with CV and prefix cache, six
  transformers (CountEncode as a CASE literal map), sampling caveats,
  performance targets, testing tolerances, deferred list.
- Outside batch, for verification only:
  `src/sqlearn/compiler/layers.py:L176-L224`,
  `src/sqlearn/compiler/compile.py:L162-L237`,
  `src/sqlearn/transforms/encoders/target_encode.py:L70-L135`,
  `tests/transforms/scalers/test_scalers_deep.py:L102-L114`. Plus import
  counts: sqlglot in 79 src files, numpy in 6; about 21.7k lines of src.

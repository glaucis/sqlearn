---
type: architecture
tags: [fit-execution, learned-state, sql-compilation, duckdb, precision, federated]
summary: "Batch B review of sqlearn core module specs, finding the fit defect, layer rules, learned state, precision and concurrency gaps in the April 2026 planning repo."
related: [docs/questions/earlier-attempts/sqlearn-private-april/sqlearn-v04/notes/B-compiler.md, "OLD:S/compiler/layers.md", "OLD:S/compiler/compile.md", "OLD:S/compiler/compose.md", "OLD:S/compiler/classify.md", "OLD:S/_hardening/v0_8_hardening.md", "OLD:P/federated/federated_execution.md", "OLD:S/precision/precision.md"]
mdindex: [type=4ca303, tags=47b9f4, summary=9677b4, related=0d9771]
---
# Batch B: core specifications (April planning repo)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn-private`
(GitHub `glaucis/sqlearn-private`, 9–24 April 2026). Citations abbreviate `S/` =
`_old/projects/sqlearn/src/` and `P/` = `_old/projects/sqlearn-pro/src/`. Read
only; nothing in OLD was run. "Inference" marks a conclusion drawn from the
text, not stated in it. Every file in the batch was read in full; none hung. The
DuckDB checks below were run on DuckDB 2.0.0 in a scratch directory, outside
OLD.

These are per-module specifications written alongside v0.4 (the
`sqlearn-ecosystem_old/sqlearn` code reviewed in
[`../../sqlearn-v04/`](../../sqlearn-v04/)). Most carry `status: shipped`
for what v0.4 had and `status: planned` with a target release (v0.5 to v1.0)
for the rest.

## Summary

- **The fit defect is specified, not fixed.** The layer rule is still "cut
  only after a dynamic, schema-changing step"
  (`OLD:S/compiler/layers.md:L32-L52`), and the worked examples batch
  `Impute` and `Scale` into one aggregate query over the same input
  (`OLD:S/compiler/layers.md:L69-L77`,
  `OLD:S/compiler/classify.md:L422-L425`). The multi-CTE fit template reads
  every statistic `FROM data` (`OLD:S/compiler/compile.md:L150-L167`).
- **Static-to-dynamic substitution is specified, and v0.4 never built it.**
  `AVG(price)` after a static `LN(price + 1)` becomes `AVG(LN(price + 1))`
  (`OLD:S/compiler/compose.md:L46-L65`). Only static steps are substituted;
  nothing says how a dynamic step's output reaches a later dynamic step in
  the same layer.
- **Row steps during fit, set queries and `where=` are unspecified or
  self-contradictory.** `Filter` sits inside fit layer 0 with no statement that
  fit applies it (`OLD:S/compiler/classify.md:L422-L425`,
  `OLD:S/compiler/compose.md:L94-L96`). Sets are still one `SELECT DISTINCT`
  per column, optionally `UNION ALL`ed (`OLD:S/compiler/compile.md:L275-L301`).
- **The query-count promises contradict each other**: "2 queries regardless
  of how many steps" (`OLD:S/compiler/compile.md:L137-L141`) against
  "2k + 1" (`OLD:S/compiler/layers.md:L84-L89`).
- **Learned state** is Python dicts `params_`/`sets_` inlined as literals,
  saved as JSON, and keyed by `{step}__{column}__{stat}` strings
  (`OLD:S/compiler/compile.md:L169-L172`, `OLD:S/core/pipeline.md:L451-L475`).
  New: a frozen pipeline that stores the compiled SQL text with two SHA-256
  fingerprints (`OLD:S/core/frozen_pipeline.md:L83-L92`, `L267-L329`).
- **Precision mode is unsound on DuckDB.** `precision="decimal38"` promises
  bit-exact `Scale`, `Impute` and division
  (`OLD:S/precision/precision.md:L30-L33`).
  On DuckDB 2.0.0, `AVG` and `STDDEV_POP` of a DECIMAL return DOUBLE,
  DECIMAL ÷ DECIMAL returns DOUBLE, and `DECIMAL(38,18) × DECIMAL(38,18)`
  is `DECIMAL(38,36)`, which overflows at 200 × 3. Float mode has no literal
  rule at all.
- **Concurrency**: cross-thread use of a Pipeline raises, `clone()` is the
  fix, and every connection has a re-entrant lock
  (`OLD:S/concurrency/concurrency.md:L37-L65`, `L197-L238`).
- **Errors and warnings**: one `SqlearnError` root with message, context and
  hint, dual-inherited from built-ins (`OLD:S/errors/errors.md:L44-L77`,
  `L259-L306`). There are fourteen fit-time checkers plus seven `group_by`
  rules and three info rules. The specs disagree on whether warnings go
  through `warnings.warn` or only through the logger
  (`OLD:S/warnings/group_by_rules.md:L26-L37` against
  `OLD:S/logging/logging.md:L202-L211`).
- **The hardening list (v0.8) closes 20-odd defects, but never the fit
  defect.** Its `group_by` design computes the statistics from the data being
  transformed with `AVG(...) OVER (PARTITION BY ...)`
  (`OLD:S/_hardening/v0_8_hardening.md:L271-L298`).
- **Federated (pro) design** keeps the fit defect (all discover queries run
  in parallel before any apply) and makes statistics per source by default
  (`OLD:P/federated/federated_execution.md:L143-L192`, `L485-L506`). Its
  algebraic-decomposition table (Welford merge) is worth keeping.

## Fit execution as specified

**The flow.** `compile.md` defines inspection, then fit planning, then
transform planning (`OLD:S/compiler/compile.md:L27-L81`). It also gives an
"11-step fit execution flow": resolve input, one `DESCRIBE`, resolve
columns, classify, cut layers, collect `discover()`, collect
`discover_sets()`, batch, execute, track the schema
(`OLD:S/compiler/compile.md:L106-L135`). The schema is read once and every
later schema is computed by walking `output_schema()`
(`OLD:S/compiler/compile.md:L231-L273`).

**Does a learning step learn from an earlier learning step's output? No.**
- The layer boundary rule: cut after a step "if and only if" it is dynamic
  *and* schema-changing (`OLD:S/compiler/layers.md:L32-L52`). "Dynamic
  non-schema-changing steps do NOT create a boundary. `Impute`, `Scale`,
  `MinMaxScale` — … Their contributions merge into the layer's single
  batched query" (`L45-L48`).
- Worked example: Layer 0 `[Impute, Scale, OneHot]` gives "1 batched aggregate
  query (Impute + Scale means/stds merged)"
  (`OLD:S/compiler/layers.md:L56-L77`). The summary view repeats it: "Fit:
  1 query (12 aggregates from Impute + Scale)"
  (`OLD:S/compiler/classify.md:L422-L425`).
- The multi-CTE template computes `MEDIAN(price)` and `AVG(price)`,
  `STDDEV_POP(price)` each `FROM data`
  (`OLD:S/compiler/compile.md:L150-L167`). The fit-warning query has the same
  shape (`OLD:S/warnings/fit_warnings.md:L548-L566`).
- The contract hands `discover()` column names and a schema, never upstream
  expressions (`OLD:S/core/transformer.md:L46-L52`, `L492-L505`).
- Inference: an imputer's fill value is not known until its aggregate has
  run, so it cannot be substituted into the same `SELECT`. The specs never
  notice this. `compose.md` says that within a layer "every step's
  aggregates reference the composed input"
  (`OLD:S/compiler/compose.md:L158-L160`), which can only hold for static
  upstream steps.
- The ordering warning O2 tells users to put `Impute` before `Scale` because
  "scaling learns mean/std on data that still has NULLs"
  (`OLD:S/warnings/fit_warnings.md:L176`). The recommended order is exactly
  the one the layer rule fits wrongly (inference).
- The audit example shows `Impute(mean=44.2) → Scale(std=12.3)`, final
  `(COALESCE(price, 44.2) - 44.2) / 12.3` (`OLD:S/core/audit.md:L59-L67`).
  The two means agree, as they would for mean imputation either way; the std
  cannot be checked from the text.

**Static to dynamic: specified.** `compose.md` substitutes column references
in a later dynamic step's aggregate with the running expression of an
earlier static step: `AVG(price)` becomes `AVG(LN(price + 1))`, in one
batched pass (`OLD:S/compiler/compose.md:L46-L65`, interface
`collect_aggregations(layer, current_exprs)` at `L120-L122`). Static
schema-changing steps therefore do not cut a layer
(`OLD:S/compiler/layers.md:L156-L173`). This is the `Tomosius/sqlearn`
behaviour the baseline says v0.4 lost; the v0.4 notes confirm that `discover()`
gets column names only (`../../sqlearn-v04/notes/B-compiler.md`, Summary).

**Set queries.** Each `discover_sets()` entry is its own
`SELECT DISTINCT`; above three columns they MAY be batched with `UNION ALL`
into `(__sq_col__, __sq_val__)` pairs and pivoted in Python
(`OLD:S/compiler/compile.md:L275-L301`). All aggregates run first, then all
sets (`L298-L301`). Sets follow the same layer rule, so a set after an
earlier dynamic step in the same layer reads un-transformed values
(inference). The hardening list widens sets for TargetEncode to
`SELECT category, AVG(target) … GROUP BY category`
(`OLD:S/_hardening/v0_8_hardening.md:L44-L52`), which v0.4's set executor
could not run (it ignores the returned expression).

**Row steps during fit.** Not specified.
- A `query()` step makes a transform-time subquery "even if it doesn't
  trigger a fit-time layer boundary"
  (`OLD:S/compiler/compose.md:L81-L96`). The summary puts `Filter` in fit
  layer 0 with `Impute` and `Scale` (`OLD:S/compiler/classify.md:L396-L431`).
  No spec says the fit aggregates see the filter.
- `where=` has two meanings. In `transformer.md` it is
  `CASE WHEN <condition> THEN <expr> ELSE col END` at apply time
  (`OLD:S/core/transformer.md:L110-L119`). In `design-rationale.md`, for bulk
  transformers it scopes "stat computation (fit-time scope), not … apply-time
  row selection", and for selective ones it scopes apply only
  (`OLD:S/design-rationale.md:L353-L368`,
  `OLD:S/core/transformer.md:L205-L241`).
- "Theme D" makes dropping rows with NULL in transformed columns the default
  at apply time, with `last_rows_dropped_`, `return_mask=True` and
  `unprocessed_nulls()` to report it (`OLD:S/core/pipeline.md:L124-L214`,
  `OLD:S/warnings/group_by_rules.md:L921-L1016`). The specs do not say whether
  fit drops the same rows (inference: they do not).

**Grouped statistics leak into transform.** The v0.8 `group_by` design emits
`(price - AVG(price) OVER (PARTITION BY region)) / STDDEV_POP(price) OVER
(PARTITION BY region)` at apply time, then says the fitted state is a
per-group dict and apply "uses the per-group window to look up" it
(`OLD:S/_hardening/v0_8_hardening.md:L271-L298`). As written, transform
recomputes the statistics from the data it is transforming. The federated
spec repeats the window form
(`OLD:P/federated/federated_execution.md:L593-L597`).

**Cross-fitting.** `Pipeline(..., cv=K)` cross-fits every learned statistic.
Each fold's features come from statistics learned on the other folds; apply on
new data uses full-training statistics
(`OLD:S/warnings/hyperfitting.md:L241-L266`,
`OLD:S/warnings/group_by_rules.md:L102-L119`). This means the training
output of `learn` differs from `apply(train)`, a fit-transform distinction
the specs never name (inference). No SQL is given for it.

**Query counts.** "1–3 SQL queries per `learn()` regardless of pipeline
length" (`OLD:S/compiler/INDEX.md:L13-L17`). "Total SQL queries for the entire
pipeline: 2 … regardless of how many steps"
(`OLD:S/compiler/compile.md:L137-L141`), against "k dynamic schema-changing
steps → 2k + 1" (`OLD:S/compiler/layers.md:L84-L89`). The pipeline doc says
learn runs "in a single pass" (`OLD:S/core/pipeline.md:L29-L32`).

**Classification.** Three tiers: built-ins trusted, declared custom steps
verified once, undeclared ones probed with "if in doubt, dynamic"
(`OLD:S/compiler/classify.md:L14-L104`). Classification depends on
constructor arguments (`Clip(lower="p01")` is dynamic;
`L106-L150`). S1–S5/D1–D5 and SC1–SC4 criteria (`L152-L301`). A
`_FrozenEmptyParams` sentinel raises when a static step reads `params_`
(`L190-L240`). Tier 1 is chosen by module path (`L54-L55`).

## Learned state and saving

- **Where it lives.** On each step: `params_` (scalars) and `sets_` (lists),
  filled from the fit result (`OLD:S/compiler/compile.md:L131-L135`,
  `OLD:S/core/transformer.md:L32-L42`). The intermediate representation is
  "sqlglot AST nodes … and Python-constant parameter dicts"
  (`OLD:S/compiler/compile.md:L401-L405`). Literals are inlined at compile
  time: `(price - 44.2) / 12.3` (`OLD:S/_hardening/v0_8_hardening.md:L274-L276`,
  `OLD:P/federated/federated_execution.md:L199-L202`).
- **Keys.** Fit result columns are named `{step_name}__{column}__{stat}`
  "without ambiguity" (`OLD:S/compiler/compile.md:L169-L172`); the
  convention check K4 only warns (`L193`). This is still a string split on
  `__`, the v0.4 failure. Federated adds `"pg:price__mean"` and
  `"price__global_mean"` (`OLD:P/federated/federated_execution.md:L177-L186`).
- **Grouped state.** "A per-group dict instead of a single value"
  (`OLD:S/_hardening/v0_8_hardening.md:L296-L298`); no serialised shape is
  given.
- **"Not fitted" and "learned NULL".** Not addressed. Empty-data fit raises
  `DataError` instead of storing NULL parameters
  (`OLD:S/_hardening/v0_8_hardening.md:L486-L503`). `Impute` must learn fill
  values for every column, not only those with NULLs (`L466-L484`).
- **Saving.** JSON by invariant: "no pickle, no numpy arrays, no sqlglot ASTs
  in the stored state"; the SQL from `sql()` is "the primary deployment
  artifact" (`OLD:S/core/pipeline.md:L451-L475`). The concurrency spec
  contradicts this by suggesting "pickle/unpickle" across processes
  (`OLD:S/concurrency/concurrency.md:L107-L113`). `clone()` is a
  `to_config()`/`from_config()` round trip
  (`OLD:S/concurrency/concurrency.md:L159-L195`).
- **Frozen pipeline (v1.0).** `freeze()` stores the training and output
  schemas, the target, `sql_` (the compiled text), `params_fingerprint_` and
  `sql_fingerprint_` (SHA-256), the sqlearn and Python versions, and a
  `format_version_` (`OLD:S/core/frozen_pipeline.md:L67-L121`). `from_config`
  refuses on a fingerprint mismatch; `verify=True` recompiles and compares
  (`L233-L329`). Strict apply rejects any schema change; "tight" also checks
  numeric ranges (`L123-L143`). It notes that `HASH()` may differ across
  DuckDB major versions (`L189-L197`).
- **Decimal state.** In precision mode, statistics are stored as canonical
  decimal strings with a `_dtype` annotation
  (`OLD:S/precision/precision.md:L206-L245`).
- **Selectors save as kind and argument** (`OLD:S/selectors.md:L182-L201`).
  The v0.4 notes found that `to_config` could not save them; the spec
  asserts it can, without a format.
- **Where a stat can depend on a connection.** "A Pipeline holds learned state
  … that may be tied to a specific connection's temp views"
  (`OLD:S/concurrency/concurrency.md:L152-L154`): the v0.4 TargetEncode
  channel is acknowledged, not removed.

## SQL representation

- **sqlglot throughout.** Every `discover()`, `expressions()` and `query()`
  returns sqlglot nodes; "no string templating, no f-string SQL … anywhere"
  (`OLD:S/compiler/compile.md:L401-L418`). The reason given is multi-database
  support as "a core requirement, not a future nice-to-have" (`L373-L398`).
  The pin is `>=25.0,<30`, because v30 "broke pyright with 292 errors"
  (`L429-L432`). Known aggregates are listed as sqlglot classes for check V2
  (`L202-L229`).
- **Transform shape.** Expression steps flatten into one `SELECT`;
  `query()` steps add a subquery or CTE (`OLD:S/compiler/compose.md:L27-L96`).
  CTE promotion by depth with `cte_depth=8`
  (`OLD:S/compiler/compile.md:L335-L348`).
  The pipeline doc says both "a single flat `SELECT`. There is no
  nested-subquery overhead" (`OLD:S/core/pipeline.md:L20-L23`) and "WITH
  `__base__` AS (… `ROW_NUMBER() OVER ()` …)" with "every subsequent CTE"
  (`L98-L122`).
- **Row identity.** `__sqlearn_rid__` from `ROW_NUMBER() OVER ()`, plus
  `__sq_rownum__` for window ordering and `__sq_fold__` for folds; the
  `__sq_*__` prefix is reserved and checked on every `DESCRIBE`
  (`OLD:S/core/transformer.md:L431-L471`). The rid stays unordered, the
  non-determinism the v0.4 notes flagged.
- **Hardening of the AST layer.** `.copy()` on reused nodes (A6, G1),
  quoted identifiers (G2), sanitised OneHot column names (G4), dtype
  inference for `Expression` (G5), and hyphenated names parsed as dates (G6)
  (`OLD:S/_hardening/v0_8_hardening.md:L149-L181`, `L558-L692`). These are
  sqlglot costs, adding to the baseline's list.
- **Universal parameters** are wrapped by the compiler: `where=` as
  `CASE WHEN`, `dtype=` as `CAST`, `group_by=` as `PARTITION BY`
  (`OLD:S/core/transformer.md:L104-L133`).
- **Hierarchy of categories.** `StatTransformer` (Bulk, Selective),
  `ElementwiseTransformer`, `WindowTransformer`, `RowOperation` and
  `Composition` carry the rules for universal parameters
  (`OLD:S/core/transformer.md:L184-L429`). `Pipeline`, `Columns` and `Union`
  are under `Composition`.
- **Federated** compiles per-source SQL by dialect and summons an ephemeral
  DuckDB only for merges; DuckDB is a "soft dependency"
  (`OLD:P/federated/federated_execution.md:L82-L141`, `L402-L421`).

## Precision

- **Float mode (the default) has no rule.** Statistics are JSON floats
  (`{"mean": 44.2, "std": 12.3}`) and inline as literals
  (`OLD:S/precision/precision.md:L213-L216`). Nothing says how a float
  becomes a literal. On DuckDB 2.0.0, `44.2` parses as `DECIMAL(3,1)`,
  `44.200000000000000000` as `DECIMAL(20,18)`, and `1e-20` as DOUBLE. A
  shortest-repr float written as a decimal literal converts back to the same
  double (checked for `0.30000000000000004`), but the literal's type changes
  with its digits (checked; inference that this matters only when the other
  operand is DECIMAL).
- **Decimal mode (v0.8).** `Pipeline(precision="decimal38",
  precision_scale=18)` casts numeric columns to `DECIMAL(38, S)`; a
  per-transform `dtype=` wins (`OLD:S/precision/precision.md:L82-L200`).
  Columns whose values exceed the integer part fall back to DOUBLE with a
  warning (`L117-L136`, `L391-L413`). Output adapters say whether they keep
  decimals: numpy no, Arrow, Polars and DuckDB yes (`L247-L263`).
- **The claim does not hold on DuckDB.** Goal 1 lists Scale, MinMaxScale,
  MaxAbsScale, Impute and Add/Sub/Mul/Div as bit-exact against
  `decimal.Decimal(prec=50)` (`OLD:S/precision/precision.md:L30-L33`), while
  the index concedes variance with a square root stays float
  (`OLD:S/precision/INDEX.md:L35-L39`).
  Checked on DuckDB 2.0.0: `AVG` and `STDDEV_POP` of `DECIMAL(38,18)` return
  DOUBLE; `SUM`, `MIN`, `MAX` and `MEDIAN` stay `DECIMAL(38,18)`;
  `DECIMAL(38,18) / DECIMAL(38,18)` is DOUBLE; `DECIMAL(38,18) - 44.2…` stays
  `DECIMAL(38,18)`; `DECIMAL(38,18) × DECIMAL(38,18)` is `DECIMAL(38,36)`,
  and `200 × 3` raises "Overflow in multiplication of DECIMAL(38)". So the
  mean, the std and every division are DOUBLE, and multiplication overflows
  at small values.
- **Ground truth.** The v0.2 `tests/PRECISION.md` framework uses
  `decimal.Decimal(prec=50)` and documents a "~2.7e-15 difference" on 20K
  banking rows (`OLD:S/precision/precision.md:L70-L80`): an exact reference,
  as the baseline's validation method wants.
- **Integer overflow.** A9 casts integer operands to DOUBLE before
  multiplying (`OLD:S/_hardening/v0_8_hardening.md:L505-L525`).

## Connections and concurrency

- **Pipeline objects** are owned by the thread and process that first use
  them; any other thread or process raises `ConcurrencyError` with a
  `clone()` hint (`OLD:S/concurrency/concurrency.md:L67-L157`). "Locking gives
  false confidence" is quoted from the older project's rationale (`L37-L65`).
- **Connections.** A named registry of `ConnectionEntry` objects, each with a
  `threading.RLock` around every `execute()` (`L197-L238`). Re-entrant
  because `explore()` calls `learn()`, which calls `discover()` (`L229-L233`,
  `L546-L569`). The registry and its cascade (`source=`, `database=`) live in
  `helpers/connection_management.md`, outside this batch
  (`OLD:S/core/pipeline.md:L361-L374`).
- **Parallelism** is one connection per thread
  (`OLD:S/concurrency/concurrency.md:L276-L304`, `L364-L403`). A BYO
  connection used directly from another thread is the user's problem;
  `sq.connect(name, _lock=True)` exposes the lock (`L240-L274`). No pool
  (`L428-L448`). No async API; `asyncio.to_thread` is the pattern
  (`L332-L362`).
- **Processes.** The DuckDB file lock is surfaced as `ConnectionConfigError`;
  one writer and many `read_only=True` readers is supported (`L306-L330`).
- **Not mentioned.** DuckDB's own per-thread mechanism,
  `DuckDBPyConnection.cursor()`, which shares one database across threads
  (inference from DuckDB's Python API, not rechecked here).
- **v0.4 lessons absorbed in part.** The process-global connection, fixed
  temp view names and views never dropped (v0.4 defect 12) are not addressed
  in this batch: there is no rule for naming or dropping fit-time views.

## Errors, warnings, logging

**Errors (v0.5).** One module, one root `SqlearnError(message, *, context,
hint)` formatting `summary / Context: / Hint:`
(`OLD:S/errors/errors.md:L82-L119`, `L218-L257`). There are eight families
with about 25 classes (`L43-L77`). Dual inheritance keeps
`except ValueError` working (`L259-L306`). `raise … from` is mandatory
(`L308-L335`). DuckDB errors are wrapped in `BackendError` and sqlglot errors
in `CompilationError` (`L360-L372`, `L604-L630`). `NotImplementedError` is
left alone (`L585-L602`). Points to note:
- `BackendError` is under sqlearn's `ConnectionError`, which also inherits
  Python's `ConnectionError` (an `OSError`), so a DuckDB type error is caught
  as an `OSError` (`L69-L72`, `L448-L451`; inference).
- `UnseenCategoryError` is the default for OneHot and Ordinal at apply
  (`L145`). The hardening audit G7 notes that the SQL falls through to
  `ELSE NULL` and proposes changing the default instead
  (`OLD:S/_hardening/v0_8_hardening.md:L694-L719`). Raising from SQL needs
  DuckDB's `error()` or a query after apply (inference).
- `FrozenPipelineError`, `SchemaDriftError` and `ConcurrencyError` are added
  later (`OLD:S/core/frozen_pipeline.md:L333-L341`,
  `OLD:S/concurrency/concurrency.md:L489-L493`).

**Logging (v0.6).** Standard `logging` under `sqlearn.*` with a private
`_logging.get_logger` helper; level WARNING by default; every record has an
`extra` dict; "no telemetry … never" (`OLD:S/logging/logging.md:L26-L65`,
`L90-L107`, `L479-L496`). `print()` is banned outside display helpers, and
`warnings.warn` is reserved for deprecations (`L190-L211`). There is a
contradiction: logging emits ERROR records before raising (`L177-L183`), while
errors are "raised, not logged" (`OLD:S/errors/errors.md:L640-L643`).

**Fit-time warnings (v0.6).**
- Fourteen checkers: identifier columns, high cardinality to OneHot,
  constant, mostly NULL, dates stored as VARCHAR, target leakage by
  correlation, six ordering rules, reserved and unusual names, PII and secret
  names, unused datetime and text columns, redundant scaling, all-NULL,
  near-zero variance and binary re-encoding
  (`OLD:S/warnings/fit_warnings.md:L42-L376`).
- Results go to `pipe.warnings_`, `show_warnings()`, `suppress_warning(s)`,
  `set_warning_threshold` and the `sqlearn.fit.warnings` logger (`L378-L469`).
- The checks are meant to ride in the fit query
  (`APPROX_COUNT_DISTINCT`, null ratios, `CORR` with the target;
  `L541-L572`). They are computed on the raw input columns (inference).
- The `learn()` sketch mutates and returns `self` (`L576-L617`), against the
  immutability rule (`OLD:S/core/pipeline.md:L41-L51`).

**`group_by` rules.** A single rules file is meant to drive both runtime
messages and the public docs page (`OLD:S/warnings/group_by_rules.md:L16-L54`).
It has seven warning rules with thresholds, SQL, templates and mitigations:
small group under 30, top group over 80%, `|corr| > 0.3` with the target,
missing values concentrated, variance cut by more than 80%, groups over
√n, and effective parameters over 10% of rows. There are also three info
rules (`L263-L1110`). Defects:
- The rule 6 SQL puts an aggregate in `WHERE` and uses
  `COUNT(DISTINCT a, b)` (`L632-L637`).
- Rule 3 takes `CORR` of a categorical grouping column (`L405-L413`).
- Rule names in the interaction note do not match the rule names
  (`L913-L919`).
- Warning classes sit in `sqlearn.errors` (`L65`, `L270`) and also in
  `sqlearn.warnings` (`L833`).
- Every rule runs its own detection query (`L28-L32`), which is not the
  "zero extra round-trips" of `fit_warnings.md` (`L32-L34`).

**Hyperfitting** names preprocessing that overfits through `where=` and
`group_by=`, counts "effective parameters", and offers `cv=K` as the fix
(`OLD:S/warnings/hyperfitting.md:L35-L139`, `L241-L266`). Its claim that
cross-validation "does not catch it" holds only when preprocessing is fitted
outside the CV loop (`L111-L116`; inference). The first-use message is
recorded in `~/.sqlearn/state.json` (`L284-L294`).

**Model compatibility.** `target_model=` against a knowledge base of about
20 model families: missing scaler, missing imputation, missing encoding, or
unnecessary preprocessing (`OLD:S/warnings/model_compatibility.md:L54-L213`).
The table says random forests do not handle NaN (`L134`); scikit-learn
added missing-value support to its random forests in 1.4 (inference from
scikit-learn's changelog, not rechecked here).

**Design rationale.** Five principles: allow, warn loudly, the user decides,
docs are the contract, convenience is earned
(`OLD:S/design-rationale.md:L39-L83`). There is one `option=` switch, strict by
default, cascading through session, pipeline and step (`L85-L109`). Strict
`Log` on zeros raises, and permissive mode gives a signed log (`L111-L196`).
"Never produce a column with mixed semantics" is enforced even when
`option=True` (`L278-L368`). The compiled SQL in worked example 5 keeps a
`CASE WHEN` for conditions its `WHERE` already guarantees
(`L603-L630`), and the text claims the compiler pushes it down.

## Against v0.4 as built

Compared with
[`../../sqlearn-v04/notes/B-compiler.md`](../../sqlearn-v04/notes/B-compiler.md).

**Specified correctly where v0.4 was wrong, but never implemented in v0.4:**
- Static-to-dynamic substitution in fit aggregates
  (`OLD:S/compiler/compose.md:L46-L65`); v0.4 passes column names only.
- One `DESCRIBE` per fit (`OLD:S/compiler/compile.md:L231-L273`); v0.4
  described twice and registered DataFrames twice.
- `Columns` fans `discover`/`expressions`/`output_schema` out to its branches
  (`OLD:S/core/columns.md:L64-L79`); v0.4's `Columns` raised and never
  routed parameters.
- Validating `discover()` returns, K1–K4 and V1–V2
  (`OLD:S/compiler/compile.md:L179-L229`).
- Schema validation on every apply (A10,
  `OLD:S/_hardening/v0_8_hardening.md:L527-L547`); v0.4 had it opt-in.
- TargetEncode per-category means through `discover_sets` instead of a
  hidden query in `expressions()` (A1, `L34-L57`). PowerScale's lambda is
  stored at learn time (A4, `L98-L112`). These are two of v0.4's
  "fitting escapes into transform" cases.
- `group_by`/`order_by` actually consumed (C1, `L250-L312`), though see the
  window leak above.
- `get_params` by an MRO walk, with `set_params` and `clone`
  (`OLD:S/core/transformer.md:L135-L182`); v0.4 had none and stored
  parameters under `_name`.
- The error hierarchy, the logger and the warnings are all planned; v0.4 had
  only `SchemaValidationError`.

**Specified as v0.4 had it (the defects carried forward):**
- The layer rule and same-layer batching of dynamic steps
  (`OLD:S/compiler/layers.md:L32-L77`): v0.4 defect 1.
- No statement that fit applies `Filter`, `where=` or `drop_null=`: v0.4
  defect 2, unaddressed.
- Sets as per-column DISTINCT keyed by parameter name: v0.4 defect 5, now
  explicit (`OLD:S/compiler/compile.md:L275-L301`). Whether NULL is a
  category is not stated.
- `__`-joined keys: v0.4 defect 6 (`OLD:S/compiler/compile.md:L169-L172`).
- `ROW_NUMBER() OVER ()` row identity (`OLD:S/core/transformer.md:L443`).
- `learn/apply/sql` names with an `as_sklearn()` adapter
  (`OLD:S/core/pipeline.md:L393-L423`), against ADR 0003.
- Target taken as a column name (`learn(data, target=)`), not excluded from
  default selectors. Only the leakage checker skips it
  (`OLD:S/warnings/fit_warnings.md:L606-L610`).
- numpy as the default output (`OLD:S/core/pipeline.md:L216-L223`), so
  numpy stays a dependency.

**Not in the specs at all:** v0.4 defects 3 (steps applied twice from layer
3 on), 4 (lost static schema changes in a layer), 10 (types faked as VARCHAR),
12 (global connection, fixed view names) and 16 (docstrings contradicting
code). The specs reproduce defect 16 among themselves: "single pass", "flat
SELECT", CTEs and "2 queries" all appear, against "2k + 1".

## New against the baseline

- **Static-to-dynamic substitution as a written rule**, with conservative
  classification and verification of custom declarations
  (`OLD:S/compiler/compose.md:L46-L65`, `OLD:S/compiler/classify.md:L14-L104`).
- **Classification by constructor arguments** (`Clip(lower="p01")` is
  dynamic) and the `_FrozenEmptyParams` sentinel
  (`OLD:S/compiler/classify.md:L106-L240`).
- **A frozen deployment artefact**: compiled SQL text plus parameter and
  SQL fingerprints, format and version fields, and strict or range-checked
  apply (`OLD:S/core/frozen_pipeline.md:L67-L329`).
- **Cross-fitting with `cv=K`** at the pipeline level, which makes the
  training output differ from `apply(train)`
  (`OLD:S/warnings/hyperfitting.md:L241-L266`).
- **Reporting row drops**: `last_rows_dropped_`, `last_dropped_reason_`,
  `return_mask=True` and `unprocessed_nulls()`
  (`OLD:S/core/pipeline.md:L124-L214`). Dropping NULL rows by default is a
  departure from scikit-learn, whose scalers pass NaN through (inference).
- **DECIMAL mode** and its measured cost table, with the DuckDB faults above
  (`OLD:S/precision/precision.md:L415-L435`).
- **Thread ownership and per-connection RLock**
  (`OLD:S/concurrency/concurrency.md:L67-L238`).
- **Structured errors with context and hint**, and structured logs with the
  same dict (`OLD:S/errors/errors.md:L82-L119`,
  `OLD:S/logging/logging.md:L109-L135`).
- **Fit-time advisory warnings** riding on the fit query, and the
  `group_by` rules file shared by runtime and docs
  (`OLD:S/warnings/fit_warnings.md:L541-L572`,
  `OLD:S/warnings/group_by_rules.md:L16-L54`).
- **The "no mixed semantics" rule for `where=`**
  (`OLD:S/design-rationale.md:L347-L368`).
- **Federated execution**: per-source push-down, an ordered strategy list,
  a main budget, and algebraic partials (COUNT, SUM, AVG as sum and count,
  variance as Welford triples) merged on main
  (`OLD:P/federated/federated_execution.md:L250-L336`). Statistics are per
  source by default (`source_local`), with `global=True` to pool them
  (`L485-L528`). This bears on the multi-engine question: it is the only
  design in any attempt so far that plans for engines beyond DuckDB, and it
  routes through sqlglot dialects.
- **Security**: `memory_limit` interpolated into SQL unchecked (A5,
  `OLD:S/_hardening/v0_8_hardening.md:L114-L147`), the same class as v0.4's
  unescaped paths.

## Contradicts the baseline

- The baseline reads v0.4's layers as an accident of the code. Here the rule
  is the written contract, with worked examples that batch `Impute` and
  `Scale` (`OLD:S/compiler/layers.md:L54-L80`). The defect was designed again
  in April, beside a warning (O2) that recommends the very order it gets
  wrong.
- The baseline says the one-query-fit idea used `WITH` clauses and was on
  file since March. Here the `WITH` form appears only as parallel CTEs over
  the same raw input (`OLD:S/compiler/compile.md:L150-L167`), not as staged
  CTEs where each stage reads the previous one.
- The baseline lists "nothing in transform may query data" as a requirement.
  The v0.8 `group_by` design and the federated spec compute grouped statistics
  inside the transform query with window aggregates
  (`OLD:S/_hardening/v0_8_hardening.md:L278-L281`,
  `OLD:P/federated/federated_execution.md:L593-L597`).
- The baseline reads "multi-database from day one" as never tested. Here it
  grows into a full federated plan; still nothing tests it, and its default
  `source_local` mode would give different answers from a single-source run
  of the same pipeline (inference).

## Confirms the baseline

- A later learning step learns from the layer or raw input, not from an
  earlier learning step's output (`OLD:S/compiler/layers.md:L45-L48`).
- Learned state is Python values inlined as literals and saved as JSON, with
  no float-literal rule (`OLD:S/precision/precision.md:L213-L216`).
- Keys are joined with `__` (`OLD:S/compiler/compile.md:L169-L172`).
- sqlglot is chosen for multi-database support, at the cost of version pins
  and type-checker noise (`OLD:S/compiler/compile.md:L373-L435`) and AST
  aliasing (`OLD:S/_hardening/v0_8_hardening.md:L149-L181`).
- The API is renamed away from scikit-learn, with bridges back (`as_sklearn`,
  `get_params`/`clone`; `OLD:S/core/pipeline.md:L393-L423`,
  `OLD:S/core/transformer.md:L135-L182`).
- The target is a column name, and fit takes a data source
  (`OLD:S/core/pipeline.md:L84-L96`, `L318`).
- Process: release "pillars" v0.5 to v1.0, agent-oriented checklists
  (`sqlearn-hardener`), and status kept by hand in several indexes. The
  indexes are stale already: "8 checker categories" against 14
  (`OLD:S/warnings/INDEX.md:L20`), and "seven" rules against seven plus
  three. Specs contradict each other on query counts, CTEs, `where=` and the
  warning channel.
- Exact references are planned (`decimal.Decimal(prec=50)`,
  `OLD:S/precision/precision.md:L70-L80`), but no spec compares a whole
  pipeline with scikit-learn's.

## Worth keeping

- **Substituting upstream expressions into later aggregates**, extended from
  static steps to every row-level prefix whose learned values are already
  known. Combined with staged CTEs, this answers the fit question
  (`OLD:S/compiler/compose.md:L46-L65`).
- **One `DESCRIBE`, then schema by `output_schema()`**
  (`OLD:S/compiler/compile.md:L231-L273`).
- **"If in doubt, dynamic", verifying custom declarations, classification by
  constructor arguments, and a sentinel for static steps reading state**
  (`OLD:S/compiler/classify.md`).
- **Checking `discover()` returns at compile time** (K1–K4, V1–V2,
  `OLD:S/compiler/compile.md:L179-L229`).
- **A frozen artefact with the SQL text and fingerprints**, and a load
  decision table keyed on format and major version
  (`OLD:S/core/frozen_pipeline.md:L163-L265`).
- **Exact references** with `decimal.Decimal(prec=50)`; drop DECIMAL mode
  as specified unless the DuckDB typing above is designed around.
- **Algebraic partials and Welford merges**: the same arithmetic gives
  per-fold, per-partition or per-file statistics in one scan
  (`OLD:P/federated/federated_execution.md:L283-L298`).
- **The error base class** (message, context, hint, `raise … from`), one
  root, and `NotImplementedError` left alone (`OLD:S/errors/errors.md`).
  Reconsider putting `BackendError` under `ConnectionError`.
- **The standard `logging` hierarchy**, quiet by default, structured
  `extra`, and no telemetry (`OLD:S/logging/logging.md`), which fits ADR 0006.
- **Fit-time checks folded into the fit query**, with one channel chosen,
  not three (`OLD:S/warnings/fit_warnings.md:L541-L572`).
- **Thread ownership with `clone()`**, and a lock per connection
  (`OLD:S/concurrency/concurrency.md`).
- **Reserved internal column prefix**, checked on every schema read
  (`OLD:S/core/transformer.md:L431-L471`).
- **"No column with mixed semantics"** as the test for `where=`
  (`OLD:S/design-rationale.md:L347-L368`).
- **Learn fill values for every column, and refuse an empty fit**
  (`OLD:S/_hardening/v0_8_hardening.md:L466-L503`).

## Files covered

- [x] `S/INDEX.md`: map of the per-module spec tree; `backend/` and
  `cte.py` undocumented.
- [x] `S/design-rationale.md`: five principles, the `option=` switch, five
  worked examples (Log domain, `group_by` leakage, `where=` semantics,
  hyperfitting, splitting predicates).
- [x] `S/selectors.md`: five lazy selectors resolved at learn time; why
  factories, why lazy.
- [x] `S/core/INDEX.md`: lists Pipeline, Transformer, Columns, LazyResult,
  FrozenPipeline and audit.
- [x] `S/core/transformer.md`: the five-method contract, column cascade,
  static/dynamic, passthrough, universal parameters, MRO `get_params`,
  category hierarchy, reserved columns.
- [x] `S/core/pipeline.md`: learn/apply/sql, immutability, sources, row id,
  NULL-drop reporting, `TransformResult`, JSON-only saving, `clone()`.
- [x] `S/core/columns.md`: per-column routing as one step, fanned out
  internally; disjoint columns; remainder policy.
- [x] `S/core/lazy.md`: `LazyResult` deferral, caches, `__array__`.
- [x] `S/core/frozen_pipeline.md`: `freeze()`, strict and tight apply, SQL
  text and two fingerprints, load compatibility table.
- [x] `S/core/audit.md`: per-column trace from fitted state; contradicts
  itself on touching data.
- [x] `S/compiler/INDEX.md`: "1–3 queries per learn" promise; `cte.py`
  undocumented.
- [x] `S/compiler/compile.md`: three phases, 11-step flow, multi-CTE fit
  template, discover validation, one DESCRIBE, set batching, sqlglot rationale.
- [x] `S/compiler/classify.md`: three tiers, criteria, sentinel, built-in
  classification table, summary output.
- [x] `S/compiler/compose.md`: expression merging, static-to-dynamic
  substitution, `query()` levels, passthrough.
- [x] `S/compiler/layers.md`: the boundary rule, worked example batching
  Impute and Scale, query-count table, conservatism.
- [x] `S/precision/INDEX.md`: summary of DECIMAL mode and its limits.
- [x] `S/precision/precision.md`: `precision="decimal38"`, CAST
  propagation, decimal strings in JSON, adapters, costs.
- [x] `S/errors/INDEX.md`: hierarchy at a glance and design choices.
- [x] `S/errors/errors.md`: full hierarchy, message template, dual
  inheritance, chaining, migration plan.
- [x] `S/concurrency/INDEX.md`: summary of the thread, process and async
  contract.
- [x] `S/concurrency/concurrency.md`: thread ownership, `clone()`,
  per-connection RLock, file lock, async wrapping, no pool.
- [x] `S/_hardening/INDEX.md`: what hardening files are and how they are
  used.
- [x] `S/_hardening/v0_8_hardening.md`: v0.8 checklist (bugs A1–A10,
  warnings B1–B5, `group_by` C1, correlations, inverse, Mahalanobis, audits
  G1–G7, polish H1–H4).
- [x] `S/logging/INDEX.md`: logger tree and design choices.
- [x] `S/logging/logging.md`: hierarchy, levels, `extra` dicts, no
  `print()`, `warnings` for deprecations only, no telemetry.
- [x] `S/warnings/INDEX.md`: map of the warnings subsystem (stale counts).
- [x] `S/warnings/fit_warnings.md`: fourteen checkers, API, registry,
  merging into the fit query.
- [x] `S/warnings/group_by_rules.md`: mitigation patterns A–H, seven
  warning rules and three info rules with SQL and templates.
- [x] `S/warnings/hyperfitting.md`: user page on preprocessing overfitting,
  effective parameters, `cv=K`.
- [x] `S/warnings/model_compatibility.md`: `target_model=` knowledge base
  and four checks.
- [x] `P/INDEX.md`: pro tree, everything parked.
- [x] `P/federated/INDEX.md`: planned split of the federated spec.
- [x] `P/federated/federated_execution.md`: four-phase star model,
  push-down order, algebraic and sketch merges, main budget, per-source
  state, alternatives rejected.

---
type: architecture
tags: [sqlglot, fit-ordering, cross-validation, learned-state, design-decisions]
summary: "Batch A design notes for sqlearn: decisions, the fit-ordering bug left in the design, CV two-phase discovery, learned state, and sqlglot SQL representation."
related: [docs/questions/archived/earlier-attempts/tomosius-sqlearn/notes/A-design.md]
mdindex: [type=4ca303, tags=57943b, summary=5c6876]
---
# Tomosius/sqlearn, batch A: design and decisions

Source (read only): `/Users/tomas/Desktop/Desktop - Tomas’s
MacBook Air/toosiaus_ducks_learnas/sqlearn-desktop`, called OLD. Batch: the
38 files in `architecture/`, the 30 in `ideas/`, the 7 generated reports,
`audits/audit-data.json` and the root files listed at the end. Nothing was
run; `project.duckdb` and `.env` were not opened. No read hung. Citations are
`OLD:path:Lnn`; inference is marked. The design documents date from 13 to 19
March 2026 (v0.1.0 to v0.3.0, milestones 1 to 4 done,
`OLD:CLAUDE.md:L276-L277`); they describe intent, and the code is batch B's.

## Summary

- **The ordering bug was found here first, and named, and then left in the
  design.** The rejected "QueryTemplate" idea says outright that a scaler
  after an imputer must learn from imputed values and that the fold-filter
  trick computes them from raw data
  (`OLD:ideas/rejected/query-template-single-pass.md:L13-L19`). The layer
  rule in the compiler design still puts Imputer and StandardScaler in one
  layer reading raw `price` (`OLD:architecture/design/compiler.md:L194-L226`).
- **The `WITH`-clause fix the v0.4 review proposed was already written down
  here**, as a "cross-layer batching" idea from `ducklearn1`:
  `WITH imputer_stats AS (SELECT MEDIAN(price) ...) SELECT
  AVG(COALESCE(price, (SELECT price_median FROM imputer_stats)))`
  (`OLD:ideas/active/base-features.md:L197-L207`). It was parked as an
  optimisation, not adopted as the correctness rule.
- **Static upstream steps were inlined into fit queries; dynamic ones were
  not.** `AVG(LN(price + 1))` for Log then Scale
  (`OLD:architecture/planning/performance.md:L56-L82`), via
  `_substitute_columns()`. The reference YAMLs claim the same function also
  handles Imputer then Scale
  (`OLD:architecture/reference/scalers.yaml:L35-L38`),
  which the design documents contradict. Batch B should check the code.
- **Learned state: Python dicts `params_` and `sets_` keyed `col__stat`,
  baked into SQL as literals** ("Baked" strategy), plus a second
  "self-contained" strategy where statistics live in a `stats` CTE joined
  with `CROSS JOIN` (`OLD:architecture/design/cv-design.md:L7-L47`). That
  second strategy is learned state as a relation, which the baseline said
  was never considered.
- **sqlglot everywhere, by decision**: "All SQL via sqlglot ASTs, never raw
  strings. Multi-database from day one"
  (`OLD:architecture/decisions.md:L62-L63`). The v30 break (292 pyright
  errors) and the `<30` pin start in this attempt
  (`OLD:ideas/active/concerns-risks.md:L152-L158`).
- **The API kept scikit-learn's method names** (`fit`, `transform`,
  `fit_transform`, `get_params`, `set_params`, `get_feature_names_out`,
  `__sklearn_is_fitted__`), with one base class instead of mixins
  (`OLD:architecture/design/base-class.md:L98-L149`). The `learn`/`apply`
  rename came later, in v0.4.
- **Validation was "match scikit-learn"**: `assert_allclose(..., rtol=1e-6)`
  (`OLD:architecture/design/testing.md:L26-L39`), `atol=1e-10` in the risk
  table (`OLD:architecture/decisions.md:L8`). No exact reference yet.
- **Static/dynamic classification in three tiers**, with the asymmetric-cost
  rule "false static = data corruption, false dynamic = one query" and a
  runtime guard dict that raises when a static step reads `params_`
  (`OLD:architecture/design/static-dynamic.md:L227-L238`,
  `OLD:architecture/design/classification-impl.md:L99-L160`).
- **The project database was agent tooling, not library state**: a DuckDB
  file of code inventory, backlog, ideas and audit findings, queried by
  agents through an MCP server
  (`OLD:architecture/design/project-database.md:L7-L46`).
  It was paused unfinished on 19 March (`OLD:CURRENT_WORK.md:L9-L24`).
- **Scope ran far ahead of the core**: 135 decisions, half of them about a
  paid Studio UI, its licence keys and its JavaScript libraries
  (`OLD:architecture/decisions.md:L94-L130`, `L165-L169`).

## Fit execution

**What was designed.**

- `discover()` returns `{name: sqlglot aggregate}`; `discover_sets()` returns
  `{name: sqlglot query}` for multi-row results (categories, per-category
  means) (`OLD:architecture/design/base-class.md:L43-L68`,
  `OLD:architecture/decisions.md:L151`). `query()` is the second hook for
  steps that need their own query level (windows, joins)
  (`OLD:architecture/design/base-class.md:L83-L89`, `L594-L696`).
- **Layers** (decision 7: "Layers during fit, one query for transform",
  `OLD:architecture/decisions.md:L50`). A boundary is cut only after a step
  that is dynamic **and** schema-changing
  (`OLD:architecture/design/compiler.md:L194-L197`,
  `OLD:architecture/planning/performance.md:L107-L129`). Per layer: one
  batched scalar `SELECT`, one `SELECT DISTINCT` per set, then a temp view
  (`OLD:architecture/design/compiler.md:L218-L240`). "Total fit: 3-4
  queries for the entire pipeline" (`L242`).
- Static steps are inlined into the next dynamic step's aggregate:
  `AVG(LN(price + 1))` (`OLD:architecture/planning/performance.md:L60-L82`;
  `_substitute_columns()`, `OLD:architecture/reference/core.yaml:L135`).
- Transform is always one query of literals; "The transform query never
  contains aggregate functions"
  (`OLD:architecture/planning/performance.md:L35-L54`).
- Fit reads through session-scoped temp views only; the Backend protocol has
  no write methods (decision 133, `OLD:architecture/decisions.md:L182`;
  `OLD:architecture/design/api-design.md:L310-L370`).
- A three-phase planner (inspection, execution, transform) was described from
  `ducklearn1` but left implicit
  (`OLD:architecture/design/compiler.md:L247-L304`).

**What goes wrong, in the design itself.**

- Layer 0 holds `[Imputer, StandardScaler, OneHotEncoder]`, and its query is
  `MEDIAN(price)`, `AVG(price)`, `STDDEV_POP(price)` from the same raw table
  (`OLD:architecture/design/compiler.md:L207-L226`). The worked "complete
  fit flow" repeats it (`OLD:architecture/design/base-class.md:L563-L581`).
  `discover(columns, schema, y_column)` gets no upstream expressions
  (`OLD:architecture/design/base-class.md:L43`), so a dynamic step cannot see
  what an earlier dynamic step did (inference from the signature).
- The problem was seen three times and fixed nowhere:
  - the rejected QueryTemplate
    (`OLD:ideas/rejected/query-template-single-pass.md:L13-L19`, `L28-L40`);
  - the SQL API's "CTE sequential fitting" and "sub-pipelines fitted on wrong
    data (SILENT BUG)" (`OLD:ideas/active/sql-api-problems.md:L42-L73`,
    `L109-L138`);
  - an audit note on Pipeline: "chained dynamic steps ... Verify this is the
    actual behavior before implementing CV"
    (`OLD:architecture/reference/core.yaml:L119-L122`).
- The reference YAMLs say the opposite: Imputer then Scale "is handled by
  `_substitute_columns()`" (`OLD:architecture/reference/scalers.yaml:L35-L38`,
  `OLD:architecture/reference/imputers.yaml:L56-L59`). One batched query
  cannot substitute a value it has not computed yet, so either the code runs
  more queries than the design says or the claim is wrong (inference; for
  batch B).
- Two documents still present QueryTemplate as a decision after its rejection
  on 17 March (`OLD:architecture/decisions.md:L183`,
  `OLD:architecture/planning/performance.md:L207-L256`).
- Row-changing steps are undefined during fit: `Filter`, `Sample` and
  `OutlierHandler(action="remove")` use `query()`, and nothing says whether
  fit sees the filtered rows
  (`OLD:architecture/reference/features.yaml:L677-L678`;
  inference: no rule in any design file).
- Windows and group features are "static" and compute over whatever rows the
  transform sees (`OLD:architecture/design/classification-impl.md:L268-L281`);
  the reference flags them `cv_safe=false`
  (`OLD:architecture/reference/features.yaml:L453-L455`).

**Cross-validation.**

- Fold column `__sq_fold__ = NTILE(k) OVER (ORDER BY HASH(rowid || seed))`
  in a temp view, reserved prefix `__sq_*__`
  (`OLD:architecture/design/cv-design.md:L195-L227`).
- **Two-phase discovery**: set-valued state (categories) from all training
  data so every fold has the same columns; scalar state per fold with
  `AVG(x) FILTER (WHERE __sq_fold__ != :k)`
  (`OLD:architecture/design/cv-design.md:L57-L115`). The argument that
  knowing the category universe "is not leakage" is at `L111-L115`. Rejected
  for the single-pass template because chained steps break it; the
  fix it names, per-fold intermediate CTEs, "defeats the purpose"
  (`OLD:ideas/rejected/query-template-single-pass.md:L42-L44`).
- A planned test checks `FILTER` against a physical subset for each
  aggregate (`OLD:architecture/design/testing.md:L412-L430`): a good pattern
  for any fold-filtered statistic.

## Learned state

- Per step: `params_` (scalars), `sets_` (lists of dicts), `columns_`,
  `input_schema_`, `_fitted`
  (`OLD:architecture/design/base-class.md:L300-L307`).
  Keys are `col__stat`; the fit query aliases them `step__col__stat`
  (`OLD:architecture/design/compiler.md:L222-L226`). `params_` is `None`
  before fit (`OLD:architecture/reference/core.yaml:L74`).
- Values become SQL literals in transform ("Baked", default for fit,
  transform, export and `describe()`,
  `OLD:architecture/design/cv-design.md:L12-L23`, `L40-L47`).
- The "self-contained" strategy keeps statistics as a one-row relation:
  `WITH stats AS (SELECT AVG(price) ... WHERE __sq_fold__ != :k) SELECT
  (price - stats.mean_price) / stats.std_price FROM data CROSS JOIN stats`
  (`OLD:architecture/design/cv-design.md:L25-L38`). TargetEncoder's
  per-category means are a `GROUP BY` CTE joined back
  (`OLD:architecture/design/cv-design.md:L143-L168`).
- `sq.custom()` builds SQL by `str.replace` and `str(value)` of the learned
  value before parsing (`OLD:architecture/design/base-class.md:L390-L402`):
  the float-to-literal round trip again, unchecked.
- Static steps get `_FrozenEmptyParams`, a dict that raises on any read
  (`OLD:architecture/design/classification-impl.md:L104-L160`). It makes
  "not fitted" and "has no state" distinct, the sentinel problem the
  baseline records.
- Saving: YAML config with `fitted:` blocks, schema in and out, and a
  versioned format with `sql_hash` to detect silent SQL changes
  (`OLD:architecture/planning/export.md:L38-L108`,
  `OLD:architecture/decisions.md:L156`); `freeze()` embeds the SQL string
  (`OLD:architecture/planning/export.md:L110-L146`). Pickle was also allowed
  (`OLD:architecture/design/base-class.md:L243-L253`).
- `FitSnapshot` (idea): an immutable record per fit of params, sets, SQL and
  schemas, because CV fits overwrote `params_`
  (`OLD:ideas/active/fit-snapshot.md:L10-L11`, `L53-L75`).
- Tables were considered once, for caching transformed folds
  (`__sq_search__.fold_0_train`, `OLD:ideas/active/cv-performance.md:L30-L57`),
  which contradicts the read-only, temp-view-only decision 133 (inference).

## SQL representation

- Decision 19: all SQL as sqlglot ASTs, "Multi-database from day one";
  decision 20: a Backend protocol from phase 1
  (`OLD:architecture/decisions.md:L62-L63`). `discover()` and
  `expressions()` must return sqlglot nodes; custom code that returns a
  string is a `TypeError` (`OLD:architecture/design/base-class.md:L419-L456`).
- `to_sql(dialect=)` for any sqlglot dialect, with a fallback table and
  `strict=False` to skip unsupported steps
  (`OLD:architecture/design/compiler.md:L358-L388`,
  `OLD:architecture/design/api-design.md:L266-L308`).
- Costs already visible here: the v30 break and the `<30` pin
  (`OLD:ideas/active/concerns-risks.md:L152-L158`, `OLD:pyproject.toml:L27`);
  `sqlglot[rs]` deprecated, its warning silenced
  (`OLD:pyproject.toml:L210-L214`);
  shared mutable AST nodes in Normalizer and unquoted identifiers
  (`OLD:BACKLOG.md:L237-L238`); "DuckDB coupling despite sqlglot" and only
  DuckDB in CI (`OLD:ideas/active/concerns-risks.md:L138-L150`,
  `OLD:ideas/active/testing-quality.md:L12-L25`).
- An "AST-based classification" idea would use sqlglot to inspect a step's
  SQL to prove it static
  (`OLD:architecture/design/classification-impl.md:L438-L469`);
  never built (inference).
- A second front end, SQL with `sq_*` functions parsed by sqlglot, was
  designed in four modes; its first blocker is that one-hot encoding cannot
  be a SQL function returning several columns
  (`OLD:ideas/active/sql-api-modes.md:L8-L23`,
  `OLD:ideas/active/sql-api-problems.md:L11-L38`).

## API and scikit-learn

- Kept: `fit`, `transform`, `fit_transform`, `get_params(deep=True)` with
  `__` nesting, `set_params`, `get_feature_names_out`,
  `__sklearn_is_fitted__`, `clone`, trailing-underscore fitted attributes
  (`OLD:architecture/design/base-class.md:L98-L149`, `L282-L305`).
- Departures, each with a reason in the decisions log:
  - one base class, no mixins, "no historical baggage" (decision 1,
    `OLD:architecture/decisions.md:L44`);
  - default column routing per class (`_default_columns = "numeric"`), so
    ColumnTransformer is rarely needed (decision 2, `L45`;
    `OLD:architecture/design/column-routing.md:L7-L33`);
  - `Columns` and `Union` renamed from ColumnTransformer and FeatureUnion,
    "shorter name" (decisions 11, 12, `L54-L55`);
  - `y` is a column name, excluded from the output by default (decision 93,
    `L139`; `L230-L239`);
  - `fit("train.parquet")` takes a source, not an array
    (`OLD:architecture/design/api-design.md:L7-L23`);
  - `+` and non-mutating `+=` build flat pipelines (decisions 90, 105,
    `L136`, `L153`);
  - `TransformResult` with `__array__` rather than a numpy subclass
    (decision 106, `L154`); dense one-hot by default (`L241-L257`).
- `expressions()` returns only changed columns; the base class passes the
  rest through (decision 102, `OLD:architecture/decisions.md:L150`;
  `OLD:architecture/design/base-class.md:L174-L212`).
- Inconsistent: "A Pipeline IS a Transformer"
  (`OLD:architecture/design/pipeline.md:L36`) against "Pipeline is NOT a
  Transformer subclass" (`OLD:architecture/reference/core.yaml:L116`).
- Universal `condition=` parameter (impute or scale only rows matching a SQL
  predicate; `FILTER` in fit, `CASE WHEN` in transform), shipped for
  `expressions()` steps only (`OLD:ideas/active/base-features.md:L8-L60`).

## Validation

- Reference is scikit-learn: per-transformer equivalence tests,
  `rtol=1e-6` (`OLD:architecture/design/testing.md:L20-L39`), `atol=1e-10`
  and `STDDEV_POP` for ddof=0 (`OLD:architecture/decisions.md:L8`). The
  `Decimal` exact reference seen in v0.4 does not exist yet.
- Per-transformer checklist: NULLs, single row, constant column, empty table,
  SQL snapshot, schema, fit-to-SQL round trip, clone
  (`OLD:architecture/design/testing.md:L9-L18`).
- Hypothesis properties (determinism, inverse, `+` associativity, feature
  names match output) (`OLD:architecture/design/testing.md:L263-L286`);
  exhaustive flag combinations for the classifier (`L43-L84`); mutation
  testing with "zero surviving mutants in compiler.py and transformer.py"
  (`OLD:CLAUDE.md:L200-L202`).
- Fixtures: one synthetic 1,000-row Parquet with known NULLs, distributions
  and correlations, plus a "small real-world dataset (e.g. iris, tips)"
  (`OLD:architecture/design/testing.md:L562-L598`). How it would be obtained
  is not said.
- Version matrix: DuckDB 1.0.0 and 1.1.0, sqlglot 25.0 and 25.8
  (`OLD:architecture/design/testing.md:L467-L486`).
- The design claims `Sample(seed=42)` is deterministic
  (`OLD:architecture/design/pipeline.md:L251`) while the reference says seeds
  are not supported (`OLD:architecture/reference/ops.yaml:L107`).

## Rejected ideas and why

- **QueryTemplate single-pass CV** (rejected 17 March): one parameterised
  query with `:k` for all folds, statistics via `FILTER`. Rejected because
  "each dynamic step's input is the previous step's fold-specific output,
  not the original source"; making it work would need per-fold intermediate
  CTEs, "which defeats the purpose"
  (`OLD:ideas/rejected/query-template-single-pass.md:L13-L19`, `L42-L44`).
  The right diagnosis; the cure missed is that the earlier step's learned
  value can itself be a CTE (`OLD:ideas/active/base-features.md:L197-L207`).
- **Bulk rejection of 273 of 475 brainstormed ideas** (17 March), by
  category (`OLD:ideas/rejected/bulk-evaluation-2026-03-17.md:L3-L68`):
  - DuckDB already reads the format: no `sq.from_*()` wrappers (`L12-L16`);
  - not SQL-native: iterative state, O(n²), splines, graphs, exponential
    smoothing (`L18-L27`);
  - enterprise, MLOps and feature-store platforms (`L29-L43`);
  - full NLP beyond text statistics (`L45-L48`);
  - niche encoders and scalers, under 1% of users (`L50-L55`);
  - second-guessing DuckDB's optimiser (index hints, join order, memory)
    (`L57-L60`);
  - presentation and delivery (Slack, PowerPoint) (`L62-L64`);
  - wrong tool: HTML stripping, images, fuzzy joins (`L66-L68`).
- Also dropped along the way: sqlearn-studio as a separate repository
  (decision 51 superseded by 52), a separate private Pro repository
  (84 to 84b), and Handsontable and borb on licence grounds (decisions 80,
  81) (`OLD:architecture/decisions.md:L94-L95`, `L123-L130`).
- Exponential smoothing was "not SQL-native" in the rejection
  (`OLD:ideas/rejected/bulk-evaluation-2026-03-17.md:L21`) yet `EWM` is a
  static recursive-CTE step (decision 114,
  `OLD:architecture/decisions.md:L162`).

## The project database

- **What:** `project.duckdb`, gitignored and rebuilt from source by
  `tools/projectdb.py`, with schemas `inventory` (modules, classes,
  functions, imports, test mapping from the Python AST), `architecture`
  (from the YAMLs), `tracking` (backlog, ideas), `skills`, `meta` and
  persistent `audit` tables (findings, health scores, agent performance)
  (`OLD:project-db-init.sql:L1-L26`, `L48-L260`;
  `OLD:architecture/reference/project-database.yaml:L16-L30`).
- **Why:** agents spent their tokens crawling files;
  `class_info('StandardScaler')` would cost ~100 tokens instead of ~2,000,
  and joins answer cross-cutting questions
  (`OLD:architecture/design/project-database.md:L9-L22`). Agents reached it
  through `mcp-server-motherduck`; DuckDB macros were the "agent API"
  (`L36-L46`, `L79-L87`).
- **Outcome:** tasks 0 to 6 done, then "Paused ... User wants to reconsider
  the overall approach" (`OLD:CURRENT_WORK.md:L9-L24`). The audit backup
  holds one test row (`OLD:audits/audit-data.json:L1-L26`); the summary shows
  0 findings (`OLD:reports/generated/db-summary.md:L3-L13`). It displaced the
  library's own pre-M5 work (`OLD:CURRENT_WORK.md:L32-L40`). DuckDB macros
  cannot write, so write "macros" were templates for agents to paste
  (`OLD:architecture/reference/project-database.yaml:L345-L347`).
- Not related to learned state or the library; a process artefact.

## New against the baseline

- The fit-order bug was diagnosed in writing in March, before v0.4, and the
  design kept it.
- The one-query `WITH` fix appeared here already, from `ducklearn1`, as an
  optimisation idea.
- Learned state as a relation (`stats` CTE, `CROSS JOIN`) was designed, for
  CV only.
- Static upstream steps were threaded into fit aggregates
  (`_substitute_columns()`); only dynamic ones were not.
- Classification by cost asymmetry, three tiers, and a raising guard on
  static steps' `params_`.
- Two-phase discovery: category universe from all data, values per fold.
- A `FILTER`-versus-subset parity test for every fold aggregate.
- The project database: agent tooling in DuckDB through MCP, abandoned.
- `condition=` on every step: statistics from a row subset.

## Contradicts the baseline

- "Both renamed scikit-learn's methods": this attempt kept every method name;
  the rename began in v0.4.
- "Tables were never considered": a `stats` CTE relation and per-fold
  materialised tables were both designed here.
- "Validation: exact references": not here; scikit-learn was the reference.

## Confirms the baseline

- A later dynamic step learns from raw input inside a layer.
- The boundary rule was "schema changed", not "learning step reads a changed
  value".
- Fit and transform composed through different paths (layer views against
  one transform query; inference from the design).
- Learned state as `__`-keyed Python values inlined as literals, unchecked.
- sqlglot from the start; v30 pin, AST aliasing, DuckDB-only CI.
- Fit leaking into transform: window and group steps compute over transform
  data.
- Plans outran product: 135 decisions, Studio pricing before milestone 5,
  stale QueryTemplate entries, a README at v0.1.0 beside a CLAUDE.md at
  v0.3.0 (`OLD:README.md:L96-L99`).

## Worth keeping

- The asymmetric-cost rule: if a step cannot be proved free of learned
  state, treat it as learning
  (`OLD:architecture/design/static-dynamic.md:L227-L238`).
- A guard that makes reading state on a stateless step an error
  (`OLD:architecture/design/classification-impl.md:L104-L160`).
- The rejected QueryTemplate page as the plainest statement of the fit-order
  rule (`OLD:ideas/rejected/query-template-single-pass.md:L13-L19`).
- The `stats` CTE with `CROSS JOIN` and `FILTER (WHERE fold != k)` as a way
  to fit every fold in one scan, once chained steps read earlier CTEs
  (`OLD:architecture/design/cv-design.md:L88-L109`).
- Category universe fixed before folds so every fold has the same columns,
  with the leakage argument written out (`L57-L115`); check it against
  scikit-learn's own behaviour before adopting.
- `FILTER`-equals-subset tests for each aggregate
  (`OLD:architecture/design/testing.md:L412-L430`).
- Read-only by construction: no write operation in the engine interface,
  temp views only (`OLD:architecture/design/api-design.md:L310-L370`).
- `sql_hash` in saved pipelines to detect SQL that changed under a new
  version (`OLD:architecture/planning/export.md:L38-L67`).
- The bulk rejection categories as a scope filter, especially "DuckDB
  already does this" and "not SQL-native"
  (`OLD:ideas/rejected/bulk-evaluation-2026-03-17.md:L12-L27`).
- Seeded, ordered fold assignment in a reserved-prefix column
  (`OLD:architecture/design/cv-design.md:L195-L227`); recheck that
  `HASH(rowid || seed)` is stable across DuckDB versions (the design itself
  doubts it, `OLD:architecture/design/pipeline.md:L254-L257`).

DuckDB claims to recheck: `FILTER` with `MEDIAN`, `MODE` and
`PERCENTILE_CONT`; "zone maps give `MIN = MAX` in O(1)" on a view or
expression (`OLD:architecture/design/cv-design.md:L191`; doubtful,
inference); temp views on a file database write nothing
(`OLD:architecture/design/api-design.md:L349-L353`).

## Files covered

`architecture/` (38):

- [x] `INDEX.yaml`: map of 103 reference sections; skimmed.
- [x] `README.md`: table of contents for the architecture folder.
- [x] `decisions.md`: risks, 135 decisions, open questions; read in full.
- [x] `design/api-design.md`: inputs, outputs, backend, read-only rule.
- [x] `design/base-class.md`: the Transformer contract and fit flow; full.
- [x] `design/classification-impl.md`: schema change, guard, built-in table.
- [x] `design/column-routing.md`: default columns per class.
- [x] `design/compiler.md`: composition, layers, three phases; full.
- [x] `design/custom-api.md`: three custom levels; read by heading and limits.
- [x] `design/cv-design.md`: baked and self-contained, two-phase; full.
- [x] `design/error-hierarchy.md`: error classes, NULL policy, drift.
- [x] `design/output-format.md`: `TransformResult` wrapper.
- [x] `design/overview.md`: philosophy, replacements, structure, non-goals.
- [x] `design/pipeline.md`: input forms, `+`, immutability, reproducibility.
- [x] `design/project-database.md`: why the agent database existed.
- [x] `design/schema.md`: Schema dataclass.
- [x] `design/static-dynamic.md`: three tiers and the safety rule; full.
- [x] `design/testing.md`: test strategy; first half full, rest by heading.
- [x] `planning/analysis.md`: profile, quality, check; by heading.
- [x] `planning/business-model.md`: free and Pro tiers; skimmed.
- [x] `planning/documentation.md`: docstring standard, doctests; skimmed.
- [x] `planning/export.md`: versioning, YAML config, freeze.
- [x] `planning/milestones.md`: M5 to M9 and release table; skimmed.
- [x] `planning/performance.md`: literals, inlining, QueryTemplate, CTE depth.
- [x] `planning/search.md`: `sq.Search`, splits as views; skimmed.
- [x] `planning/studio-tech.md`: Studio stack; by heading.
- [x] `planning/studio.md`: Studio UX; by heading.
- [x] `reference/auto.yaml`: Auto* steps; known risks read.
- [x] `reference/core.yaml`: core components and audit risks; first 230 lines.
- [x] `reference/custom.yaml`: Expression and custom; head read.
- [x] `reference/data.yaml`: merge, concat, Lookup; head read.
- [x] `reference/encoders.yaml`: encoders; known risks read.
- [x] `reference/feature-selection.yaml`: selectors; known risks read.
- [x] `reference/features.yaml`: feature steps; known risks read.
- [x] `reference/imputers.yaml`: Imputer; known risks read.
- [x] `reference/ops.yaml`: Rename to Deduplicate; head and Sample read.
- [x] `reference/project-database.yaml`: agent database schema and risks.
- [x] `reference/scalers.yaml`: scalers; known risks read.

`ideas/` (30):

- [x] `INDEX.md`: dashboard and milestone gateways; head and rejected list.
- [x] `active/analysis-functions.md`: EDA helpers; by heading.
- [x] `active/base-features.md`: `condition=`, cross-layer CTE batching.
- [x] `active/business.md`: marketing; by heading.
- [x] `active/concerns-risks.md`: 20 concerns incl. sqlglot v30; full.
- [x] `active/cv-performance.md`: fold views, `FILTER`, fold tables; full.
- [x] `active/dataset-splits.md`: `__sq_dataset__` column; by heading.
- [x] `active/documentation-ideas.md`: content ideas; by heading.
- [x] `active/duckdb-extension.md`: Rust extension, Mode 4; skimmed.
- [x] `active/expansion-ideas.md`: 109 kept ideas; by heading.
- [x] `active/exploration-functions.md`: `__call__`, repr; by heading.
- [x] `active/fit-snapshot.md`: immutable per-fit record; full.
- [x] `active/integrations.md`: Rust, GPU; by heading.
- [x] `active/long-term-vision.md`: plugins, pipeline JSON; head read.
- [x] `active/new-transformers.md`: 28 proposed steps; by heading.
- [x] `active/pipeline-enhancements.md`: fit `sample=`, naming; partly read.
- [x] `active/pipeline-step-search.md`: `sq.Choice`; by heading.
- [x] `active/production-features.md`: incremental fit etc.; partly read.
- [x] `active/safety-guards.md`: ordering validation; partly read.
- [x] `active/someday-maybe.md`: parked ideas; by heading.
- [x] `active/sql-api-modes.md`: SQL front end, four modes; first 180 lines.
- [x] `active/sql-api-problems.md`: eight SQL API problems; full.
- [x] `active/studio.md`: seven-line stub.
- [x] `active/testing-quality.md`: dialect, fuzz, injection tests; full.
- [x] `active/transformer-enhancements.md`: step extensions; by heading.
- [x] `active/ux-ergonomics.md`: errors, progress, repr; by heading.
- [x] `active/vortex-integration.md`: Vortex format; by heading.
- [x] `done/already-existed-m4.md`: 12 ideas already built.
- [x] `rejected/bulk-evaluation-2026-03-17.md`: 273 rejections; full.
- [x] `rejected/query-template-single-pass.md`: the fit-order rejection; full.

`reports/generated/` (7), `audits/` (1):

- [x] `churn-report.md`: git churn per file to 18 March.
- [x] `consistency-issues.md`: eight "untested module" rows.
- [x] `coverage-gaps.md`: classes missing architecture docs.
- [x] `db-summary.md`: row counts of the agent database.
- [x] `import-graph.md`: most imported modules.
- [x] `project-matrix.md`: class by docs, findings, churn.
- [x] `skill-coverage.md`: 26 agent skills listed.
- [x] `audits/audit-data.json`: one test finding, otherwise empty.

Root (9):

- [x] `README.md`: pitch, example SQL, status v0.1.0 (stale).
- [x] `CLAUDE.md`: agent guide, core concepts, toolchain, v0.3.0.
- [x] `BACKLOG.md`: milestones M1 to M9, fixed bugs; read in full.
- [x] `CONTRIBUTING.md`: setup, "all SQL via sqlglot ASTs".
- [x] `CURRENT_WORK.md`: project database paused 19 March.
- [x] `pyproject.toml`: runtime deps `duckdb>=1.0` (MIT), `numpy>=1.24`
  (BSD-3-Clause), `sqlglot[rs]>=25.0,<30` (MIT); Python 3.10; strict typing.
- [x] `Makefile`: `uv`-based targets, three test tiers, mutmut.
- [x] `mkdocs.yml`: Material site; MathJax loaded from unpkg (network).
- [x] `project-db-init.sql`: agent database schema, read as text.

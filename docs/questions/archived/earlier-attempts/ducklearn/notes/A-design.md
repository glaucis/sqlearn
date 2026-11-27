---
type: note
tags: [sqlearn, sql-compilation, preprocessing, cross-validation, design-review]
summary: "Original design-only ducklearn/sqlearn proposal compiling Python preprocessing steps into DuckDB SQL, reviewed for scope, API, compiler and cross-validation."
related: [docs/questions/archived/earlier-attempts/ducklearn/notes/A-design.md]
mdindex: [type=edb465, tags=7b4bea, summary=5c2a77, related=1a2e7a]
---
# ducklearn: the original design (batch A)

Attempt: `ducklearn`, 2026-03-13, no git, 14 design documents and no code
(`OLD:CLAUDE.md:L167`). It is the first design of the project: 9,748 lines of
prose, 132 numbered decisions (`OLD:docs/14-decisions.md:L44-L180`; the agent
guide still says 121, `OLD:CLAUDE.md:L152`). OLD is the folder
`ducklearn` under ROOT. Citations are `OLD:path:Lnn` with file-relative line
numbers. "(inference)" marks my reading, not the text. "Baseline" is **What we
know so far** in the README.

## Summary

- A design-only project: an agent guide, a backlog, 14 documents, four
  skills. Nothing was implemented; the first milestone is "scaffolding"
  (`OLD:CLAUDE.md:L167`, `OLD:BACKLOG.md:L14-L22`).
- Core idea: Python steps compile to one `SELECT` of nested sqlglot ASTs,
  `Transformer` with `discover()`, `discover_sets()`, `expressions()`,
  `query()`, `output_schema()` (`OLD:docs/03-architecture.md:L31-L92`).
- Fit is "layers": one batched aggregate query per layer, cut after a
  schema-changing dynamic step; transform is always one query
  (`OLD:docs/04-compiler.md:L184-L241`). This is the rule that, in the
  baseline, scales an un-imputed column; here the doc's own example does it
  (see Confirms).
- Learned state is Python values (`params_`, `sets_`) baked into SQL
  literals and saved as YAML or a versioned file
  (`OLD:docs/03-architecture.md:L1507-L1513`,
  `OLD:docs/08-export.md:L29-L99`).
- A three-tier static/dynamic classification (built-in trusted and tested in
  CI, custom verified once, undeclared inspected), with "any doubt means
  dynamic" (`OLD:docs/03-architecture.md:L452-L464`, `L648-L659`).
- Cross-validation was designed in: a fold column, per-fold statistics with
  `FILTER`, and "two-phase discovery" so every fold has the same output
  columns (`OLD:docs/03-architecture.md:L1696-L1873`).
- The scope is far wider than preprocessing: model search with
  multi-fidelity, an analysis suite (quality score, leakage check, audit),
  freeze and export, and a local web "Studio" (`OLD:docs/06`, `07`, `08`).
- A commercial plan: one MIT package, a licence key unlocking "Pro" Studio
  features, 14-day trial, $49-99 (`OLD:docs/11-business-model.md:L5-L42`,
  `L247-L256`). It conflicts with ADR 0004's rule that paid things are
  separate packages.
- The author's own review items already named the process risk: timeline
  60-70 weeks, duplicated plan documents, "validate the compiler first"
  (`OLD:BACKLOG.md:L145-L161`).
- The best parts to keep: the classification-by-CI idea, two-phase fold
  discovery, discover/discover_sets split, baked vs self-contained SQL, the
  "SQL computes, browser renders" EDA principle (see Worth keeping).

## Design as written

### Philosophy and scope

- "Safe defaults, power opt-in": nothing clever unless asked. `Auto*` steps
  are explicit pipeline steps, never injected; `AutoFeatures.to_explicit()`
  freezes auto decisions for production (`OLD:docs/01-overview.md:L11-L64`,
  `OLD:docs/05-transformers.md:L521-L552`, `OLD:docs/14-decisions.md:L174`).
- Claims to replace `sklearn.preprocessing`, `impute`, `pipeline`, `compose`,
  `feature_selection`, `model_selection`, `metrics`, plus pandas data ops
  (`OLD:docs/01-overview.md:L76-L91`). "100% of preprocessing and feature
  engineering"; models, PCA/SVD, text vectorisation and images are out
  (`OLD:docs/01-overview.md:L93-L105`).
- Non-goals: no model training, no distributed or streaming execution, no
  multi-tenant Studio, no data versioning or experiment tracking, no GPU, no
  custom aggregates (`OLD:docs/12-milestones.md:L439-L455`).
- Name and import: `import sqlearn as sq`, "sk to sq"
  (`OLD:docs/01-overview.md:L130-L132`).

### API

- Pipelines are lists, tuple-lists or dicts; a Pipeline is a Transformer, so
  nesting is allowed (`OLD:docs/02-api-design.md:L85-L137`).
- `fit` takes a data source, not an array: a table name, file, glob, S3 path,
  DataFrame, Arrow table or NumPy array (registered as a temp table)
  (`OLD:docs/02-api-design.md:L235-L251`). `y` is a column name, or a list,
  not an array, and the target is dropped from the output by default
  (`OLD:docs/14-decisions.md:L139`, `OLD:docs/14-decisions.md:L226-L235`).
- Each step has a default column set (`_default_columns`: all, numeric,
  categorical, temporal), so `ColumnTransformer` is "rarely needed"
  (`OLD:docs/02-api-design.md:L48-L83`). Selectors: `sq.numeric()`,
  `sq.matching("price_*")`, `sq.dtype("DOUBLE")` (`L61-L67`).
- Composition: `Pipeline`, `Columns` (ColumnTransformer), `Union`
  (FeatureUnion); `+` flattens, `+=` returns a new Pipeline (value
  semantics), no `|` operator (`OLD:docs/02-api-design.md:L139-L233`,
  `OLD:docs/14-decisions.md:L136`, `L153`).
- Output: eager NumPy by default, wrapped in `TransformResult` (an
  `__array__` wrapper carrying `columns`, `dtypes`, `sql`), with
  `out="relation" | "arrow" | "pandas" | "polars" | "parquet"`,
  `batch_size=` streaming, `dtype=` cast, and a warning above 1 GB estimated
  size (`OLD:docs/02-api-design.md:L253-L406`).
- Backend: in-memory DuckDB by default, persistent file, user connection,
  global `set_backend`; precedence call > pipeline > global > in-memory
  (`OLD:docs/02-api-design.md:L408-L439`). "One pipeline = one DuckDB
  engine"; other sources come in through `ATTACH` (`L441-L462`).
- Data assembly: `sq.merge()` returns a content-hashed view name,
  `sq.concat()`, and `sq.Lookup` as a mid-pipeline join
  (`OLD:docs/02-api-design.md:L464-L564`).
- Inspection: `to_sql`, `describe`, `explain`, `preview`, `diff`, `lineage`,
  `get_feature_names_out`, `validate` (`OLD:docs/02-api-design.md:L1077-L1093`).
- Estimator plumbing kept from scikit-learn: `get_params`, `set_params` with
  `__` nesting, `clone`, `fit_transform`, `get_feature_names_out`
  (`OLD:docs/03-architecture.md:L117-L140`, `L236-L256`).
- Thread model: not thread-safe; a runtime guard checks thread id and pid and
  tells the user to `clone()` (`OLD:docs/03-architecture.md:L194-L219`,
  `OLD:docs/14-decisions.md:L138`).

### Transformer base class

- One base class replaces scikit-learn's mixin tower
  (`OLD:docs/03-architecture.md:L5-L30`, `L236-L256`).
- Author-facing methods: `discover(columns, schema, y_column)` returns
  `{name: sqlglot aggregate}`; `discover_sets(...)` returns
  `{name: sqlglot query}` for multi-row results (categories, per-category
  means); `expressions(columns, exprs)` returns only changed columns;
  `query(input_query)` returns a whole `SELECT` for windows and joins;
  `output_schema(schema)` declares added or removed columns
  (`OLD:docs/03-architecture.md:L31-L92`).
- The base class merges untouched columns (`_apply_expressions`), checks
  collisions, warns on undeclared new columns and drops columns the schema
  removes (`L154-L192`). Decision 102 explains it: forgetting passthrough was
  "the most common custom transformer bug" (`OLD:docs/14-decisions.md:L150`).
- Everything the author returns "MUST be sqlglot AST nodes, not strings"
  (`OLD:docs/03-architecture.md:L50`, `L77-L78`, `L86`).
- Idempotent `discover()` is a stated contract
  (`OLD:docs/03-architecture.md:L1419-L1435`).
- Three levels of custom steps: `sq.Expression("SQL")` (static one-liner);
  `sq.custom("({col} - {mean}) / {std}", columns=, learn={...})`, a
  template with `{col}` and `{param}` placeholders parsed by sqlglot at
  creation, learned names `{col}__{param}`; and a `Transformer` subclass
  (`OLD:docs/02-api-design.md:L566-L862`,
  `OLD:docs/03-architecture.md:L258-L355`). A `@sq.static_transform`
  decorator is also sketched (`OLD:docs/03-architecture.md:L268-L278`).
- `_validate_custom()` runs on first fit for non-built-ins: type checks on
  what `discover` and `expressions` return, schema consistency, parameter
  consistency, classification consistency
  (`OLD:docs/03-architecture.md:L357-L426`,
  `OLD:docs/02-api-design.md:L877-L933`).

### Compiler

- Expressions compose as `{column: AST}` dictionaries threaded through the
  steps; three Python steps become one `SELECT` with no CTE
  (`OLD:docs/04-compiler.md:L5-L40`).
- A CTE is introduced only for: a `query()` step (windows, joins), a complex
  expression referenced twice, or nesting deeper than 8; bare column
  references are never promoted (`OLD:docs/04-compiler.md:L42-L76`,
  `OLD:docs/03-architecture.md:L1620-L1628`, `OLD:CLAUDE.md:L125`). If a
  step defines both interfaces, `query()` wins
  (`OLD:docs/03-architecture.md:L1597-L1618`).
- `Columns` compiles to one `SELECT`, branches disjoint. `Union` compiles to
  one `SELECT` when every branch is expression-level, else a CTE per branch
  joined by a cross join "same row count guaranteed"; name collisions get a
  branch prefix (`OLD:docs/04-compiler.md:L78-L182`). The same-row-count
  assumption is an open question (`OLD:docs/14-decisions.md:L195`).
- A `Schema` dataclass (name to SQL type) is read once with `DESCRIBE` and
  then threaded through `output_schema()` without touching the database
  (`OLD:docs/03-architecture.md:L1630-L1650`). Names `__sq_*__` are reserved
  and rejected on read (`L1885-L1895`).

### How fit and transform were meant to work

- Fit resolution (`OLD:docs/04-compiler.md:L184-L241`):
  1. read the schema; resolve each step's columns from `_default_columns`;
  2. classify each step static or dynamic;
  3. cut "layers": a boundary after any schema-changing dynamic step;
  4. per layer, batch every step's `discover()` aggregates into one
     `SELECT ... FROM data`, and run one `SELECT DISTINCT` per
     `discover_sets()` entry (optionally `UNION ALL` when more than three
     columns, `OLD:docs/12-milestones.md:L564-L592`);
  5. store results in each step's `params_` and `sets_`;
  6. "materialize Layer 0's output as a temp view" so the next layer sees the
     new columns (`OLD:docs/04-compiler.md:L228-L236`).
- Worked flow with queries: 2 queries for Imputer + StandardScaler +
  OneHotEncoder, versus "one data pass per step" in scikit-learn
  (`OLD:docs/03-architecture.md:L1456-L1524`).
- Static steps contribute nothing to the fit query, though they stay in the
  layer for schema tracking (`OLD:docs/04-compiler.md:L210-L212`).
- Transform is "always one SQL query" with the learned numbers baked in as
  literals (`OLD:docs/04-compiler.md:L241`,
  `OLD:docs/03-architecture.md:L1701-L1712`).
- A static step's `params_` is a `_FrozenEmptyParams` that raises
  `StaticViolationError` on any access, `.get()` included
  (`OLD:docs/03-architecture.md:L1080-L1143`).
- Bigger-than-RAM is stated as a property of DuckDB: stream, spill, write to
  Parquet, or iterate in batches (`OLD:docs/04-compiler.md:L270-L291`).

### Cross-validation inside the compiler

- Two compile strategies, chosen by the library, never the user: **baked**
  (literals; fit then transform, export, describe) and **self-contained**
  (a stats CTE computed `FILTER (WHERE __sq_fold__ != :k)` and cross-joined;
  for cross-validation) (`OLD:docs/03-architecture.md:L1696-L1744`).
- "Two-phase discovery": phase 1 learns the category universe from all data
  (schema), phase 2 learns scalar statistics per fold. `discover_sets()` =
  phase 1, `discover()` = phase 2. Purpose: every fold yields the same output
  columns (`OLD:docs/03-architecture.md:L1746-L1873`,
  `OLD:docs/14-decisions.md:L152`, risk row `L29`, rated Critical).
- The claim that phase 1 is not leakage rests on "knowing Berlin exists is
  structural" (`OLD:docs/03-architecture.md:L1800-L1804`); for
  `TargetEncoder` the doc concedes the per-category means are value
  dependent and routes them through per-fold `FILTER` (`L1806-L1857`). The
  sketch of `TargetEncoder` is internally inconsistent (inference): it puts
  the universe in `discover_sets()` and one global mean in `discover()`, then
  says per-category means are computed "in the compiler" (`L1811-L1830`).
- Folds: a column `__sq_fold__` from `NTILE(k) OVER (ORDER BY HASH(...))`,
  variants for stratified, group, time series, repeated
  (`OLD:docs/03-architecture.md:L1875-L1907`).

### Learned state

- Per step, `params_` (dict of scalars from `fetch_one`) and `sets_` (dict of
  lists of row dicts) (`OLD:docs/03-architecture.md:L63-L65`,
  `L1507-L1513`). Keys follow `column__stat`, split on `__`; keys starting
  `__sq_` are rejected, and a key without `__` only warns
  (`L1030-L1044`). Fitted flag is `self._fitted` ("no trailing-underscore
  scanning") (`L147-L150`, `L243`).
- Values re-enter SQL as `exp.Literal.number(mean)` or `str(value)` in
  template substitution (`OLD:docs/03-architecture.md:L1553`, `L341`).
- Saved forms: a versioned binary/zip `.sqlearn` (with `sqlearn_version`,
  `format_version`, `sql_hash`, `schema_in`, `schema_out`), and a readable
  YAML with `fitted:` values per step (`OLD:docs/08-export.md:L29-L99`).
  `ModelPipeline.save` bundles `pipeline.json` and a pickled model
  (`OLD:docs/06-model-integration.md:L88-L110`).
- Search state lives in a DuckDB file ("queryable, portable, no pickle") and
  features are cached in temp tables keyed by an AST hash
  (`OLD:docs/06-model-integration.md:L320-L339`, `L402-L419`,
  `OLD:docs/14-decisions.md:L80`, `L87`). These are the only DuckDB tables
  in the design; learned parameters never are (inference from absence).

### SQL representation

- sqlglot ASTs everywhere, "never raw strings", chosen "for multi-database
  from day one" (`OLD:docs/01-overview.md:L73-L74`,
  `OLD:docs/14-decisions.md:L62`, `OLD:CLAUDE.md:L121`, `L161`).
- Even user templates are parsed at creation to fail fast
  (`OLD:docs/14-decisions.md:L171`).
- `sqlglot>=25.0` is a core dependency; the risk is named, mitigated by an
  internal `sql_utils.py` wrapper and a version range
  (`OLD:CLAUDE.md:L87-L88`, `OLD:docs/14-decisions.md:L7`).

### Dialects and backends

- A `Backend` protocol (`dialect`, `execute`, `fetch_one`, `describe`,
  `register`, `supports`) so Postgres, MySQL, Snowflake and BigQuery are
  "implementing one interface" (`OLD:docs/03-architecture.md:L1652-L1672`,
  `OLD:docs/14-decisions.md:L63`). Phase 1 ships DuckDB only.
- A compatibility table (FILTER, MEDIAN, HASH, Parquet read, schema inspect)
  and a plan: emit equivalent SQL where possible (FILTER to CASE), otherwise
  raise `CompilationError`, or skip with `strict=False`
  (`OLD:docs/03-architecture.md:L1674-L1694`,
  `OLD:docs/12-milestones.md:L530-L560`).
- Postgres and Spark backends are "ideas, not yet planned" in the backlog
  (`OLD:BACKLOG.md:L126-L127`).
- Pinning is advised for reproducibility: DuckDB `HASH()` may change across
  major versions, so fold assignment may too
  (`OLD:docs/12-milestones.md:L506-L526`).

### Model integration

- Models are out of scope. `ModelPipeline(preprocessor, model,
  target_transform=)` wraps a pipeline and any scikit-learn-style model with
  `fit`, `predict`, `predict_proba`, `score`, `save`, `load`, and nested
  `get_params` (`OLD:docs/06-model-integration.md:L25-L121`).
- `TargetTransform` (log, sqrt, standard, minmax, quantile) lives only inside
  `ModelPipeline` and inverts predictions
  (`OLD:docs/05-transformers.md:L648-L704`,
  `OLD:docs/14-decisions.md:L144`).
- `sq.Search` replaces GridSearchCV, RandomizedSearchCV, Optuna and Hyperopt:
  random, grid, Sobol, built-in TPE, "auto"; optional Optuna sampler; three
  spaces helpers; Hyperband-style rounds varying data fraction
  (`USING SAMPLE`), dtype and fold count; preprocessing deduplication by SQL
  hash; early stop per trial; checkpoint and resume; error recovery;
  warm start; functional-ANOVA parameter importance
  (`OLD:docs/06-model-integration.md:L123-L758`).
- Helpers: `sq.read_column` (target by one query), `sq.train_test_split` as
  SQL views over a split column, `sq.cross_validate`
  (`OLD:docs/06-model-integration.md:L571-L662`).
- Claimed cost: about 17x faster than scikit-learn or Optuna on the example
  (`OLD:docs/06-model-integration.md:L745-L758`); no measurement exists
  (design only).

### Analysis

- Levels 0 to 4: `quality()` (score 0-100 with a penalty table),
  `profile()`, `analyze()`, `recommend()`, `autopipeline()`
  (`OLD:docs/07-analysis.md:L8-L283`, `L1048-L1113`). `recommend` rests on a
  hand-written `MODEL_PROFILES` table and `FEATURE_SUGGESTIONS`
  (`L172-L223`, `L285-L327`).
- Safety functions: `check()` (identifier columns, target proxies by
  correlation above 0.95, train/test overlap, "future" columns),
  `pipe.audit()` (before and after statistics per column per step),
  `missing_analysis()` (MCAR/MAR by null-indicator correlation, an
  approximate Little's test), `feature_importance()` (Pearson, Spearman,
  Cramer's V, binned mutual information, ANOVA), warnings during `fit`
  (`OLD:docs/07-analysis.md:L1115-L1558`).
- Drift: `pipe.detect_drift(new_data)` compares new data with stored training
  statistics (`OLD:docs/09-error-handling.md:L36-L77`).
- All analysis is "SQL; any size", and the web Studio never sends raw data to
  the browser: histograms are 30 points, scatter 1,000 sampled rows
  (`OLD:docs/07-analysis.md:L349-L369`, `L926-L943`).

### Export

- `to_sql(dialect=)`, `to_dbt`, `to_config`/`from_config` (YAML), `save`/`load`,
  `export()` to a standalone script using only DuckDB
  (`OLD:docs/08-export.md:L5-L27`).
- `freeze()` returns an immutable `FrozenPipeline`: baked literals, fixed
  output schema, pre-compiled SQL string and SHA-256, input-schema check on
  every transform, `FrozenError` on `fit` (`OLD:docs/08-export.md:L101-L181`).
  Open question: embed the SQL string or the AST; leaning to the string
  (`OLD:docs/14-decisions.md:L193`).
- Security: SQL is trusted, not sanitised; "never pass untrusted input"
  (`OLD:docs/08-export.md:L183-L207`, `OLD:docs/14-decisions.md:L163`).

### Testing

- Per transformer: equality with scikit-learn on the same data
  (`np.allclose`, `atol=1e-10`), NULL cases, edge cases, SQL snapshot, schema
  match, roundtrip `fit -> to_sql -> run -> equals transform`, clone
  (`OLD:docs/13-testing.md:L5-L14`, `OLD:docs/14-decisions.md:L8`,
  `OLD:.claude/skills/test/SKILL.md:L35-L55`: "non-negotiable").
- CI classification tests: for every built-in, `static` implies
  `discover() == {}` and `dynamic` implies non-empty
  (`OLD:docs/03-architecture.md:L499-L526`, `OLD:docs/13-testing.md:L199-L211`).
- Other plans: hypothesis properties, random-pipeline fuzzing, FILTER versus
  physical subset for ten aggregates, a version matrix over Python, DuckDB
  and sqlglot, timing guards, one synthetic 1,000 x 20 Parquet fixture with
  known nulls and correlations (`OLD:docs/13-testing.md:L187-L197`,
  `L314-L371`, `L428-L453`).
- Fixtures are generated in-repo, not downloaded (`L428-L453`).

### Milestones and release plan

- Nine milestones, "realistic" 60-70 weeks; milestones 1-4 critical, "ship
  v0.1.0 fast" to validate the compiler (`OLD:docs/12-milestones.md:L3-L18`,
  `OLD:BACKLOG.md:L157-L160`):
  1 scaffolding; 2 compiler with Imputer, StandardScaler, OneHotEncoder
  matching scikit-learn; 3 composition and data ops; 4 feature engineering,
  selection, auto features; 5 search; 6 analysis; 7 export and polish to
  1.0; 8 Studio free and Pro; 9 Studio Pro completion
  (`OLD:docs/12-milestones.md:L20-L381`, release table `L383-L394`).
- The proof for milestone 2 is exactly one slice with three steps and a
  scikit-learn comparison (`L58-L78`), which resembles the new project's
  3.2 "vertical slice" (inference).
- Process pieces: hierarchical `logging` loggers, a reproducibility table,
  commit and backlog skills (`OLD:docs/12-milestones.md:L459-L526`,
  `OLD:.claude/skills/commit/SKILL.md`, `OLD:.claude/skills/backlog/SKILL.md`).

### Business model

- One repo, one package, MIT. Three tiers: library (free), `sqlearn[studio]`
  free (read-only EDA), and Studio Pro unlocked by a licence key in the same
  package (`OLD:docs/11-business-model.md:L5-L42`, `L261-L303`,
  `OLD:docs/14-decisions.md:L126-L130`).
- Functional rather than numeric limits: free is "explore and understand";
  Pro is "build, generate, export" (pipeline builder, code generation, chart
  customisation, search monitor, session save, project scaffolding,
  notebooks, model fitting from UI) (`OLD:docs/11-business-model.md:L71-L173`,
  `L203-L245`).
- Pricing: one-time $49-99, annual $29, team seats, free for students and
  open-source projects, 14-day trial; decide after Studio ships
  (`L247-L259`).
- Licence key: signed offline with RSA ("no phone-home, no telemetry"),
  `sq.activate`, `sq.trial`, trial state in `~/.sqlearn/trial`
  (`L305-L322`, `OLD:docs/14-decisions.md:L133`, `L165`). The Pro code ships
  in the same wheel, "minified" in the frontend bundle (`L269-L273`).
- Revenue was planned only for versions 1.1 and 1.2, after week 40
  (`OLD:docs/12-milestones.md:L383-L394`).

## Decisions and reasons

The log is `OLD:docs/14-decisions.md` (sections 15-18). I list the ones that
bear on the library core, with the reason given.

- **One base class, not mixins** (#1): "simpler, no historical baggage"
  (`L44`).
- **Auto column routing by `_default_columns`** (#2): removes
  `ColumnTransformer` "for 80% of cases" (`L45`).
- **discover / expressions / output_schema** (#3), static and schema-change
  "auto-detected" (#4, #5): "user doesn't think about it" (`L46-L48`).
- **Layers during fit, one query for transform** (#7): "minimum queries,
  maximum performance" (`L50`).
- **In-memory DuckDB default** (#8) and **numpy output default** (#9)
  (`L51-L52`). Later **eager NumPy with a size warning** (#91): "sklearn
  compat is non-negotiable"; lazy via `__array__` "fragile" (`L137`).
- **Multi-source via ATTACH, not split pipelines** (#17): "one pipeline = one
  engine" (`L60`).
- **All SQL via sqlglot, never strings** (#19) and **Backend protocol in
  phase 1** (#20): "multi-database from day one" (`L62-L63`).
- **Baked for fit/transform/export, self-contained CTE for CV** (#21): "best
  performance in each context, user doesn't choose" (`L64`).
- **Fold column `__sq_fold__`, reserved prefix** (#22) (`L65`).
- **Minimal dependencies: duckdb, sqlglot, numpy** (#28) (`L71`).
- **`y` is a column name** (#93): "SQL-native: target already in the table";
  no `needs_target` flag (`L139`).
- **Three-tier classification** (#93b): trust declarations for our code,
  inspect user code; false static means data corruption, false dynamic costs
  one cheap query (`L140`).
- **Auto-passthrough in `expressions()`** (#102): the silent column drop bug
  (`L150`).
- **`discover_sets()`** (#103): `fetch_one` cannot return DISTINCT
  categories (`L151`).
- **Two-phase discovery for CV** (#104): rare categories vanish from folds
  and the output schema changes (`L152`).
- **Non-mutating `+=`** (#105): notebook re-runs (`L153`).
- **`TransformResult` as a wrapper, not an ndarray subclass** (#106):
  subclassing is fragile across NumPy versions (`L154`).
- **`freeze()`** (#107) and **versioning with SQL hash** (#108): a library
  update must not silently change output (`L155-L156`).
- **`ModelPipeline`: preprocessing JSON, model pickle** (#112) (`L160`).
- **EWM and Deduplicate reclassified static** (#114): structure comes from
  constructor arguments (`L162`).
- **Trust all SQL input** (#115) (`L163`).
- **Three levels of custom steps** (#122), `{col}`/`{param}` templates (#123),
  `_validate_custom` (#124): "the gap between built-ins and writing sqlglot
  ASTs was too wide" (`L170-L172`).
- **`autopipeline()` and `as_code=True` free** (#121): "library users should
  never hit a paywall" (`L169`).
- Supersessions are kept visible: #51 to #52 (Studio separate repo to
  optional extra), #82 to #82b, #83 to #83b, #84 to #84b (separate private
  repo to one repo with licence gating) (`L94-L95`, `L125-L130`).
- Open at the end: frozen pipeline string versus AST, and `Union` with
  branches of different row counts (`L190-L195`, `OLD:BACKLOG.md:L114-L115`).
- Risk register (section 15) names, with mitigations: sqlglot breakage,
  NumPy precision, expression nesting, OneHot explosion, cross-dialect
  correctness, wrong built-in classification ("caught in CI, never at
  runtime"), cross-fold schema inconsistency (Critical), version mismatch on
  load, pickle security (`OLD:docs/14-decisions.md:L5-L34`).

## New against the baseline

The baseline reviews cover `sqlearn_000` and v0.4 only. Where I say "the
baseline is silent" I mean the README summary and the two reviews I skimmed
do not mention it.

- **Fold-aware fit in one scan.** Statistics per fold by `FILTER (WHERE
  fold != k)` inside one query, cross-joined to the data; a test that FILTER
  equals a physical subset for ten aggregates
  (`OLD:docs/03-architecture.md:L1696-L1744`,
  `OLD:docs/13-testing.md:L323-L341`). Directly relevant to the open
  question "can fit be one query" and to model selection (3.3).
- **Two-phase discovery** as a rule for a stable output schema across folds
  (`OLD:docs/03-architecture.md:L1746-L1873`). The baseline has no
  cross-validation story.
- **Scalar and set learning are different query shapes** (`discover` vs
  `discover_sets`), the first batched into one query, the second one query per
  set (`OLD:docs/12-milestones.md:L564-L592`). v0.4 kept this shape
  (`sqlearn-v04/review.md:L54-L57`), so it is inherited, not new to the
  baseline; the reasoning here is the earliest.
- **Baked versus self-contained compilation** as two modes of the same
  composer (`OLD:docs/03-architecture.md:L1696-L1736`). The baseline's
  "one composer" demand fits; this adds a second output mode.
- **Classification proved by CI, not at runtime** for built-ins, with
  both branches tested for conditionally static steps
  (`OLD:docs/03-architecture.md:L499-L582`).
- **Guard against a static step reading learned state**
  (`OLD:docs/03-architecture.md:L1080-L1143`): a precise answer to
  "fit leaked into transform" (see Confirms).
- **Explicit freeze of auto decisions** (`to_explicit`) so thresholds cannot
  drift between versions (`OLD:docs/05-transformers.md:L521-L552`).
- **A serialised pipeline with fitted values and both schemas** as readable
  YAML, plus a SQL hash to detect silent change
  (`OLD:docs/08-export.md:L29-L99`). Bears on the core requirement that a
  pipeline serialises to a file and back.
- **Content-hash dedup of preprocessing** across model trials and a
  materialised feature cache (`OLD:docs/06-model-integration.md:L320-L339`).
- **Pre-aggregation as the EDA design rule**: every chart is a small SQL
  result; the browser never receives raw rows
  (`OLD:docs/07-analysis.md:L349-L369`, `L926-L943`, decision #54 at
  `OLD:docs/14-decisions.md:L97`). Relevant to overview 3.6.
- **Data-quality score, leakage check, per-column audit, missing-data
  diagnosis** as library functions (`OLD:docs/07-analysis.md:L1048-L1558`).
- **A commercial licensing design** inside the open package
  (`OLD:docs/11-business-model.md`). The overview has no commercial plan
  beyond ADR 0004's "paid means a separate package".
- **Studio as a builder that generates code**, a drag-and-drop pipeline
  editor with live Python preview (`OLD:docs/07-analysis.md:L814-L851`).
  It is an early ancestor of the node editor (3.7), but it exports Python
  and YAML rather than serialising a graph that both run (inference).
- **Hand-written knowledge tables** for "which model needs scaling"
  (`OLD:docs/07-analysis.md:L172-L223`): data, not code, but unvalidated.

## Contradicts the baseline

- **Boundary rule.** The baseline says the rule must be "a learning step
  reads a value an earlier step changed". ducklearn's rule is "a boundary
  after any schema-changing dynamic step" (`OLD:docs/04-compiler.md:L190-L193`,
  `OLD:docs/03-architecture.md:L904-L914`). Different, and the wrong one by
  the baseline's test (Imputer then StandardScaler stay in one layer).
- **API names.** The baseline says both attempts renamed scikit-learn's
  methods. ducklearn did not rename `fit`, `transform`, `fit_transform`,
  `get_params`, `set_params` (`OLD:docs/03-architecture.md:L96-L140`). It
  departs elsewhere: `y` is a column name and `fit` takes a source, not
  `X, y`; `Columns` and `Union` rename `ColumnTransformer` and `FeatureUnion`;
  `+` and non-mutating `+=` on steps; author hooks `discover`/`expressions`/
  `query`; output is a wrapper (`OLD:docs/14-decisions.md:L55-L56`, `L136`,
  `L139`, `L154`). Under ADR 0003 each departure needs an ADR.
- **Validation reference.** The baseline says a strong method (exact
  references, measured bounds) was written. ducklearn's reference is
  scikit-learn itself with one fixed `atol=1e-10`
  (`OLD:docs/14-decisions.md:L8`, `OLD:.claude/skills/test/SKILL.md:L52`),
  not exact arithmetic and not measured bounds; "bounds from measurement"
  never appears. So the method was weak here, not strong-but-unenforced.
- **Network use.** The baseline says datasets were downloaded. ducklearn
  uses one synthetic generated fixture
  (`OLD:docs/13-testing.md:L428-L453`). (But its Studio and `attach` examples
  use S3 and Postgres: `OLD:docs/02-api-design.md:L441-L458`.)
- **Dependencies.** The baseline project allows one runtime dependency
  (ADR 0005). ducklearn needs `duckdb`, `sqlglot`, `numpy`
  (`OLD:docs/10-project-structure.md:L191-L198`), and a studio extra of eight
  packages including `cryptography` for licence checks (`L208-L217`). Note
  the library never uses NumPy except as output type (inference).
- **Licence and commerce.** Contradicts ADR 0004 (paid features in a separate
  package) and the overview's constraint on licensing
  (`OLD:docs/11-business-model.md:L261-L303`).
- **Python floor.** 3.10 (`OLD:CLAUDE.md:L158`,
  `OLD:docs/10-project-structure.md:L193`) against 3.12 (ADR 0007).
- **Scope.** The overview defers modelling and search to 3.3 after a
  vertical slice; ducklearn treats search, analysis and Studio as part of one
  roadmap with the library, and puts preprocessing as "100% of what happens
  before a model", leaving models out (`OLD:docs/01-overview.md:L93-L105`).
  The new project does include models (overview 3.3).

## Confirms the baseline

- Fit statistics come from the raw input: Layer 0 computes the scaler mean
  from `FROM data` beside the imputer's, and the audit example shows the
  scaler using the raw mean 65,420 after imputing with the median
  (`OLD:docs/04-compiler.md:L214-L226`,
  `OLD:docs/03-architecture.md:L1495-L1505`,
  `OLD:docs/07-analysis.md:L1208-L1210`). The bug is in the first design.
- Fit ignores row-changing steps: `Filter` is "static" and "no schema
  change", the aggregates read the source table
  (`OLD:docs/03-architecture.md:L1246`, `OLD:docs/05-transformers.md:L716`,
  `OLD:docs/04-compiler.md:L218-L222`) (inference; v0.4 shows the same,
  `sqlearn-v04/review.md:L64-L67`).
- Same lineage as v0.4: classification, `step__param` keys, layers cut after
  a step that learns and changes schema, `expressions()` returning only
  changed columns (`sqlearn-v04/review.md:L54-L58`, `L246-L252`).
- No staged fit as one `WITH` query (baseline: possible on DuckDB 2.0.0):
  ducklearn runs one batched query per layer and puts a temp view between
  layers (`OLD:docs/04-compiler.md:L214-L236`), so the idea was never tried.
- Learned state as Python values inlined as literals, saved to a file; tables
  never considered (`OLD:docs/03-architecture.md:L1507-L1513`,
  `OLD:docs/08-export.md:L61-L99`).
- `__`-split keys: `column__stat` built and parsed by convention, with a
  warning when `__` is missing (`OLD:docs/03-architecture.md:L1037-L1044`);
  any column name containing `__` would break it (inference).
- Float literals never checked: values are inserted with
  `exp.Literal.number(mean)` or `str(value)`; NaN, infinity and NULL results
  are not addressed (`OLD:docs/03-architecture.md:L1553`, `L341`) (inference).
- sqlglot from the start, version risk named, portability tested only by
  "parses without error" (`OLD:docs/14-decisions.md:L7`,
  `OLD:docs/13-testing.md:L314-L322`).
- Process outgrew product: 14 documents and 132 decisions, no code, 26 plan
  review items, plan duplication admitted (`OLD:CLAUDE.md:L167`,
  `OLD:BACKLOG.md:L145-L162`).
- Skills and the commit template carry AI attribution
  (`OLD:.claude/skills/commit/SKILL.md:L150`), contrary to this repository's
  rule; not to be copied.

## Worth keeping

- **The CI-proved declaration** for static versus dynamic, with "any doubt
  means dynamic" for user code. Cheap, and it answers a baseline failure
  (spec said static, runtime said dynamic)
  (`OLD:docs/03-architecture.md:L499-L526`).
- **Runtime guard for hidden state reads** (`_FrozenEmptyParams`): turns the
  "fit leaked into transform" class into an error at the first use
  (`OLD:docs/03-architecture.md:L1086-L1122`).
- **`FILTER`-per-fold statistics**, plus the FILTER-equals-subset test, as a
  way to cross-validate with one scan. Needs recheck on current DuckDB
  (`OLD:docs/13-testing.md:L323-L341`).
- **Stable output schema across folds** as a stated invariant, even if the
  mechanism changes (`OLD:docs/03-architecture.md:L1859-L1861`).
- **Separate scalar and set learning** with batched scalars
  (`OLD:docs/12-milestones.md:L564-L592`).
- **Auto-passthrough in `expressions()`** and an explicit collision error
  (`OLD:docs/03-architecture.md:L154-L192`).
- **A frozen, hashed, schema-validated deployment artefact**, and SQL hash in
  the saved format (`OLD:docs/08-export.md:L29-L181`).
- **`{col}`/`{param}` SQL templates** as the low-effort level for custom
  steps, parsed at creation (`OLD:docs/02-api-design.md:L603-L741`).
- **Readable, versioned config with fitted values and both schemas**
  (`OLD:docs/08-export.md:L61-L99`), useful for the graph-serialisation
  requirement of 3.2.
- **Pre-aggregation rule for EDA** (`OLD:docs/07-analysis.md:L349-L369`).
- **Explicit opt-in for anything automatic**, with a freeze step
  (`OLD:docs/01-overview.md:L11-L64`).
- **Check lists worth reusing as test ideas**: the 13-testing sections on
  null handling, edge cases, passthrough and thread guard.
- **Risks and cautions to avoid**: the `Union` same-row-count assumption
  (`OLD:docs/04-compiler.md:L149`), the doc inconsistencies below, and a
  hand-tuned score table for "data quality" with no validation
  (`OLD:docs/07-analysis.md:L1101-L1113`).

Internal inconsistencies noticed (all inference; show the document was never
reconciled): `TransformResult` is an `__array__` wrapper
(`OLD:docs/02-api-design.md:L358-L361`) but the resolved-decisions text says
"No `__array__` protocol magic" (`OLD:docs/14-decisions.md:L215`);
OneHotEncoder is dense by default (`OLD:docs/05-transformers.md:L61`,
`OLD:docs/14-decisions.md:L237-L238`) yet "sparse by default" in
`OLD:docs/10-project-structure.md:L46` and `OLD:docs/07-analysis.md:L313`;
EWM and Deduplicate appear under "Declared Dynamic" with value static
(`OLD:docs/03-architecture.md:L1293-L1294`); ECharts is 135 KB and 500 KB
(`OLD:docs/07-analysis.md:L538`, `OLD:docs/10-project-structure.md:L156`); the
Imputer median is written as `Avg(...)` in a worked flow
(`OLD:docs/03-architecture.md:L1487`).

## Files covered

- [x] `OLD:CLAUDE.md`: agent guide; summary, core concepts, tiers, key
  decisions, doc map, "pre-implementation".
- [x] `OLD:BACKLOG.md`: nine milestones as tick lists, open questions Q2/Q3,
  ideas, 26 plan-review items, 60-70 week estimate.
- [x] `OLD:IDEAS.md`: empty template (no content beyond headings).
- [x] `OLD:docs/01-overview.md`: philosophy, what it replaces and does not,
  data formats, naming.
- [x] `OLD:docs/02-api-design.md`: columns, pipelines, operators, inputs,
  outputs, backend, merge/concat/Lookup, three-level custom steps, validation.
- [x] `OLD:docs/03-architecture.md`: base class, classification tiers,
  fit flow, interfaces, schema, backend, baked vs self-contained, two-phase
  discovery, fold column.
- [x] `OLD:docs/04-compiler.md`: expression composition, CTE rules, Columns
  and Union compilation, fit layers, memory claims.
- [x] `OLD:docs/05-transformers.md`: catalogue of steps (preprocessing,
  encoders, features, selection, auto, outliers, target, data ops).
- [x] `OLD:docs/06-model-integration.md`: ModelPipeline, Search, multi-fidelity,
  dedup, Optuna paths, cross_validate, split, warm start.
- [x] `OLD:docs/07-analysis.md`: profile/analyze/recommend/autopipeline,
  Studio stack and UX, quality, check, audit, missing, importance, warnings.
- [x] `OLD:docs/08-export.md`: export formats, versioning, YAML, freeze,
  security model.
- [x] `OLD:docs/09-error-handling.md`: error classes, unseen category
  policy, NULL policy, drift detection.
- [x] `OLD:docs/10-project-structure.md`: package tree, extension points,
  dependency lists.
- [x] `OLD:docs/11-business-model.md`: three tiers, funnel, pricing, licence
  key, one-repo rationale.
- [x] `OLD:docs/12-milestones.md`: nine milestones, release table, non-goals,
  logging, reproducibility, graceful degradation, discover_sets execution.
- [x] `OLD:docs/13-testing.md`: per-area test lists, classification tests,
  CV tests, FILTER tests, version matrix, fixture.
- [x] `OLD:docs/14-decisions.md`: risks (15), decisions 1-132 (16), open
  questions (17), resolved decisions (18).
- [x] `OLD:.claude/settings.local.json`: allows web search and fetch for
  github.com, duckdb.org, code.claude.com; nothing else.
- [x] `OLD:.claude/skills/backlog/SKILL.md`: how to tick the backlog and
  record bugs and ideas.
- [x] `OLD:.claude/skills/commit/SKILL.md`: semantic-commit protocol; its
  template adds a Co-Authored-By trailer (not to be copied here).
- [x] `OLD:.claude/skills/test/SKILL.md`: test structure and the five
  mandatory tests per step, sklearn equality "non-negotiable".
- [x] `OLD:.claude/skills/transformer/SKILL.md`: how to write a Level 3 step,
  folder map, validation rules.

Not read: `OLD:.DS_Store` (empty, 0 lines). No file hung or failed.

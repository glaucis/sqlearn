---
type: note
tags: [sqlearn, documentation, sklearn-compat, column-routing, pipeline, design]
summary: "Review of the sqlearn-desktop user docs: API as documented, sklearn departures, column routing, and documentation drift lessons."
related: [docs/questions/archived/earlier-attempts/tomosius-sqlearn/notes/D-docs.md]
mdindex: [type=edb465, tags=cac0ac, summary=88cace]
---
# Batch D: user docs of `sqlearn-desktop`

Source: `OLD` is `sqlearn-desktop` under ROOT (the first real build,
GitHub `Tomosius/sqlearn`, Mar 13 - Apr 9 2026). Every citation is
`OLD:docs/<path>:Lnn`, relative to `OLD/docs/`. Inference is marked
"(inference)". Nothing was run; no `.env` was opened; `site/` was ignored; no
file failed to read.

## Summary

- The docs promise a scikit-learn-shaped surface (`Pipeline`, `fit`,
  `transform`, `fit_transform`, `get_params`, `clone`,
  `get_feature_names_out`) but change the data contract: `fit` takes a path,
  table, SQL string or DataFrame, and `y` is a column name, not an array
  (`OLD:docs/guide/design-decisions.md:260-291`). Same rename-then-bridge
  pattern as the baseline, in a different place.
- Column routing is the headline feature: each transformer carries
  `_default_columns` (`numeric`, `categorical`, `temporal`, `all`, `None`),
  resolved against the DuckDB schema at fit time, with `columns=` as a name
  list, a type string or a composable selector (`|`, `&`, `~`, `-`)
  (`OLD:docs/guide/column-routing.md:8-121`).
- Fit is a "layered" compiler: aggregates of all dynamic steps in a layer are
  batched into one query on the raw layer input. The guide's own worked
  example hides that this makes `Impute` then `Scale` learn from un-imputed
  data (see "Contradicts"). Confirms the baseline's main defect.
- The specs under `superpowers/` are unusually precise about the contracts
  (`discover`, `discover_sets`, `expressions`, `query`, `output_schema`,
  `params_`, `sets_`, three-tier static/dynamic classification) and
  admit one fit-time hazard in a `known_risks` field, but only for
  static-into-dynamic inlining, not dynamic-into-dynamic
  (`OLD:docs/superpowers/specs/2026-03-17-system-reference-design.md:121-123`).
- Learned state is `params_` (scalars, keys `"{col}__{stat}"`) and `sets_`
  (lists of row dicts), set on each step by `Pipeline.fit`. Same shape as the
  baseline; same failures (keys split on `__`, no "learned NULL" versus "not
  fitted" distinction beyond `_fitted`, nothing about tables).
- SQL representation is sqlglot ASTs only, "never raw strings", with a
  `custom()` template layer that parses strings into ASTs at creation. Costs
  are acknowledged in the docs (verbosity) but not the baseline's version-pin
  and dialect-drift costs.
- Validation is described as strong (golden SQL files, AST shape tests, sklearn
  equivalence, `known_risks`) but the integration-test spec compares against
  scikit-learn only transformer by transformer, never the composed `Imputer` +
  `StandardScaler` pipeline, which is the case that differs
  (`OLD:docs/superpowers/archive/specs/2026-03-15-integration-tests-design.md:13-35`).
- The hand-written numbers in the docs drift from each other and from the
  mechanism (different `std` for the same data in two tutorials; an example
  `Expression` placed before `Imputer` shows imputed inputs). Docs whose
  outputs are not generated rot; this is the clearest lesson for the new
  site.
- Worth reusing for the site: tabbed "Python / Generated SQL" pairs, one API
  page per component (formula, SQL, then docstring), a gallery of
  self-contained examples with inline data, a side-by-side comparison
  tutorial, and a "What we chose / Why / Alternatives / Trade-offs" format
  for decisions.
- Process echo of the baseline: 91 docs files, 23 spec and plan files of
  about 600 KB, a reorganisation spec (Mar 17) to cope with 46,000 lines of
  documentation, and a DuckDB "project database" plan for agents, all before
  the library reached v0.4.

## API as documented

Entry points and signatures, all from the docs; none verified against code.

**Pipeline.**

- Three step formats: bare list (auto-named by class: `imputer`,
  `standardscaler`), `(name, transformer)` tuples, and a dict
  (`OLD:docs/guide/concepts.md:63-88`). Access: `pipe.named_steps["scale"]`,
  `pipe.steps[0][1]`, `pipe["name"]` (the last from the naming plan,
  `OLD:docs/superpowers/plans/2026-03-18-pipeline-step-naming.md:1-12`).
- `fit(data, y=None, *, backend=None)` returns `self`;
  `transform(data, *, backend=None)`; `fit_transform(data, y=None, ...)` is
  `fit` then `transform`, "single-pass optimisation deferred"
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:257-271`).
- `to_sql(*, dialect="duckdb", table="__input__")` needs no backend and
  returns `ast.sql(dialect=...)`
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:273-294`);
  `__input__` is a placeholder the user replaces
  (`OLD:docs/examples/full-pipeline.md` Step 5).
- `get_feature_names_out()`, `is_fitted` (a plain property, not trailing
  underscore scanning), `clone()`, `copy()`, context manager that closes only
  a backend the pipeline created
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:375-407`).
- `+` and `+=` build a new flat Pipeline of cloned steps; `+=` never mutates;
  a user-given name collision raises `InvalidStepError`, auto names get a
  suffix (`OLD:docs/api/operators.md:56-114`). `|` for parallel composition
  was explicitly rejected (`OLD:docs/guide/design-decisions.md:355-362`).
- Promised later and not specified: `freeze()` / `FrozenPipeline`,
  `detect_drift`, `validate`, `audit`, `null_policy`, `sq.Search(n_jobs=)`,
  `to_dbt`, `to_config`
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:16-18`;
  `OLD:docs/guide/design-decisions.md:813`).

**Output formats.** Documented default is a numpy `float64` array
(`OLD:docs/tutorials/basic-pipeline.md:141-146`). The guide additionally
promises a `TransformResult` wrapper (columns, dtypes, `.sql`, `__array__`),
`out="arrow" | "pandas" | "polars" | "relation"`, `batch_size`, `dtype` and
`exclude_target=True`
(`OLD:docs/guide/design-decisions.md:574-644`;
`OLD:docs/superpowers/archive/specs/2026-03-14-transformer-design.md:343-347`).
The spec for the actually built Pipeline defers all of these
(`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:16`,
`:459-462`). Rationale given for a wrapper over a numpy subclass: subclass
metadata is lost by slicing and `np.concatenate`
(`OLD:docs/guide/design-decisions.md:618-626`).

**Model integration.** Only a promise: because the result implements
`__array__`, "sklearn, XGBoost, LightGBM accept it" and `model.fit(result, y)`
works (`OLD:docs/guide/design-decisions.md:609-615`). No docs page shows a model
being fitted or a sklearn `Pipeline` containing a sqlearn step. `Search` and
cross-validation exist only as planning notes, with a "fold column" convention
via temp views (`OLD:docs/guide/design-decisions.md:819-841`;
`OLD:docs/superpowers/specs/2026-03-17-documentation-reorganization-design.md:151-154`).
Inference: the model-integration story stops at "numpy in, numpy out".

**Column routing.**

- `_default_columns`: `StandardScaler`, `MinMaxScaler`, `RobustScaler`
  numeric; `OneHotEncoder`, `OrdinalEncoder` categorical; `Imputer` all;
  `Rename`, `Cast` none (explicit `columns=` required)
  (`OLD:docs/guide/column-routing.md:13-22`).
- Type strings `numeric`, `categorical`, `temporal`, `boolean`, `all`
  (`OLD:docs/guide/column-routing.md:71`); selectors `numeric()`,
  `categorical()`, `temporal()`, `boolean()`, `all_columns()`,
  `columns("a","b")`, `matching("price_*")` (glob, not regex),
  `dtype("DECIMAL")` (`OLD:docs/guide/column-routing.md:81-92`;
  `OLD:docs/superpowers/archive/specs/2026-03-14-schema-design.md:146-163`).
  Selectors are lazy and resolved at fit time, so one pipeline definition serves
  tables with different schemas (`OLD:docs/guide/column-routing.md:123-126`).
- `Columns([(name, transformer, columns), ...], remainder="drop"|"passthrough")`
  replaces `ColumnTransformer`; overlap raises `SchemaError`; default remainder
  is drop, as in scikit-learn (`OLD:docs/guide/column-routing.md:129-180`).
  `Union([(name, transformer), ...])` replaces `FeatureUnion`, prefixing each
  branch's outputs with the branch name
  (`OLD:docs/guide/column-routing.md:210-253`).
- Fit-time warnings for likely identifier columns, because auto routing "will
  scale that ID" (`OLD:docs/guide/design-decisions.md:160-164`).
- Types come from `DESCRIBE`, mapped by frozensets to numeric / categorical /
  temporal / boolean / other, parameters stripped (`DECIMAL(18,3)` to `DECIMAL`)
  (`OLD:docs/superpowers/archive/specs/2026-03-14-schema-design.md:83-127`).

**Transformer contract (single base class, no mixins).**
`__init__(*, columns=None)`; class attributes `_default_columns`,
`_classification`; override points `discover` (scalar aggregates as sqlglot
nodes, `{col}__{stat}` keys), `discover_sets` (multi-row queries),
`expressions(columns, exprs)` (only the modified columns; the base class passes
the rest through), `query(input_query)` (window, join, `Rename`, selection
steps) and `output_schema(schema)`
(`OLD:docs/superpowers/archive/specs/2026-03-14-transformer-design.md:71-187`).
Extras: `get_params` introspecting the subclass `__init__` signature,
`set_params`, `_repr_html_`, `__sklearn_is_fitted__`, pickling that drops the
DuckDB connection, a thread and process owner guard
(`OLD:docs/superpowers/archive/specs/2026-03-14-transformer-design.md:247-360`).
Later additions as plans: `suffix=` (output next to the original) and
`condition=` (apply to rows matching a SQL WHERE: `CASE WHEN` around the
expression, `FILTER (WHERE ...)` on the learning aggregates)
(`OLD:docs/superpowers/plans/2026-03-18-suffix-parameter.md:1-9`;
`OLD:docs/superpowers/plans/2026-03-18-condition-parameter.md:1-9`).

**Catalogue (from `api/index.md`).** Scalers: Standard, MinMax, Robust,
MaxAbs, Normalizer (row-wise, static). Encoders: OneHot, Ordinal, Hash
(static), Frequency, Auto. Imputer (`mean|median|most_frequent|constant|auto`,
per-column dict). Feature engineering: arithmetic (Log, Sqrt, Power, Clip),
string, datetime (DateParts, DateDiff, IsWeekend, Quarter), window (Lag,
Lead, RollingMean, RollingStd, Rank, RowNumber), OutlierHandler,
TargetTransform, Auto{Datetime,Numeric,Features} with `to_explicit()`. Feature
selection: Drop, DropCorrelated, VarianceThreshold, SelectKBest. Data ops:
Rename, Cast, Filter, Sample, Deduplicate, Lookup (mid-pipeline JOIN), and the
functions `merge()` and `concat()` that return a view name used as input
(`OLD:docs/api/index.md:32-95`; `OLD:docs/api/merge.md:19-21`).

**Custom transformers, three levels.** `sq.Expression("a * b AS c")` (static,
adds a column, parsed at creation); `sq.custom("LN({col}+1)", columns=...,
learn={"mean": "AVG({col})"}, mode="per_column"|"combine")`; subclass
`sq.Transformer` (`OLD:docs/guide/custom-transformers.md:6-10`,
`:89-227`). Custom classes are checked at first fit (five checks: AST not
Python values, `expressions` returns ASTs, new columns declared in
`output_schema`, no undeclared params, classification matches) and cached
(`OLD:docs/guide/design-decisions.md:689-732`).

**Follows scikit-learn?** Partly, and by design departs where the data model
differs.

- Kept: `fit` returns self, `fit_transform`, `get_params` / `set_params` /
  `clone`, `(name, step)` tuples, `named_steps`, `get_feature_names_out`,
  `Pipeline`, population std to match `StandardScaler`, `handle_unknown`
  vocabulary in `OrdinalEncoder`, `strategy` names in `Imputer`.
- Replaced: `ColumnTransformer` by `Columns` and by automatic routing,
  `FeatureUnion` by `Union`, `X, y` arrays by a data source plus `y="col"`,
  trailing-underscore fitted attributes by `params_` / `sets_` / `is_fitted`,
  mixins by one base class, fitted attributes `mean_`, `scale_` by dict
  lookups (`OLD:docs/tutorials/sklearn-comparison.md:294-305`).
- The docs call the departure deliberate: "sklearn's class hierarchy is a
  historical accident" (`OLD:docs/guide/design-decisions.md:72-79`).
- Bridge back: `__array__` result, `__sklearn_is_fitted__`, `get_params`.
  No evidence the docs ever show `sklearn.base.clone`, `GridSearchCV` or
  `sklearn.pipeline.Pipeline` accepting a sqlearn step (inference from the
  absence).

## Specs and plans (superpowers)

Nine specs and eleven plans under `archive/` plus two specs and seven plans
active, all dated Mar 14-18 2026. Specs were read in full; plans by task
headings and by the code blocks that decide behaviour.

**Fit.**

- Three phases: `plan_fit` (resolve columns, classify, group into layers),
  `build_fit_queries` (batch scalar aggregates of a layer into one `SELECT`,
  `discover_sets` queries separately), `compose_transform` (nest expressions)
  (`OLD:docs/superpowers/archive/specs/2026-03-14-compiler-design.md:6-14`).
- Layer boundary only after a step that is both dynamic and schema-changing;
  a static schema change never splits a layer
  (`OLD:docs/superpowers/archive/specs/2026-03-14-compiler-design.md:62-77`).
  After a layer, the pipeline builds a temp view from `compose_transform` over
  that layer's steps and fits the next layer against it
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:175-198`).
- Inlining: only **static** steps are composed into later steps' aggregates
  ("`AVG(LN(price))`"); the plan's code updates `running_exprs` only in the
  static branch
  (`OLD:docs/superpowers/archive/specs/2026-03-14-compiler-design.md:131-135`;
  `OLD:docs/superpowers/archive/plans/2026-03-14-compiler.md:1561-1569`). A
  dynamic step's own expression is never carried into the next step's aggregate
  inside the same layer. (This is the direct cause; see Contradicts.)
- Design principle in the spec: "Compiler produces ASTs, never executes";
  execution and temp views live in `Pipeline`
  (`OLD:docs/superpowers/archive/specs/2026-03-14-compiler-design.md:300-307`).
- The plan swallows exceptions from `discover()` (`except Exception:
  discover_result = {}`) and passes `y_column` as `None`
  (`OLD:docs/superpowers/archive/plans/2026-03-14-compiler.md:1573-1580`); plan
  code, may differ from what shipped (inference).
- Safety rule for classification: "false static = data corruption; false
  dynamic = one extra cheap query", with three tiers (built-in trusted,
  custom declared verified once, custom undeclared inspected every fit)
  (`OLD:docs/superpowers/archive/specs/2026-03-14-compiler-design.md:35-41`).

**Learned state.**

- `params_: dict[str, Any] | None` and `sets_: dict[str, list[dict]] | None`,
  both `None` until fit, plus `columns_`, `input_schema_`, `output_schema_`,
  `_fitted` bool
  (`OLD:docs/superpowers/archive/specs/2026-03-14-transformer-design.md:60-69`).
- Distribution of results back to steps is by alias mapping
  `__agg_{i}_{col}__{stat}` and, for sets, `f"{step_index}_{set_name}"` split
  with `split("_", 1)`
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:142-162`).
  Both are string-keyed conventions, the baseline's "keys split on `__`" failure
  again.
- Literals enter SQL through `exp.Literal.number(float)`
  (`OLD:docs/guide/custom-transformers.md:275-279`); nothing mentions float
  round-trip.
- Persistence: `pickle` with the connection nulled; temp views are session
  scoped, "fitted parameters (temp tables, views) are lost when the process
  exits" in memory mode (`OLD:docs/guide/design-decisions.md:568-571`). No JSON
  save format appears in the docs. `to_sql()` after fit is the deployment
  artefact. `freeze()` is promised, unspecified.
- Data safety: the backend protocol has only reads (`SELECT`, `DESCRIBE`); all
  intermediate state is a temp view
  (`OLD:docs/guide/design-decisions.md:819-841`). Fold columns for
  cross-validation are the same idea.

**SQL representation.**

- sqlglot ASTs everywhere; strings only through `Expression` / `custom`, which
  substitute a dummy column and parse at creation, then replace
  `Column("__col__")` nodes by the composed `exprs[col]`
  (`OLD:docs/superpowers/archive/specs/2026-03-15-custom-transformers-design.md:113-127`).
- Composition by nesting, CTE promotion when nesting depth exceeds 8 ("chosen
  empirically", threshold configurable) or when a step overrides `query()`
  (`OLD:docs/guide/design-decisions.md:403-414`).
- Review fixes on Mar 16 show what the AST approach cost: bare
  `exp.Column(this=col)` did not quote identifiers so columns named `order`,
  `group`, `select` produced invalid SQL; shared AST nodes in `Normalizer`;
  `exp.Anonymous` for `MEDIAN`, `LAG`; `Expression` output type hard-coded
  `VARCHAR` then changed to `DOUBLE`
  (`OLD:docs/superpowers/archive/plans/2026-03-16-codebase-review-fixes.md:70-110`;
  `OLD:docs/superpowers/archive/specs/2026-03-15-custom-transformers-design.md:38`).
- Fit-time SQL is built from the same nodes but executed through a transpile
  to DuckDB; `DESCRIBE` is raw SQL ("an implementation detail")
  (`OLD:docs/superpowers/archive/specs/2026-03-14-backend-io-design.md:62`).

**Validation.**

- Test pyramid: sklearn equivalence at `rtol=1e-6`, golden `.sql` snapshots
  updated by `--update-snapshots`, inline pattern assertions, AST structure
  tests, plus mock-transformer unit tests
  (`OLD:docs/superpowers/archive/specs/2026-03-15-integration-tests-design.md:11-72`).
- Equivalence rows cover single transformers on 7-row hand data; the
  Imputer-plus-Scaler case appears only as a snapshot and an AST-shape test
  (`OLD:docs/superpowers/archive/specs/2026-03-15-integration-tests-design.md:46-47`,
  `:70`). Shape, not value (inference).
- `known_risks` and `cv_safe` fields in a YAML system reference, "primary
  output of correctness audits", with the rule that a risk is removed only
  when the fix is verified
  (`OLD:docs/superpowers/specs/2026-03-17-system-reference-design.md:147-156`).
- Error hierarchy: `SQLearnError` root; `NotFittedError`, `SchemaError`
  (`MissingColumnError`), `FitError`, `CompilationError`, `UnseenCategoryError`,
  `ClassificationError`, `StaticViolationError`, `FrozenError`,
  `InvalidStepError`, `ThreadSafetyError`, `ProFeatureError` (licence-gated)
  (`OLD:docs/superpowers/archive/specs/2026-03-14-errors-design.md:10-26`).

**Process specs.** Documentation reorganisation (112 files, 46,000 lines into
`reference/` YAML, `design/` prose, `planning/` future work, an `INDEX.yaml`
master lookup, "move, don't rewrite", 100-400 lines per file, hard cap 600)
(`OLD:docs/superpowers/specs/2026-03-17-documentation-reorganization-design.md:7-31`);
skill consolidation (32 marketplace skills to 9 custom); a project database in
DuckDB with an MCP server
(`OLD:docs/superpowers/plans/2026-03-18-project-database.md:14-40`). It says
public `docs/` are "fine as-is" and out of scope
(`OLD:docs/superpowers/specs/2026-03-17-documentation-reorganization-design.md:29`).

## Documentation structure worth reusing

The public site is MkDocs Material with mkdocstrings, MathJax, tabs and
abbreviations (`OLD:docs/javascripts/mathjax.js`,
`OLD:docs/includes/abbreviations.md`). The new project uses Sphinx (ADR 0009),
so reuse the shape, not the plumbing.

- **Landing in three beats:** one `Python` and `Generated SQL` tab pair, a
  problem/sklearn/sqlearn comparison table, then a feature list
  (`OLD:docs/index.md:9-52`). For a learning site, the tab pair maps to
  "code, what ran underneath".
- **Getting started as a tour:** first pipeline, then one section per
  transformer with the SQL beside it, then composition, then custom, then
  routing (`OLD:docs/getting-started.md`).
- **Guide in fixed order:** concepts (mental model), compiler (trace of one
  example), column routing, custom transformers
  (`OLD:docs/guide/index.md:9-24`). Ends each page with "key takeaways".
- **Decisions page** per choice in a fixed template: What we chose, Why,
  Alternatives considered, Trade-offs
  (`OLD:docs/guide/design-decisions.md:14-61`). Same intent as the new
  project's ADRs, readable by users.
- **API page per component:** a short prose, the formula in LaTeX, the SQL it
  produces, admonitions for "when to use" and edge cases (constant column gives
  `NULL`), then the auto-generated docstring
  (`OLD:docs/api/standard-scaler.md:3-25`). Pages for pure-docstring modules are
  three lines (`OLD:docs/api/pipeline.md`).
- **Examples gallery:** one page per family, each example self-contained with
  inline DuckDB `VALUES` data, building a pipeline and printing `to_sql()`
  (`OLD:docs/examples/index.md:1-45`).
- **Tutorials:** "Your First Pipeline" (seven numbered steps, data created
  inline, inspect `params_`), "Custom Transformers" (levels 1-3), and
  "sqlearn vs sklearn" (same task twice, an assertion that outputs agree,
  a differences table, a "when to use which" table)
  (`OLD:docs/tutorials/sklearn-comparison.md:294-331`). The comparison table is
  the best single teaching device in the set.
- **Warnings to carry over:** every number in these pages was typed by hand
  and several are wrong or inconsistent; use executed examples (doctest or
  a build step that runs them). The API index links four pages that do not
  exist (`auto-encoder.md`, `auto-datetime.md`, `auto-numeric.md`, and the
  `AutoFeatures` page lives only under `examples/`)
  (`OLD:docs/api/index.md:50,68-70`). Link-check the build.
- **For the learning site (inference):** nothing here teaches machine
  learning; the tutorials teach the library. The reusable part is the
  discipline: self-contained data, show the generated artefact, then compare
  with the reference tool.

## New against the baseline

- The docs, not the code, show the user-visible price of the "SQL-native" API
  choice: `y` as a column name and `Pipeline.fit(path)` change the scikit-learn
  call shape; target-aware steps (`SelectKBest`, `TargetEncoder`,
  `TargetTransform`) depend on it. ADR 0003 stands, but this is the departure
  to weigh (`OLD:docs/guide/design-decisions.md:260-291`).
- Automatic type-based routing as the default, with `Columns` as the escape
  hatch, and a stated reason: schema comes from the database, so there is "no
  ambiguity" (`OLD:docs/guide/design-decisions.md:149-151`). The baseline has
  no equivalent evidence. The weak point the docs name themselves is integer
  identifier columns (`:160-164`).
- A fit with layers and a stated cost model: number of fit queries is the
  number of layers, "typically 1-3", not the number of steps
  (`OLD:docs/guide/design-decisions.md:460-468`). Useful as the baseline for
  the fit-execution question; not a correct boundary rule (see below).
- Static versus dynamic as a first-class classification, with a tier model for
  custom code and a "if in doubt, dynamic" safety rule. Neither earlier
  attempt documented this; it maps to "steps that need fit" in the new
  project.
- `output_schema()` as a required declaration for any step that adds or
  removes columns, enforced by a first-fit check with a copy-paste fix in the
  error message (`OLD:docs/guide/design-decisions.md:709-714`). Auto
  passthrough of unmentioned columns removes the commonest custom-step bug
  (`:756-764`).
- `condition=` and `suffix=` as base-class parameters: conditional transform via
  `CASE WHEN` on the output and `FILTER (WHERE ...)` on the learning aggregates,
  which is what keeps the learned statistic consistent with the rows transformed
  (`OLD:docs/superpowers/plans/2026-03-18-condition-parameter.md:7`).
- Auto-feature steps with `to_explicit()`: learn a decision, freeze it into
  explicit parameters (`OLD:docs/examples/auto-features.md` end). A reusable
  pattern for "learned choices become parameters".
- `merge()` / `concat()` as functions that register a view and return its
  name, and `Lookup` as a mid-pipeline JOIN step
  (`OLD:docs/api/merge.md:19-21`, `OLD:docs/api/lookup.md:21-24`). Joins as
  steps were never in the baseline.
- Thread rule: one pipeline per connection, guard raises and points to
  `clone()`, because in-memory DuckDB temp state is per connection
  (`OLD:docs/guide/design-decisions.md:790-799`).
- The project's own reaction to documentation growth: a 112-file, 46,000-line
  corpus reorganised by "reference / design / planning" with a master index
  (`OLD:docs/superpowers/specs/2026-03-17-documentation-reorganization-design.md:9-16`).
  Evidence for "plans and standards outgrew the product" with numbers.

## Contradicts the baseline

- **Documented fit is not a staged fit, and the docs hide it.** The baseline
  says the boundary rule must be "a learning step reads a value an earlier
  step changed". Here the boundary is "dynamic and schema-changing", so
  `Imputer` then `StandardScaler` (same layer) batches
  `AVG(price), STDDEV_POP(price)` on the raw table. Yet the guide's example
  shows `std = 0.8165` for `price = [10, NULL, 8]`
  (`OLD:docs/guide/compiler.md:31-37`, `:165-166`). The population std of the
  raw non-null values is 1.0; 0.8165 is the std of `[10, 9, 8]`, the imputed
  data (arithmetic mine). So the doc shows the answer a correct staged fit
  would give while the mechanism it describes (`:133-149`) produces another
  (inference). The tutorial comment also says the scaler works "using filled
  values" (`OLD:docs/getting-started.md:123`, `OLD:docs/guide/compiler.md:119`).
  The behaviour depends on step order (Imputer, OneHot, Scaler gets the
  imputed scaler stats via the temp view; Imputer, Scaler does not,
  `OLD:docs/guide/compiler.md:92-101`).
- **Output is not consistently numpy.** The baseline implied a plain array
  contract. The guide promises a `TransformResult` with an `__array__`
  protocol and an `out=` family; the built spec returns bare numpy and defers
  the rest (see API above).
- **Step naming:** the spec of Mar 15 auto-names `step_00`; the docs and a Mar
  18 plan use class-based names
  (`OLD:docs/superpowers/archive/specs/2026-03-15-pipeline-design.md:56` against
  `OLD:docs/guide/concepts.md:68`). The plan supersedes the spec.
- **Thread error type:** `RuntimeError` in the guide message
  (`OLD:docs/guide/design-decisions.md:785`) against `ThreadSafetyError` in the
  errors spec
  (`OLD:docs/superpowers/archive/specs/2026-03-14-errors-design.md:81`); changed
  by the Mar 16 review, docs not updated.
- **Imputer default:** `auto` means median for numeric in `getting-started.md`,
  `examples/imputer.md` and the tutorial, mean in `api/imputer.md`
  (`OLD:docs/getting-started.md:72-74` against `OLD:docs/api/imputer.md:24-26`).
  A review task fixed only the first
  (`OLD:docs/superpowers/archive/plans/2026-03-16-codebase-review-fixes.md:566-596`).
- **`Columns` signature:** list of `(name, transformer, columns)` triples in
  the guide and API page (`OLD:docs/guide/column-routing.md:135-142`), a dict
  `{"revenue": RobustScaler(), ...}` in design decisions
  (`OLD:docs/guide/design-decisions.md:169-173`, `:379-384`).
- **Target in the output:** design decisions say the target is excluded from
  `transform()` by default, `exclude_target=False` to keep it
  (`OLD:docs/guide/design-decisions.md:273-275`); the tutorial fits
  `y="has_garage"`, then lists `has_garage` as "imputed and standardized"
  among 7 output columns (`OLD:docs/tutorials/basic-pipeline.md:152-158`), and
  the full pipeline example scales `revenue`, its `y`
  (`OLD:docs/examples/full-pipeline.md:88-90`).
- **Hand-made numbers disagree.** Same price data, two scaler stds:
  80609.87 in the tutorial and 79498.59 in the comparison page
  (`OLD:docs/tutorials/basic-pipeline.md:178` against
  `OLD:docs/tutorials/sklearn-comparison.md:175`). The raw mean of the 13
  non-null prices is 281,153.85 by my arithmetic; both pages print 281,923.08
  (inference: figures typed, not produced). `Expression("price * quantity AS
  total_cost")` is listed before `Imputer` yet its SQL contains the imputed
  inputs (`OLD:docs/examples/full-pipeline.md:51`, `:92`), which the documented
  composition cannot produce.
- **sklearn parity claim.** The page asserts equality to `1e-6`
  (`OLD:docs/tutorials/sklearn-comparison.md:136-141`) and the start page to
  `1e-10` (`OLD:docs/getting-started.md:216-220`) for a pipeline whose
  imputer is followed by the scaler. scikit-learn scales the imputed data;
  a raw-input fit cannot match (inference from the compiler spec). The
  baseline said parity tests "skipped or hand-picked"; here they are
  specified but only per transformer.

## Confirms the baseline

- Fit learns a later step's statistics from the layer input, not from what an
  earlier step in the layer produced (compiler spec `:131-135`, plan
  `:1561-1569`, tutorial scaler mean next to a median fill,
  `OLD:docs/tutorials/basic-pipeline.md:178`).
- Learned state is Python values inlined as SQL literals; keys carry the
  column and statistic in one string split by convention (`price__mean`);
  "learned NULL" versus "not fitted" is not a documented distinction (only
  `_fitted`).
- sqlglot from the start, with its costs: verbosity (acknowledged,
  `OLD:docs/guide/design-decisions.md:36-41`), identifier quoting and node
  sharing bugs (review fixes), and portability promised ("Postgres, MySQL,
  Snowflake, BigQuery",
  `OLD:docs/index.md:7-8`) with no evidence of a test run on any non-DuckDB
  engine (the test specs use DuckDB only).
- A strong validation method written and not wired: sklearn equivalence, golden
  files, `known_risks`; and the parity gap above. Hand-picked 7-row data and
  loose tolerances.
- Renamed or reshaped API followed by bridges: `y` as a name, results with
  `__array__`, `__sklearn_is_fitted__`.
- Plans and standards outgrew the product: 600 KB of specs and plans, 46,000
  lines of docs and a project-database plan for agents, against a Mar 18 library
  at about v0.3
  (`OLD:docs/superpowers/plans/2026-03-17-skill-consolidation.md:5`).

## Worth keeping

- The routing table and selector algebra (`numeric() - columns("id")`) as the
  starting vocabulary for column handling; the open point is whether routing
  is implicit by default.
- The decision template (chose / why / alternatives / trade-offs) for the
  learning site's design pages.
- The "same task in scikit-learn and sqlearn, assert equal, then show what
  only sqlearn gives" tutorial. It needs real parity tests behind it.
- Tab pairs "Python / Generated SQL", and the examples-gallery convention of
  inline `VALUES` data.
- First-fit validation of custom steps with actionable errors; auto
  passthrough; `output_schema` declaration; `to_explicit()`.
- Static versus dynamic with the "false static is corruption" rule, as a name
  for steps that need a fit.
- The `known_risks` idea: a risk stays in the reference entry until a verified
  fix removes it.
- `condition=`: apply a step to a row subset and learn on the same subset.
- Counter-lessons: executed docs, link checks, one source of truth per number,
  no hand-typed outputs.

## Files covered

Legend: [x] read in full, [~] skimmed (headings, key blocks or first lines).
All paths are relative to `OLD/docs/`. 91 files.

- [x] `index.md`: landing page, tab pair, why-table, features.
- [x] `getting-started.md`: tour of Imputer, scaler, encoder, composition,
      routing.
- [x] `guide/index.md`: guide map.
- [x] `guide/concepts.md`: lifecycle, static/dynamic, routing, composition,
      schema.
- [x] `guide/compiler.md`: three phases traced; the 0.8165 example.
- [x] `guide/column-routing.md`: defaults, selectors, Columns, Union.
- [x] `guide/custom-transformers.md`: three levels with examples.
- [x] `guide/design-decisions.md`: 17 decisions in a fixed template.
- [~] `includes/abbreviations.md`: tooltip glossary (AST, CTE, OHE, NULL ...).
- [~] `javascripts/mathjax.js`: MathJax config for Material.
- [x] `api/index.md`: catalogue; links four pages that do not exist.
- [x] `api/pipeline.md`: three-line mkdocstrings stub.
- [x] `api/transformer.md`: stub for the base class.
- [x] `api/schema.md`: stub for Schema and selector factories.
- [x] `api/compiler.md`: stub for classify_step, build_fit_queries,
      compose_transform.
- [x] `api/backend.md`: stub for Backend and DuckDBBackend.
- [x] `api/io.md`: stub for resolve_input.
- [x] `api/errors.md`: stub for the error module.
- [x] `api/custom.md`: stub for Expression and custom.
- [x] `api/columns.md`: Columns prose, remainder, overlap.
- [x] `api/union.md`: stub for Union.
- [x] `api/selectors.md`: selector factories and operators.
- [x] `api/operators.md`: `+`, `+=`, flattening, cloning, collisions.
- [x] `api/imputer.md`: COALESCE formula; says auto is mean (contradiction).
- [x] `api/standard-scaler.md`: z-score, NULLIF, population std.
- [~] `api/minmax-scaler.md`: formula and SQL.
- [~] `api/robust-scaler.md`: median and IQR formula and SQL.
- [~] `api/maxabs-scaler.md`: max-abs formula and SQL.
- [~] `api/normalizer.md`: row-wise L1, L2, max norm, static.
- [x] `api/onehot-encoder.md`: CASE WHEN per category, naming rule.
- [~] `api/ordinal-encoder.md`: alphabetical codes, unknown handling.
- [~] `api/hash-encoder.md`: static hash buckets, collision note.
- [~] `api/frequency-encoder.md`: proportions or counts, in place.
- [x] `api/arithmetic.md`: stub for arithmetic module.
- [x] `api/string.md`: string transformers, all static.
- [x] `api/datetime.md`: DateParts, DateDiff, IsWeekend, Quarter.
- [x] `api/window.md`: Lag, Lead, rolling, rank via query().
- [x] `api/outlier-handler.md`: IQR and z-score, clip or remove.
- [x] `api/target-transform.md`: log, sqrt, Box-Cox on targets.
- [x] `api/feature-selection.md`: Drop, DropCorrelated, VarianceThreshold,
      SelectKBest.
- [x] `api/rename.md`: query()-based rename.
- [~] `api/cast.md`: CAST mapping, static.
- [x] `api/filter.md`: WHERE via query(), parsed at construction.
- [x] `api/sample.md`: random n or fraction, no seed.
- [x] `api/deduplicate.md`: DISTINCT or window-based, keep modes.
- [x] `api/merge.md`: function returning a view name.
- [~] `api/concat.md`: UNION ALL view function.
- [x] `api/lookup.md`: mid-pipeline LEFT JOIN step.
- [x] `tutorials/index.md`: three tutorials, prerequisites.
- [x] `tutorials/basic-pipeline.md`: seven-step first pipeline.
- [~] `tutorials/custom-transformers.md`: headings and first lines; three
  levels.
- [x] `tutorials/sklearn-comparison.md`: same task in both, parity assert,
      differences table.
- [x] `examples/index.md`: gallery map, conventions.
- [x] `examples/full-pipeline.md`: end-to-end sales example; Expression-order
      anomaly.
- [~] `examples/auto-features.md`: AutoDatetime, AutoNumeric, to_explicit.
- [~] `examples/encoders.md`: first 3500 bytes (OneHot, Ordinal) and tail
  skipped.
- [~] `examples/custom.md`: headings only.
- [~] `examples/data-ops.md`: headings only.
- [~] `examples/feature-engineering.md`: headings only.
- [~] `examples/feature-selection.md`: headings and SelectKBest block.
- [~] `examples/imputer.md`: headings and auto-strategy block (says median).
- [~] `examples/scalers.md`: headings only.
- [x] `superpowers/archive/specs/2026-03-14-backend-io-design.md`: Backend
      protocol, resolve_input.
- [x] `superpowers/archive/specs/2026-03-14-compiler-design.md`: layers,
      inlining, CTE depth 8.
- [x] `superpowers/archive/specs/2026-03-14-errors-design.md`: error hierarchy.
- [x] `superpowers/archive/specs/2026-03-14-schema-design.md`: Schema, type
      sets, selectors.
- [x] `superpowers/archive/specs/2026-03-14-transformer-design.md`: base class
      contract.
- [x] `superpowers/archive/specs/2026-03-15-custom-transformers-design.md`:
      Expression, custom.
- [x] `superpowers/archive/specs/2026-03-15-integration-tests-design.md`: four
      test layers.
- [x] `superpowers/archive/specs/2026-03-15-pipeline-design.md`: Pipeline M2
      spec.
- [x] `superpowers/archive/specs/2026-03-16-auto-features-design.md`: Auto*
      family, to_explicit.
- [x] `superpowers/specs/2026-03-17-system-reference-design.md`: YAML reference,
      known_risks.
- [x] `superpowers/specs/2026-03-17-documentation-reorganization-design.md`:
      architecture/ split, INDEX.yaml (migration map read to :420, remainder by
      headings).
- [~] `superpowers/archive/plans/2026-03-14-backend-io.md`: task headings only.
- [~] `superpowers/archive/plans/2026-03-14-compiler.md`: headings;
  build_fit_queries code at :1536-1600.
- [~] `superpowers/archive/plans/2026-03-14-errors.md`: task headings only.
- [~] `superpowers/archive/plans/2026-03-14-schema.md`: task headings only.
- [~] `superpowers/archive/plans/2026-03-14-transformer.md`: task headings only.
- [~] `superpowers/archive/plans/2026-03-15-custom-transformers.md`: task
  headings only.
- [~] `superpowers/archive/plans/2026-03-15-integration-tests.md`: headings;
  composition tests grepped.
- [~] `superpowers/archive/plans/2026-03-15-pipeline.md`: task headings only.
- [~] `superpowers/archive/plans/2026-03-15-transformers.md`: headings;
  set-query FROM fix and integration test table read.
- [~] `superpowers/archive/plans/2026-03-16-auto-features.md`: task headings
  only.
- [~] `superpowers/archive/plans/2026-03-16-codebase-review-fixes.md`: headings;
  tasks 2 and 12 read.
- [~] `superpowers/plans/2026-03-17-documentation-reorganization.md`: header and
  goal only.
- [~] `superpowers/plans/2026-03-17-skill-consolidation.md`: header and first
  verdicts.
- [~] `superpowers/plans/2026-03-17-system-reference.md`: header and goal only.
- [~] `superpowers/plans/2026-03-18-condition-parameter.md`: goal, architecture,
  grepped test names.
- [~] `superpowers/plans/2026-03-18-pipeline-step-naming.md`: goal and task
  headings.
- [~] `superpowers/plans/2026-03-18-project-database.md`: revision notes and
  task headings (125 KB).
- [~] `superpowers/plans/2026-03-18-suffix-parameter.md`: goal and task
  headings.

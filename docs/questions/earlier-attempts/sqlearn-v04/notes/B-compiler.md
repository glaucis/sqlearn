---
type: architecture
tags: [compiler, sqlearn, fit, transform, sqlglot, layers]
summary: "Read-only trace of the old sqlearn compiler, core and backend code, covering fit and transform flow and the defects found in each."
related: [docs/questions/earlier-attempts/sqlearn-v04/notes/B-compiler.md, sqlearn_000]
mdindex: [type=4ca303, tags=57479c, summary=0f9346, related=96dd4c]
---
# Batch B: OLD compiler, core, backend (actual code)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn`.
Paths below are relative to OLD; `src/` is `src/sqlearn/`. Read-only; nothing
was run. "Inference" marks a conclusion drawn from the code, not observed.

## Summary

- Fit is called `learn(data, target=)` and returns a deep-copied fitted
  pipeline (`src/core/pipeline.py:L84-L104`, `src/compiler/compile.py:L82-L84`).
  It runs one `DESCRIBE`, then per **layer** one batched aggregate `SELECT` and
  one `SELECT DISTINCT` per set parameter, and a `CREATE OR REPLACE TEMP VIEW`
  between layers (`src/compiler/compile.py:L64-L114`).
- A layer is cut only after a step that is both dynamic and schema-changing
  (`src/compiler/layers.py:L215-L224`). Within a layer every step's aggregates
  run against the **layer's input**, not the previous step's output:
  `discover()` gets column names, never upstream expressions
  (`src/core/transformer.py:L210-L236`,
  `src/transforms/scalers/scale.py:L46-L50`). So `Impute` then `Scale` learns
  std on the un-imputed data; the snapshot freezes that (std 5.0 rather than
  about 4.08 for 25, NULL, 35: `tests/compiler/test_snapshots.py:L241-L258`,
  `tests/snapshots/impute_then_scale.sql`). It is the same defect the
  `sqlearn_000` review found.
- Filter, `where=`, `drop_null=` and every `query()` step are ignored while
  fitting: fit SQL never applies them (`src/compiler/layers.py:L179-L224`,
  `src/compiler/compile.py:L240-L287`). Statistics come from rows the
  transform later drops (inference, confirmed by reading the code paths).
- Transform composes by **expression substitution** into a dict
  `{column: sqlglot node}`. It gives one flat `SELECT` for expression steps and
  wraps a subquery for each `query()` step (`src/core/pipeline.py:L615-L725`,
  `tests/snapshots/filter_then_scale.sql`).
- There are two separate composers: `_compose_layer_transform` for the fit-time
  views and `_compose_pipeline_sql` for apply and `sql()`. They behave
  differently: the first skips query steps, drop_null and schema pruning
  (`src/compiler/compile.py:L240-L287` vs `src/core/pipeline.py:L615-L725`).
- Learned state lives in Python dicts on each step: `_params` (flat
  `"{col}__{stat}"` keys), `_sets`, `_resolved_columns` and `_fitted`
  (`src/core/transformer.py:L176-L179`). It is inlined as SQL literals at
  compile time and serialised to JSON by class name
  (`src/core/config.py:L71-L91`).
- sqlglot is the internal representation throughout (pinned `<30`,
  `pyproject.toml`). The source is handled as an f-string, then parsed and
  re-parsed. `cte.py` (depth-based CTE promotion) is **dead code**, used only
  by its own tests.
- The contract has holes, and transforms worked around them: TargetEncode runs
  its own SQL inside `expressions()` against a remembered temp-view name
  (`src/transforms/encoders/target_encode.py:L100-L132`). PowerScale computes
  its lambda lazily inside `expressions()`, and `to_config()` calls `sql()`
  with exceptions suppressed so the lambda gets filled in
  (`src/core/pipeline.py:L253-L258`).
- `Columns` (the ColumnTransformer equivalent) cannot work in a pipeline. It
  has `_default_columns=None`, so resolving its columns raises
  (`src/core/columns.py:L54`, `src/core/transformer.py:L62-L67`). Even past
  that, branch parameters are learned onto `Columns` and never routed back to
  the branches (`src/core/columns.py:L88-L171`). Its tests are unit-only.
- Runtime dependencies are `sqlglot`, `duckdb` and `numpy`. numpy is imported
  at the top of the backend and of `lazy.py` (`src/backend/duckdb.py:L22`,
  `src/core/lazy.py:L24`).

## Fit, traced

Call: `Pipeline.learn(data, target)` → `compile_learn(self, data, target)`
(`src/core/pipeline.py:L102-L104`).

1. `source = resolve_source(data)`. A `.parquet` path becomes
   `read_parquet('…')`, a `.csv` path becomes `read_csv_auto('…')`, any other
   string passes through as a table name or raw SQL, and a DataFrame or Arrow
   object is registered as `__sqlearn_df_N` on the global connection
   (`src/backend/duckdb.py:L124-L231`). Quotes are not escaped
   (`L159`, `L162`).
2. `schema = backend.describe(data)`: `DESCRIBE SELECT * FROM <src>`
   (`src/backend/duckdb.py:L75-L83`). This calls `resolve_source` again, so a
   DataFrame is registered twice under two view names (inference from
   `L77` + `L188-L190`).
3. **Phase 1, `inspect_steps`** (`src/compiler/layers.py:L100-L150`). For each
   step: `_resolve_columns(current_schema)`, which **mutates the user's
   original step** (`src/core/transformer.py:L340-L342`), so the "learn never
   mutates" promise at `src/core/pipeline.py:L34-L36` is false. Then
   `classify()`, then `output_schema()`; the output schema is carried forward.
   The target column is not excluded from selectors, so `Scale()` with the
   `"numeric"` default would also scale a numeric `target` (inference: there is
   no exclusion anywhere in `inspect_steps` or `resolve_columns`).
4. **classify** (`src/compiler/classify.py:L42-L188`). It has three tiers keyed
   on the module prefix `sqlearn.`. Built-ins are trusted. Custom steps with a
   declared classification are verified by calling
   `discover`/`discover_sets`; a step that claims static but is actually
   dynamic raises. Undeclared custom steps are probed, and any exception counts
   as dynamic. The probes call `discover(columns, schema)` without
   `y_column` (`L135`, `L163`).
5. **Phase 2, `plan_layers`** (`src/compiler/layers.py:L153-L230`). Each
   dynamic step's `discover()` output goes into `layer.aggregates` keyed
   `"{step}__{param}"`; `discover_sets()` *keys only* go into
   `layer.set_queries`. `discover()` is called with
   `current_layer.input_schema`, not the schema propagated through earlier
   steps of the same layer (`L187-L189`). The next layer's input schema is
   `info.step.output_schema(layer.input_schema)`: **only the cutting step's
   change is applied**, so the change from a static schema changer earlier in
   the layer (for example `Drop`) is lost (`L220`; inference).
6. Deep-copy the steps (`src/compiler/compile.py:L82-L87`).
7. **Per layer, `_execute_layer`** (`src/compiler/compile.py:L163-L237`):
   - One query: `SELECT agg AS step__param, … FROM <current_source>`
     (`src/compiler/compose.py:L176-L217`), run by `execute_aggregate`, which
     returns a dict (`src/backend/duckdb.py:L85-L92`). Values go back to steps
     by splitting on the first `__` (`compile.py:L196-L201`): a step name
     containing `__` routes silently to the wrong place or to nowhere.
   - Sets: `discover_sets` is called again, but **the expression it returns is
     ignored**. The column name is recovered from the parameter-name convention
     `"{col}__categories"` by `rsplit("__",1)`, and the compiler issues its own
     `SELECT DISTINCT col FROM src ORDER BY col`, one query per parameter
     (`compile.py:L206-L228`, `compose.py:L220-L245`). So "set" can only ever
     mean a DISTINCT over one column, and NULL is included as a category
     (inference: no `WHERE … IS NOT NULL`).
   - The step is marked fitted, and `step._learn_source = source` is stamped on
     it (`compile.py:L233-L237`). This is a hidden channel that TargetEncode
     reads.
8. **Between layers**: `_compose_layer_transform` builds the cumulative
   transform `SELECT`, then `CREATE OR REPLACE TEMP VIEW __sqlearn_layer_{i}`,
   and the next layer reads that view (`compile.py:L105-L114`,
   `src/backend/duckdb.py:L115-L117`). Defects:
   - It starts from identity expressions over the **original** schema and
     re-applies **every fitted step from step 0**, yet its `FROM` is the
     *previous view*. From the third layer on, earlier steps are therefore
     applied twice and refer to columns the view no longer has (inference;
     layer tests are planning-only, `tests/compiler/test_layers_deep.py`).
   - Its stop test compares `step == layer.steps[-1].step`, a deep copy
     against the original. `Transformer` has no `__eq__`, so the test is never
     true and the loop never breaks; it works only because later steps are not
     yet fitted (`compile.py:L283`).
   - It ignores `query()`, `drop_null` and schema pruning (compare
     `src/core/pipeline.py:L665-L719`).
   - The views are never dropped: `drop_temp_view` is unused in `src`. The
     names are fixed and live on a process-global connection, so a second
     `learn()` replaces `__sqlearn_layer_0` under the first pipeline's
     TargetEncode, which still points at it (inference).
9. If there is any Filter step, a warning about X/y alignment is raised
   (`compile.py:L117-L126`). This is a compiler-to-transform import,
   `sqlearn.transforms.ops.filter`.
10. Return `pipeline._with_fitted_steps(..., input_schema=schema)`
    (`compile.py:L128-L130`, `src/core/pipeline.py:L504-L519`).

Query count for N layers with S set parameters: 1 DESCRIBE, N aggregate
queries (skipped when a layer has none), S DISTINCT queries and N-1 CREATE
VIEW. TargetEncode adds lazy `GROUP BY` queries, one per column, on the first
`expressions()` call, which may happen during layer composition, `sql()` or
`to_config()`. "1-3 queries for a pipeline" (`layers.py:L8-L9`) holds only
without set parameters.

## Transform/compile, traced

`apply(data, out, validate, lazy)` (`src/core/pipeline.py:L106-L156`) and
`sql(dialect)` → `compile_sql` (`src/compiler/compile.py:L133-L160`) both call
`_compose_pipeline_sql(pipeline, source)`. `sql()` passes the placeholder
`__input__`.

`_compose_pipeline_sql` (`src/core/pipeline.py:L615-L725`):
- `exprs = identity_expressions(input_columns)` plus
  `__sqlearn_rid__ = ROW_NUMBER() OVER ()`, injected **always**
  (`L647-L654`). An unordered window on every query is nondeterministic under
  parallel scan, and `LazyResult.row_ids` re-runs a second query and assumes
  the rid is the last column (`src/core/lazy.py:L92-L106`; inference).
- Source: `parse_one(source)`, then the `FROM` node (`L657-L663`).
- For each step:
  - `drop_null`: wrap `SELECT exprs FROM src WHERE c IS NOT NULL…`. The
    `WHERE` tests the **raw** source columns, not the composed values
    (inference). Then reset to identity expressions and re-add the rid
    (`L667-L686`).
  - `step.query(build_select_ast(exprs, source_ast))` (`L689`). When it returns
    non-None the result becomes `Subquery(this=…)`, and the expressions reset to
    identity over `output_schema(schema_with_all_types_VARCHAR)` (`L692-L703`).
    Faking every type as VARCHAR breaks any `output_schema` that depends on
    type. The query receives a SELECT that **already contains the rid**, and the
    query steps use `SELECT *` to keep it
    (`src/transforms/group_aggregate.py:L107`).
  - Otherwise `exprs = step._apply_expressions(exprs)`, then prune to
    `output_schema(...)` columns, again with all types faked as VARCHAR
    (`L706-L719`).
- Strip the rid, then `build_select(exprs, source_ast.sql())`, which
  serialises the source and **parses it again** (`L725`,
  `src/compiler/compose.py:L131-L153`).

`_apply_expressions` (`src/core/transformer.py:L344-L404`): it hides the rid,
calls `expressions(columns_, exprs)`, copies `exprs` (passthrough), **drops any
targeted column missing from the returned dict** (so OneHot's replacement
works), merges the result in place, puts the rid back and wraps
`where`/`dtype`. A step that returns `{}` for its targets deletes them; the
base `Transformer` with `_default_columns="all"` deletes every column
(inference, `L148`, `L286`, `L382-L384`).

Output shape: expression steps give one flat `SELECT` with nested expressions
(`tests/snapshots/impute_then_scale.sql`); each query step adds one level of
subquery (`tests/snapshots/filter_then_scale.sql`, with the rid computed
innermost, before the filter). There are no CTEs. The docstrings contradict
each other: "wrapping … in CTEs" (`src/compiler/__init__.py:L9-L11`) against
"no nested-subquery overhead" (`src/core/pipeline.py:L52-L56`).

Expression blow-up: a step that refers to `exprs[col]` once per category, as
Ordinal and OneHot do with `CASE WHEN <upstream> = 'a' … WHEN <upstream> = 'b'`,
copies the whole upstream subtree k times
(`src/transforms/encoders/ordinal.py:L60-L63`, `onehot.py:L71`). That is what
`cte.py` was written to address (`MAX_DEPTH=8`, depth only, not repetition),
and it was never wired in (`src/compiler/cte.py:L21`; only
`tests/compiler/test_cte.py` imports it). The same node objects are also put
under several parents without a copy (`compose.py:L100` uses `copy=False`), a
known sqlglot aliasing risk (inference).

Column routing: steps target columns by `columns=` (a list, a string keyword
`all|numeric|categorical|temporal`, or a `ColumnSelector` with `matching(glob)`
or `dtype(T)`) or by the class default `_default_columns`
(`src/core/transformer.py:L31-L107`, `src/_selectors.py`,
`src/_schema.py:L93-L170`). Resolution happens once, at learn, against the
propagated schema, and is cached as `columns_`. Type categories are fixed
frozensets of DuckDB type names (`src/_schema.py:L25-L71`); BOOLEAN, LIST and
STRUCT fall into no category.

`validate()` compares the stored training schema with a new `DESCRIBE`:
missing columns raise, an incompatible type category raises, and extra columns
warn (`src/core/pipeline.py:L158-L217`, `L584-L609`). It is opt-in.

## Learned state and serialization

- State: `_params: dict[str, Any]` (flat, `"{col}__{stat}"`, and later
  `"{col}__cat__{v}__mean"`), `_sets: dict[str, list]`, `_resolved_columns`,
  `_fitted` (`src/core/transformer.py:L176-L179`). There are also ad-hoc
  attributes: `_learn_source` (`compile.py:L236`), TargetEncode's `_y_column`
  set **inside `discover()`** on the original step
  (`target_encode.py:L61`), and PowerScale writing `params_[…lambda]` during
  `expressions()` (`src/transforms/scalers/power_scale.py:L88-L100`). In
  effect, `expressions()` can carry on fitting.
- The values are DuckDB's Python values, stored raw (`compile.py:L201`); they
  enter the SQL as literals through each transform's `expressions()`.
- `to_config` writes `config_version: 1`, `input_columns`, `input_types` and
  `steps`, each step holding `name`, `type`, `init` and
  `fitted: {params, sets, columns}` (`src/core/config.py:L1-L25`,
  `L228-L255`). `init` is recovered by reading
  attributes named after the `__init__` parameters, or the same names with a
  leading `_`, and non-default values are kept (`L94-L158`), the base
  `Transformer.__init__` included. `_serialize_value` falls back to
  `float(value)` (`L68`). So a `ColumnSelector` (`columns=sq.numeric()`), the
  `Columns` routes (Transformers), or a learned DATE or TIMESTAMP minimum raise
  TypeError (inference; none is covered by tests, as a grep of
  `tests/**/to_config` shows). The connector had the same problem in
  `sqlearn_000`.
- `from_config` looks up classes in a **registry built from `dir(sqlearn)`**,
  keeping objects that have `_classification` (`L39-L48`). Custom transformers
  cannot be loaded (`L166-L168`). Arguments are rebuilt into positional and
  keyword form from the signature; fitted state is restored and
  `_fitted=True` set (`L161-L225`). `_learn_source` is not saved, so a
  reloaded TargetEncode without precomputed category parameters falls back to
  the global mean for every category, without a warning
  (`target_encode.py:L110-L116`).
- `to_config()` first calls `self.sql()` under `contextlib.suppress(Exception)`
  to force the lazy parameters into existence
  (`src/core/pipeline.py:L253-L258`). This is a workaround for fitting that
  happens late.
- `save` and `load` are plain JSON with `default=str` (`config.py:L294-L315`).
  `default=str` would quietly turn anything that slips past
  `_serialize_value` into a string.

## sqlglot in practice

- The AST is the representation everywhere: `ExprDict = dict[str, Any]`,
  typed `Any` "to avoid a hard sqlglot import" (`src/_types.py:L15-L18`).
  Aggregates are built as `exp.Anonymous(this="AVG")`, not as typed nodes
  (`scale.py:L48`), so transpilation cannot rewrite them (inference).
- The source mixes strings and AST: f-string `read_parquet('…')` →
  `parse_one` (`pipeline.py:L661`) → `.sql()` → `parse_one` again
  (`compose.py:L280`). `where=` strings are parsed without a dialect
  (`compose.py:L99`). Fixed SQL is built by string interpolation: `DESCRIBE`,
  `CREATE VIEW` and TargetEncode's `GROUP BY` (`duckdb.py:L79`, `L117`,
  `target_encode.py:L124-L130`).
- Gotcha shared with `sqlearn_000`: a parsed `Select` used in `FROM` must be
  wrapped in `exp.Subquery` (`compose.py:L280-L284`).
- The window is built by hand: `exp.Window(this=exp.Anonymous("ROW_NUMBER"))`
  (`pipeline.py:L651-L653`). The CTE attachment uses `outer.set("with", …)`
  (`cte.py:L138`); the key name is fragile across sqlglot versions (it is the
  same `from`/`from_` type of trap as `sqlearn_000`).
- `sql(dialect)` transpiles only the final AST (`compose.py:L153`). Fit always
  runs DuckDB SQL. Multi-dialect is claimed but cannot be verified from this
  batch.
- What sqlglot did give: structural composition by substitution, the
  `CASE WHEN` wrapping for `where`, `CAST` for `dtype`, and pretty-printed
  snapshots.

## Transformer contract

`src/core/transformer.py:L110-L457`. This is not scikit-learn's contract:
- The constructor takes keyword-only universal parameters:
  `columns, where, drop_null, group_by, order_by, dtype` (`L151-L175`).
  `group_by` and `order_by` only raise "stored but not yet consumed"
  (`L166-L174`). Parameters are stored under `_name`, not `name`, and there is
  no `get_params`, `set_params` or clone, so serialisation guesses attribute
  names (`config.py:L152-L158`). This agrees with the `sqlearn_000` review:
  copy scikit-learn's `__init__` rule.
- Methods to override: `discover(columns, schema, y_column) -> {param: agg}`;
  `discover_sets(...) -> {"{col}__x": anything}` (the value is ignored);
  `expressions(columns, exprs) -> {col: expr}` (return only the changes);
  `query(input_query) -> Select | None` (it replaces expressions);
  `output_schema(schema) -> Schema` (`L210-L328`).
- Class attributes: `_default_columns` (default `"all"`) and
  `_classification`, `"static"`/`"dynamic"`/None (`L148-L149`).
- `y` is a **column name in the same relation** (`target=`), not a separate
  array (`pipeline.py:L87`).
- Fitted results are reached through `params_`, `sets_` and `columns_`
  (`L186-L202`); `is_fitted` is a boolean flag. `+` builds a flat Pipeline,
  and when the left side is a Pipeline the step names are generated again
  (`L427-L439`, `pipeline.py:L438-L468`).
- Pipeline accepts a list, `(name, step)` tuples or a dict; names are
  generated as `{class}_{i}` (`pipeline.py:L541-L581`). Duplicate names are not
  checked, and `dict(fitted_steps)` keeps only the last
  (`compile.py:L87`; inference).

## Worth keeping

- **Expression map with automatic passthrough** (`_apply_expressions`):
  return only the columns you change, and replacement is declared by omission
  plus `output_schema`. The idea is good; make the drop rule explicit rather
  than implicit.
- **Batching independent aggregates into one `SELECT`** with namespaced aliases
  `step__param`, and separate queries for multi-row results. Namespacing should
  be structured (a tuple or a mapping per step), not a string split on `__`.
- **Splitting fit into stages**, with intermediate output as a temp view so
  that later stages see the new schema. The right rule is wider than "dynamic
  and schema-changing": any step whose *values* a later dynamic step reads must
  be in an earlier stage, or the later step's aggregates must be composed over
  the upstream expressions (`AVG(COALESCE(x, 30))` in the same query; this is
  the cheap route to one-query fit for row-wise prefixes; inference).
- **Static/dynamic classification** with "if in doubt, dynamic", and verifying
  custom declarations (`classify.py`).
- **Schema threaded with `output_schema()`** so that selectors resolve after
  OneHot and similar steps; type-category selectors and `matching`/`dtype`.
- **Training-schema validation** on apply (`pipeline.py:L158-L217`).
- **Row identity** as an internal column hidden from steps, for
  deduplication, "keep first" and X/y alignment after Filter. It needs a
  deterministic source (a file row number) rather than `ROW_NUMBER() OVER ()`.
- **JSON config with a version number**, no pickle, and the input schema
  stored with it.
- **Placeholder `__input__`** so the exported SQL does not depend on the source.
- **SQL snapshot tests** (`tests/snapshots/*.sql`) as a readable contract.
  They should check values against a reference, though, or they freeze bugs
  (the impute-then-scale case).

## Defects and smells

1. Same-layer steps fit on the layer input rather than on upstream output
   (`layers.py:L187-L189`, `scale.py:L46-L50`); the snapshot locks in the wrong
   std (`tests/snapshots/impute_then_scale.sql`).
2. Filter, `where`, `drop_null` and `query()` steps are invisible to fit
   (`layers.py:L179-L224`, `compile.py:L240-L287`).
3. From the third layer on, steps are applied twice and refer to columns that
   no longer exist (`compile.py:L272-L284`; inference). The break condition is
   dead (`L283`).
4. The next layer's schema ignores earlier static schema changes in the same
   layer (`layers.py:L220`; inference).
5. Set discovery ignores what `discover_sets` returns and parses column names
   from the parameter key (`compile.py:L213-L227`); NULL is kept as a category.
6. Step names containing `__` break parameter routing (`compile.py:L197`).
7. `Columns` raises on resolution and never routes parameters to its branches
   (`columns.py:L54`, `L88-L171`); the `remainder=Transformer` type is
   accepted but has no effect (`L61`, `L196`).
8. learn mutates the user's original steps: `_resolve_columns` and
   TargetEncode's `_y_column` (`layers.py:L123`, `target_encode.py:L61`).
9. Fitting escapes into transform: TargetEncode issues SQL from
   `expressions()` against a temp view that can be replaced; PowerScale fits
   lambda lazily; `to_config` hides errors from `sql()`
   (`target_encode.py:L100-L132`, `power_scale.py:L88-L100`,
   `pipeline.py:L253-L258`).
10. `output_schema()` is called with every type faked as VARCHAR during
    composition (`pipeline.py:L696-L699`, `L712-L715`).
11. Serialisation cannot handle selectors, nested transformers, dates or
    custom classes (`config.py:L39-L68`, `L166-L168`; inference). Lazy
    parameters are lost on reload.
12. A process-global connection, fixed view names, views never dropped, and
    DataFrames registered twice and never unregistered (`duckdb.py:L26-L48`,
    `L115-L121`, `L170-L231`, `compile.py:L106`). A custom `backend=` still
    registers DataFrames on the global connection (`duckdb.py:L192`;
    inference).
13. Paths are interpolated into SQL without quote escaping
    (`duckdb.py:L159`, `L162`).
14. The target column is not excluded from the default selectors (inference).
15. Dead code: `cte.py`, `compose_step`, `remove_columns` and `drop_temp_view`
    are unused in `src`. `group_by` and `order_by` are stored and only raise a
    warning (`transformer.py:L166-L174`).
16. Docstrings contradict the code: "single pass"
    (`pipeline.py:L4`), "flat SELECT" (`L52-L56`), CTE wrapping
    (`compiler/__init__.py:L9-L11`), and "the compiler never executes SQL"
    (`compiler/__init__.py:L13`, against `compile.py:L189-L237`).
17. A compiler-to-transform dependency through `Filter` (`compile.py:L117`),
    and `Transformer` imports `compiler.compose` lazily
    (`transformer.py:L398`): the layering is circular.
18. numpy is a runtime dependency, and `apply` defaults to `out="numpy"`
    through `np.array(fetchall())`, which materialises in Python and loses
    types (`duckdb.py:L103-L104`). That is the opposite of
    larger-than-memory.

### Against `sqlearn-000-review.md`

- Agrees: aggregates learned from the raw or stage input (the same defect,
  improved here by layers but not fixed); learned state as Python attributes
  inlined as literals and saved to JSON; a registry by class name; the
  subquery wrap gotcha; a global connection; universal parameters that are
  never consumed; parameters stored under `_name` hurting serialisation.
- Differs: OLD *does* batch aggregates into one `SELECT` per stage, where
  `sqlearn_000` ran one query per aggregate. OLD flattens expression steps
  into one `SELECT` by substitution, where `sqlearn_000` nested one SELECT per
  step. OLD has a passthrough rule, which `sqlearn_000` lacked. OLD built real
  consumers (Scale, OneHot, TargetEncode), and they show the contract breaking
  for grouped or conditional statistics (TargetEncode) and for fits computed
  after aggregation (PowerScale).

## Files covered

- [x] `src/__init__.py`: public re-exports (about 130 symbols, against the
  target of 16 at L6-L7); version from metadata.
- [x] `src/_errors.py`: `SchemaValidationError(errors)` only.
- [x] `src/_schema.py`: a frozen `Schema(columns, types)`, type-category sets,
  selectors, `add` and `remove`, `_base_type`.
- [x] `src/_selectors.py`: `numeric`, `categorical`, `temporal`,
  `matching(glob)`, `dtype(T)` factories.
- [x] `src/_types.py`: the `ColumnsParam`, `ExprDict`, `Params` and `Sets`
  aliases and `ColumnSelector`.
- [x] `src/compiler/__init__.py`: re-exports `compile_learn` and
  `compile_sql`; its docstring is stale.
- [x] `src/compiler/compile.py`: runs learn (layers, aggregate and set
  execution, temp views) and `compile_sql`.
- [x] `src/compiler/compose.py`: identity expressions, universal-parameter
  wrapping, `SELECT`/aggregate/`DISTINCT` builders, source parsing.
- [x] `src/compiler/layers.py`: `StepInfo`/`Layer`, `inspect_steps`,
  `plan_layers` (the boundary rule).
- [x] `src/compiler/classify.py`: three-tier static/dynamic classification.
- [x] `src/compiler/cte.py`: depth measure and CTE wrap; unused by `src`.
- [x] `src/core/__init__.py`: re-exports `Columns`, `Pipeline`,
  `Transformer`.
- [x] `src/core/transformer.py`: base contract, column resolution,
  `_apply_expressions`, `+`.
- [x] `src/core/pipeline.py`: the API (learn, apply, validate, sql, config,
  summary, HTML, sklearn adapter) and `_compose_pipeline_sql`.
- [x] `src/core/columns.py`: per-column routing step; broken in a pipeline.
- [x] `src/core/config.py`: JSON to and from config, registry, init-argument
  extraction.
- [x] `src/core/lazy.py`: `LazyResult`, cached numpy and Arrow output,
  `__array__`, `row_ids`.
- [x] `src/backend/__init__.py`: re-exports `DuckDBBackend` and
  `get_connection`.
- [x] `src/backend/duckdb.py`: global connection, describe, aggregate, sets
  and transform execution, temp views, `resolve_source`, DataFrame
  registration, table formatting.

Also consulted (not in batch):
`src/transforms/encoders/{ordinal,target_encode,onehot}.py`,
`src/transforms/scalers/{scale,power_scale}.py`,
`src/transforms/group_aggregate.py`, `tests/compiler/test_snapshots.py`,
`tests/snapshots/*.sql`, `tests/compiler/test_layers_deep.py`, and
`pyproject.toml` (dependencies).

---
type: note
tags: [sqlearn, code-review, fit-pipeline, duckdb, batch-b]
summary: "Read-only review of Tomosius/sqlearn core code (v0.3.0), tracing fit planning, layered execution, and transform composition."
related: [docs/questions/archived/earlier-attempts/tomosius-sqlearn/notes/B-core.md]
mdindex: [type=edb465, tags=941c14, summary=bd8fe4]
---
# Batch B: `Tomosius/sqlearn` core code (`sqlearn-desktop`)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-desktop`.
Citations are `OLD:<path>:Lnn` with `<path>` relative to `OLD/src/sqlearn/` (so
`OLD:core/compiler.py:L590` is `OLD/src/sqlearn/core/compiler.py`), except where
a path starts with `tests/` or `pyproject.toml`, which are relative to OLD
itself. Read only; nothing was run. "Inference" marks a conclusion drawn from
reading the code, not observed. DuckDB claims marked "recheck" must be rechecked
on the current DuckDB before the review uses them. All 51 files under
`src/sqlearn/` were read, including `data/`, which the brief did not list.

Version 0.3.0 (`OLD:__init__.py:L158`); runtime dependencies `duckdb>=1.0`,
`numpy>=1.24`, `sqlglot[rs]>=25.0,<30`; Python `>=3.10`
(`OLD:pyproject.toml:L7`, `L24-L28`).

## Summary

- The API uses scikit-learn's names: `fit(data, y=)`, `transform`,
  `fit_transform`, `get_feature_names_out`, `get_params`/`set_params` from the
  `__init__` signature, `clone` (`OLD:core/pipeline.py:L400-L593`,
  `OLD:core/transformer.py:L391-L512`). v0.4 renamed them (`learn`, `apply`,
  `sql`) afterwards. But only `Pipeline` can fit: `Transformer.fit`,
  `transform` and `to_sql` raise `NotImplementedError`
  (`OLD:core/transformer.py:L643-L740`).
- Fit is planned in **layers**. A boundary falls after each step that is both
  dynamic and schema-changing (`OLD:core/compiler.py:L541-L552`). Each layer
  runs one batched aggregate `SELECT`, one query per set parameter, and (for
  every layer but the last) a `CREATE TEMPORARY VIEW __sq_layer_i__`
  (`OLD:core/pipeline.py:L433-L482`).
- Within a layer, a **static** step's expressions are substituted into later
  aggregates (`AVG(LN("x" + 1))`), but a **dynamic** step's are not. So
  `Imputer` then `StandardScaler` learns mean and std from the un-imputed
  column, the same defect as the baseline
  (`OLD:core/compiler.py:L572-L597`, `L734-L749`). Set queries (DISTINCT,
  GROUP BY) get no substitution at all: they always read the raw layer source
  (`OLD:core/compiler.py:L685-L702`).
- Transform composes `{column: sqlglot node}` by substitution into one
  `SELECT`. Each `query()` step becomes a CTE, and expressions deeper than 8
  nodes are promoted to a CTE automatically
  (`OLD:core/compiler.py:L767`, `L877-L983`). v0.4 had this CTE code but left
  it unwired.
- Learned state is `params_` (flat `"{col}__{stat}"` keys), `sets_` (lists of
  row dicts), `columns_`, `input_schema_` and `output_schema_` on each step
  (`OLD:core/transformer.py:L112-L118`). It is inlined into SQL as literals.
  There is **no** JSON save: the only persistence is pickle, through
  `__getstate__` (`OLD:core/transformer.py:L526-L534`).
- sqlglot is the representation throughout, with `exp.Anonymous` for MODE,
  HASH, SKEWNESS, LAST_DAY, ROW_NUMBER and RANDOM. `custom()` drops to string
  templating, putting raw column names and `str(value)` into SQL text
  (`OLD:custom.py:L242`, `L282-L285`).
- Planning uses **pre-fit** schemas and is never redone. Steps whose
  `output_schema()` depends on `columns_` or `sets_` (Ordinal, Frequency, the
  window steps, OneHot's new columns) look unchanged or under-declared when the
  plan is made, so later steps resolve their columns against a wrong schema
  (inference, `OLD:core/compiler.py:L500-L554`).
- `Columns` and `Union` work in a pipeline here. They prefix parameter keys and
  distribute them back to the branches (`OLD:core/columns.py:L269-L323`,
  `OLD:core/union.py:L228-L258`). v0.4's `Columns` could not resolve at all.
- The target column `y` is passed only to `discover()`. It is never stored
  (`_y_column` is copied by `clone` but never assigned), never excluded from
  the default selectors, and kept in transform output (inference from grep;
  `OLD:core/transformer.py:L118`, `L508`).
- Semantics departures: discrete `QUANTILE`, untie-broken `MODE`, zero-scale
  columns becoming NULL, NULL clipped to a bound by `LEAST`/`GREATEST`
  (recheck), an `AutoEncoder` "frequency" that is uniform `1/n`, and a made-up
  Box-Cox lambda (see **Transformers**).

## Fit, traced

Call: `Pipeline.fit(data, y=None, backend=None)`
(`OLD:core/pipeline.py:L400-L492`).

1. **Thread guard.** The first call records the thread id and pid; a later call
   from another thread or process raises `ThreadSafetyError`
   (`OLD:core/pipeline.py:L320-L348`).
2. **Backend.** A per-call backend, then the pipeline's own, then a new
   in-memory `DuckDBBackend` that the pipeline owns and caches
   (`OLD:core/pipeline.py:L352-L376`). The connection is lazy
   (`OLD:core/backend.py:L198-L209`). There is no process-global connection,
   unlike v0.4.
3. **Input.** `resolve_input`: a `str` passes through unchanged (a file path or
   table name); a pandas DataFrame is registered as `__sqlearn_input_N` and
   never unregistered. Anything else raises `TypeError`, so Arrow and Polars
   are refused although `register` would accept them
   (`OLD:core/io.py:L34-L72`, `OLD:core/backend.py:L287-L302`).
4. **Schema.** `DESCRIBE 'file.parquet'` for paths ending `.parquet/.csv/.json/
   .tsv`, otherwise `DESCRIBE "name"` (`OLD:core/backend.py:L134-L147`,
   `L264-L285`). Raw DuckDB type strings are kept. Column names of the form
   `__sq_*__` are refused (`OLD:core/schema.py:L163-L172`).
5. **Plan** (`plan_fit`, `OLD:core/compiler.py:L470-L566`). For each step in
   order:
   - Columns are resolved against the propagated schema
     (`OLD:core/compiler.py:L502-L506`). A spec of `None` means all columns.
     A string is a category keyword (`"numeric"`, `"categorical"`,
     `"temporal"`, `"boolean"`, `"all"`), never a column name, so
     `columns="price"` raises (`OLD:core/schema.py:L808-L830`).
   - Classification (`classify_step`, `OLD:core/compiler.py:L135-L188`). Tier
     1: a class from a `sqlearn.` module with a declared `_classification` is
     trusted. Tier 2: a custom class with a declaration has its `discover`
     and `discover_sets` called once to verify it, and a false "static"
     raises `ClassificationError` (`L191-L290`). Tier 3: no declaration, so
     probe; any exception, `None`, a non-dict, a non-empty dict or an
     overridden `fit` means dynamic (`L293-L399`). `Transformer._classify`
     (`OLD:core/transformer.py:L315-L336`) is not used by the compiler; only
     `Union` calls it.
   - Schema change: `output_schema(current)` is compared with the input; an
     exception or a non-`Schema` counts as a change
     (`OLD:core/compiler.py:L405-L464`). The step's output schema is carried
     forward.
   - Boundary after dynamic and schema-changing steps (`L541-L552`).
6. **Running expressions** start as identity `Column("c", quoted)` over the
   input schema (`OLD:core/pipeline.py:L428-L431`).
7. **Per layer** (`OLD:core/pipeline.py:L433-L482`). The source is the input
   for layer 0 and `__sq_layer_{i-1}__` afterwards (`L434`).
   `build_fit_queries` (`OLD:core/compiler.py:L705-L761`):
   - A static step calls `expressions(columns, running_exprs)` and merges the
     result into `running_exprs`. `NotImplementedError` is swallowed, and a
     `query()` step returns `{}`, so Filter, Drop, Sample and Lag contribute
     nothing to fit (`L735-L743`).
   - A dynamic step's `discover()` aggregates are copied, and each bare
     column reference is replaced with the running expression
     (`_substitute_columns`, `L572-L597`). A step `condition=` wraps the
     aggregate in `FILTER (WHERE …)`, unsubstituted (`L641-L646`). Aliases
     are `__agg_{index}_{param}`, and the mapping is a tuple
     `(step index, param)` (`L648-L650`). Any exception in `discover()` is
     swallowed and the step learns nothing (`L623-L628`): `SelectKBest`
     without `y` silently becomes a pass-through (inference, with
     `OLD:feature_selection/kbest.py:L138-L140`). A dynamic step's own
     expressions are **not** added to `running_exprs`, because it is not yet
     fitted.
   - `discover_sets()` returns `SELECT` nodes. The compiler adds
     `FROM <layer source>` when none is given, and the step's condition as
     `WHERE`. There is no substitution, so a set always sees raw layer input
     (`L653-L702`).
   - One aggregate query: `SELECT agg AS __agg_i_p, … FROM source`
     (`L752-L755`), run with `fetch_one` (`OLD:core/backend.py:L242-L262`).
     Values land in `step.params_[param]`. `params_` is created only when it
     is `None`, so a refit keeps keys from the previous fit
     (`OLD:core/pipeline.py:L439-L446`; inference).
   - One query per set key, run with `fetchall` into a list of dicts
     (`OLD:core/pipeline.py:L449-L455`). The key is split on the first `_`,
     safely, because the prefix is the step index.
   - **Finalise** each step: `columns_`, `input_schema_` (the **planned**
     schema), `_fitted=True`, then the `_post_discover` hook (Auto*), Lookup's
     `_resolve_with_backend` (a `DESCRIBE` of the lookup source), then
     `output_schema_ = output_schema(input_schema)`, then Union's
     distribution (`OLD:core/pipeline.py:L380-L398`). `output_schema_` is
     computed **before** `_distribute_fitted_params`, so a Union whose branch
     needs `sets_` to declare its columns (OneHot) gets a stale
     `output_schema_` on its first fit, and `_apply_expressions` then filters
     the branch's new columns out (inference).
   - **Between layers**: `compose_transform(this layer's steps, layer source)`
     is wrapped in `CREATE TEMPORARY VIEW __sq_layer_i__ AS …`
     (`OLD:core/pipeline.py:L462-L471`). The `exp.Create` has no
     `replace=True`, so refitting a multi-layer pipeline on its cached backend
     should fail with "already exists" (inference; recheck). The views are
     never dropped. `running_exprs` reset to identity over the last step's
     post-fit output schema (`L473-L482`). Unlike v0.4, the view composes
     only this layer's steps over the previous view, which is correct.

**Query count**: 1 `DESCRIBE`; per layer, 1 aggregate query (if any dynamic
step emits one) plus 1 query per set key (OneHot, Ordinal, AutoEncoder: one per
column; Frequency: one per column); L−1 `CREATE VIEW`; plus a `DESCRIBE` per
Lookup. Every set query re-reads the layer source or view.

**Does a later step see an earlier step's output?** In order:

- Static then dynamic, same layer: **yes** for aggregates (substitution), **no**
  for sets. `Lower` then `OneHotEncoder` learns `'London'` from raw data but
  transforms `LOWER(city) = 'London'`, which never matches, so every row is
  all zeros (inference).
- Dynamic then dynamic, same layer: **no**. `Imputer` (no schema change) then
  `StandardScaler` gives
  `SELECT MEDIAN("price") AS __agg_0_price__value,
  AVG("price") AS __agg_1_price__mean,
  STDDEV_POP("price") AS __agg_1_price__std FROM src`.
  The std is that of the non-NULL values, not of the imputed column. The
  docstrings show exactly this
  (`(COALESCE(price, 3.0) - 3.0) / NULLIF(1.58, 0)`,
  `OLD:core/pipeline.py:L173-L180`).
- Anything then a step in a **later** layer: **yes**, through the view,
  including `query()` steps such as Filter. Whether a Filter affects a
  statistic therefore depends on whether a dynamic schema changer happens to
  sit between them (inference).
- Static `query()` steps in the same layer (Filter, Deduplicate, Sample,
  OutlierHandler `remove`, Lag): **invisible** to that layer's fit.

## Transform, traced

`Pipeline.transform(data)` → `resolve_input` → `compose_transform(steps,
source)` → `backend.execute` → `fetchall` → list of dicts →
`np.array(float64)`, falling back to `object` (`OLD:core/pipeline.py:L494-L532`,
`OLD:core/backend.py:L222-L240`). Everything is materialised in Python, which
contradicts "larger than memory". `to_sql(dialect, table="__input__")`
composes over the placeholder and renders with `.sql(dialect=)`
(`OLD:core/pipeline.py:L553-L578`).

`compose_transform` (`OLD:core/compiler.py:L825-L983`):

1. Every step must have `columns_` (`L854-L858`). Identity expressions are
   built over the first step's `input_schema_` (`L861-L869`).
2. For each step, an input `SELECT <exprs> FROM <current source>` is built and
   `step.query(input)` is called first (`L880-L888`). A non-`None` result
   becomes CTE `__cte_n`, the source becomes that name, and expressions reset
   to bare columns of `output_schema_` (`L910-L925`). A `condition=` on a
   query step only warns (`L894-L908`).
3. Otherwise there is a collision check: `expressions()` is **called a
   first time**, any exception is swallowed, and two steps adding the same
   non-original column raise `SchemaError` (`L931-L947`). Then
   `_apply_expressions` calls `expressions()` a **second time**
   (`L950`; `OLD:core/transformer.py:L538-L601`). That wrapper copies every
   column (passthrough), wraps changed columns in
   `CASE WHEN <condition> THEN new ELSE old END`, renames them with
   `suffix`, warns about undeclared new columns, and filters to
   `output_schema_` columns, which is how OneHot drops the original.
4. Each value must be a sqlglot `Expression` (`L953-L960`). When the maximum
   tree depth exceeds 8, the current expressions are wrapped in a CTE and
   reset to quoted column references (`L963-L968`, `L799-L822`).
5. Final `SELECT … FROM <last source>` with `.with_()` for each CTE in order
   (`L971-L981`).

Shape: a flat `SELECT` of nested expressions for expression steps, and a
`WITH __cte_0 AS (SELECT * FROM (<prev>) AS __input__ WHERE …)` chain for
query steps. Each query step wraps its input in a subquery aliased `__input__`
inside its CTE (for example `OLD:ops/filter.py:L118-L129`). There is no row
identity column, so there is no deduplication by row and no X/y alignment.

Expression blow-up: Ordinal, OneHot, Frequency and the AutoEncoder put
`exprs[col]` under k `CASE` branches without copying it
(`OLD:encoders/ordinal.py:L228-L238`, `OLD:encoders/onehot.py:L197-L212`).
The tree is then repeated k times, and the same node objects sit under
several parents. The depth-8 rule catches depth, not repetition. Normalizer,
Hash and AutoDatetime do copy (`OLD:scalers/normalizer.py:L150`,
`OLD:encoders/hash.py:L154`, `OLD:features/auto.py:L438-L444`).

Source handling (inference, recheck): the compiler turns the source string
into `exp.to_table(source)` (`OLD:core/compiler.py:L754`, `L882`, `L973`). For
`"train.parquet"` that is the qualified name `train.parquet`, not the string
literal that `DESCRIBE` and `Lookup` use (`OLD:core/backend.py:L145-L146`,
`OLD:data/lookup.py:L368-L380`). Every docstring example fits on a `.parquet`
path, yet the file-path tests use only a static step, so they run nothing
beyond `DESCRIBE` (`tests/core/test_pipeline.py:L267-L280`). Fitting or
transforming a file path with a dynamic step is probably broken.

## Learned state and saving

- Attributes: `params_: dict[str, Any]`, `sets_: dict[str, list[dict]]`,
  `columns_`, `input_schema_`, `output_schema_`, `_fitted`
  (`OLD:core/transformer.py:L107-L118`). There are also ad-hoc caches:
  `_dropped` (VarianceThreshold, DropCorrelated), `_selected` (SelectKBest),
  `_resolved_groups` (Columns), `_lookup_schema` (Lookup), `_pipeline`
  (AutoFeatures) and `_classification_verified`.
- Values are DuckDB's Python values, stored raw (`OLD:core/pipeline.py:L446`).
  They enter SQL through `exp.Literal.number(v)` or `exp.Literal.string(v)`
  in each `expressions()`. A learned NULL (an all-NULL column) becomes
  `Literal.number(None)`, which renders `None`. A learned date or timestamp
  (Imputer `median` on a temporal column, the default for "other" types:
  `OLD:imputers/imputer.py:L148-L155`) becomes an unquoted number literal.
  Both should fail at SQL time (inference).
- Missing keys fall back to silent defaults: mean 0.0, std 1.0, fill value 0
  (`OLD:scalers/standard.py:L158`, `L167`; `OLD:imputers/imputer.py:L234`;
  `OLD:custom.py:L284`). "Not fitted for this column" and "learned 0" look
  the same.
- Some decisions are made lazily, in `query()` or `output_schema()`, and
  cached only once: VarianceThreshold computes `_dropped` when it is empty
  (`OLD:feature_selection/variance.py:L167-L172`), so after a refit that
  should drop nothing, the old drops stay.
- **Saving**: none. There is no `to_config`, `save` or `load` anywhere in
  `src/`. `__getstate__` only clears `_connection` for pickling
  (`OLD:core/transformer.py:L526-L534`). `Pipeline` has no `__getstate__`
  and holds its backend, so pickling a fitted pipeline with an open
  connection probably fails (inference). The JSON config was added in v0.4.

## SQL representation in practice

- sqlglot AST end to end: `discover` returns aggregate nodes, `discover_sets`
  returns `Select` nodes, `expressions` returns column nodes, `query` returns a
  `Select`, and `Backend.execute` takes an `Expression` and calls
  `.sql(dialect="duckdb")` (`OLD:core/backend.py:L222-L240`). Typed nodes are
  used where they exist (`exp.Avg`, `exp.StddevPop`, `exp.Quantile`,
  `exp.Median`, `exp.Corr`, `exp.VariancePop`). `exp.Anonymous` is used for
  `MODE`, `HASH`, `SKEWNESS`, `LAST_DAY`, `ROW_NUMBER`, `RANK`, `RANDOM`,
  `REPLACE` and two-argument `TRIM`, which transpilation cannot rewrite
  (inference).
- `exp.Quantile` has no DuckDB-specific rule in the sqlglot generator, so it
  renders as `QUANTILE(col, p)`. Checked in the local uv cache's
  sqlglot, a newer version than the `<30` pin. In DuckDB, `quantile` is
  `quantile_disc` (recheck).
- Strings still appear: a `condition=` is parsed with `sqlglot.parse_one`
  without a dialect (`OLD:core/transformer.py:L165`). `custom()` and
  `Expression()` wrap the template in `SELECT … FROM __t__`, parse it with the
  DuckDB dialect, and in `custom()` substitute by string first
  (`OLD:custom.py:L27-L49`, `L242`, `L282-L285`). `concat` and `merge` run
  f-string `CREATE OR REPLACE VIEW {name} AS {sql}`
  (`OLD:data/concat.py:L234-L238`, `OLD:data/merge.py:L321-L325`).
- Identifier quoting is inconsistent. Scalers, imputers and encoders use
  `to_identifier(col, quoted=True)`. Feature selection, window, rename, drop
  and `TargetTransform` use unquoted or auto-quoted names
  (`OLD:feature_selection/variance.py:L122`, `OLD:features/window.py:L39`,
  `OLD:features/target.py:L154`). `DateDiff`'s reference column is
  `exp.Column(this=<str>)` (`OLD:features/datetime.py:L311`).
- Costs visible in the code: 379 `# pyright: ignore` annotations across
  `src/`, mostly on sqlglot calls (`reportUnknownMemberType` throughout).
  Structural traps were
  worked around one at a time: `.copy()` in Normalizer and Hash "to avoid
  sqlglot AST node sharing issues" (`OLD:scalers/normalizer.py:L128-L130`),
  but none in Ordinal or OneHot. And `exp.Subquery` or `exp.Alias` is needed
  for every nested `FROM`.
- Multi-dialect is claimed ("any sqlglot-supported database (Postgres, MySQL,
  Snowflake, BigQuery)", `OLD:core/backend.py:L30-L33`) but only
  `DuckDBBackend` exists, `supports()` always answers `True`
  (`OLD:core/backend.py:L304-L316`), and fit SQL always runs as DuckDB.
  DuckDB-only functions: `HASH`, `MODE`, `MEDIAN`, `QUANTILE`, `SKEWNESS`,
  `LAST_DAY`, `EXTRACT(DOW)`, `RANDOM()`.

## Contract

`Transformer` (`OLD:core/transformer.py:L20-L751`):

- Constructor: keyword-only `columns`, `suffix`, `condition`. Every parameter
  is stored under its own name, so `get_params` can read the `__init__`
  signature across the MRO and `set_params` can `setattr` it
  (`L74-L118`, `L391-L438`). This follows scikit-learn's rule, which v0.4
  dropped. `condition` is a property that parses SQL in its setter, which is
  validation inside `__init__`, against scikit-learn's rule
  (`L139-L171`).
- Class attributes: `_default_columns` (default `None`, meaning all columns in
  the compiler) and `_classification` (`"static"`, `"dynamic"`, `None`)
  (`L71-L72`). `TargetTransform` makes `_classification` a property
  (`OLD:features/target.py:L86-L97`), and `custom()` sets it on the instance
  (`OLD:custom.py:L189`). Both work only because the compiler reads the
  attribute.
- Overrides: `discover(columns, schema, y_column) -> {param: agg}`,
  `discover_sets(...) -> {name: Select}`, `expressions(columns, exprs) ->
  {col: expr}` (return only the changes), `query(input_query) -> Select | None`
  and `output_schema(schema)` (`L175-L295`). A suffix makes the default
  `output_schema` add suffixed copies (`L282-L295`).
- `y` is a column name in the same relation (`fit(data, y=)`), passed to
  `discover` as `y_column`. Nothing else records it.
- Fitted state is checked through `columns_ is None`
  (`OLD:core/compiler.py:L854-L858`) or `_fitted`. `__sklearn_is_fitted__`
  exists (`L131-L137`).
- Standalone `fit`, `transform`, `fit_transform`, `to_sql` and `freeze` are
  stubs that raise (`L643-L751`), so a bare `StandardScaler().fit(...)` does
  not work. Only `AutoFeatures` overrides `fit`, by building an internal
  Pipeline (`OLD:features/auto.py:L1346-L1371`). Inside a Pipeline, its
  `discover` and `expressions` return `{}`, so it is a silent no-op there
  (inference, `L1326`, `L1342`).
- Composition: `a + b` builds a `Pipeline` of clones; `+=` is not mutating
  (`L605-L639`, `OLD:core/pipeline.py:L597-L652`). Pipeline steps can be a
  list (auto-named in lowercase, with `_2` on repeats), `(name, step)` tuples
  or a dict, and duplicate names raise (`OLD:core/pipeline.py:L111-L160`).
- Thread affinity: `clone()` resets the owner and the connection
  (`L440-L512`).
- Error classes never raised in `src/`: `UnseenCategoryError`,
  `StaticViolationError`, `FrozenError`, `ProFeatureError`
  (`OLD:core/errors.py:L70`, `L102`, `L114`, `L130`). `ProFeatureError`
  mentions a licence key, `sq.activate("SQ-XXXX")` (`L130-L139`).

## Transformers

"sk" is scikit-learn. Departures are from reading; sk behaviour is from memory
and marked (unsure) where I am not certain.

| Name | Learns (fit SQL) | Transform SQL | Departures from scikit-learn |
|---|---|---|---|
| StandardScaler (`OLD:scalers/standard.py:L117-L178`) | `AVG`, `STDDEV_POP` | `("c" - m) / NULLIF(s, 0)` | ddof 0 matches sk. Zero std gives NULL; sk uses scale 1, giving 0. NULL is ignored in fit as in sk. No `copy`. |
| MinMaxScaler (`OLD:scalers/minmax.py:L129-L195`) | `MIN`, `MAX` | `(c - min) / NULLIF(max - min, 0) [* range + lo]` | Zero range gives NULL; sk treats the range as 1, giving `lo`. No `clip`. |
| MaxAbsScaler (`OLD:scalers/maxabs.py:L102-L140`) | `MAX(ABS(c))` | `c / NULLIF(m, 0)` | Zero gives NULL; sk divides by 1. |
| RobustScaler (`OLD:scalers/robust.py:L134-L205`) | `MEDIAN`, `QUANTILE(c, q/100)` | `(c - med) / NULLIF(q3 - q1, 0)` | `QUANTILE` is discrete in DuckDB (recheck), while `MEDIAN` interpolates; sk interpolates both. Zero IQR gives NULL; sk uses 1. No `unit_variance`. |
| Normalizer (`OLD:scalers/normalizer.py:L140-L241`) | none (static) | `c / NULLIF(norm, 0)`, with L2 `SQRT(Σc·c)`, L1 `Σ ABS`, max `GREATEST(ABS…)` | A zero-norm row gives NULL; sk leaves it unchanged. One NULL makes the L1 and L2 norms NULL for the whole row; `GREATEST` may skip NULLs (recheck). |
| Imputer (`OLD:imputers/imputer.py:L148-L250`) | `AVG`, `MEDIAN`, `MODE(c)`, none for `zero` or a constant | `COALESCE(c, v)` | Default `strategy="auto"` (median for numeric, mode for text, median for anything else); sk defaults to `mean`. Defaults to **all** columns, the target included. `MODE` without `ORDER BY` has an arbitrary tie-break; sk picks the smallest (recheck). Only NULL counts as missing, never NaN. An all-NULL column inlines `None`; sk drops it. Positional `strategy`. |
| OneHotEncoder (`OLD:encoders/onehot.py:L129-L253`) | `SELECT DISTINCT "c" FROM src` (one per column) | `CASE WHEN c = 'cat' THEN 1 ELSE 0 END` per category; the original is dropped | Categories are `str(v)`, sorted as text (`"10" < "9"`), and **truncated** to `max_categories=30` alphabetically; sk's `max_categories` keeps the most frequent and groups the rest as infrequent. Unknowns and NULL give all zeros; sk raises by default and treats NaN as a category. Names are lower-cased with non-alphanumerics replaced (`[^a-z0-9]`→`_`), so `"A b"` and `"a_b"` collide silently. No `drop`. |
| OrdinalEncoder (`OLD:encoders/ordinal.py:L150-L268`) | DISTINCT | `CASE WHEN c='A' THEN 0 … ELSE NULL/unknown END` | `handle_unknown="error"` does not raise; it gives NULL. NULL maps to NULL under `error` but to `unknown_value` under `use_encoded_value`. The text sort matches sk only for strings. An all-NULL column gives NULL. `output_schema` needs `columns_`, so before fit it reports no change: no layer boundary, and later numeric selectors miss the encoded column on the first fit (inference). |
| FrequencyEncoder (`OLD:encoders/frequency.py:L146-L261`) | `COUNT(*)`, plus `SELECT c, COUNT(*) … GROUP BY c` | `CASE WHEN c='cat' THEN freq … ELSE fill END` | No sk equivalent. The denominator includes NULL rows. `handle_unknown="error"` is accepted but does nothing. The same pre-fit schema problem as Ordinal. |
| HashEncoder (`OLD:encoders/hash.py:L138-L193`) | none (static) | n × `CASE WHEN ABS(HASH(c)) % n = i THEN 1 ELSE 0 END` | Not sk's `FeatureHasher` (murmur3, signed). DuckDB `HASH` is engine-specific and hashes NULL to a bucket (recheck). The hash is recomputed n times. |
| AutoEncoder (`OLD:encoders/auto.py:L174-L520`) | `COUNT(*)`, DISTINCT per column | one-hot when there are ≤ 20 categories, "frequency" when ≤ 500, otherwise hash with 8 buckets | Its "frequency" is **uniform `1/n_categories`**, not a frequency at all (`L341-L360`). DISTINCT pulls every value of a high-cardinality column into Python only to count it. Before fit, `output_schema` drops the columns, which forces a boundary. |
| Log (`OLD:features/arithmetic.py:L128-L145`) | none | `LN(c + offset)[/LN(base)]` | `LN(0)` and `LN(<0)` raise or give NaN in DuckDB (recheck); there is no guard. |
| Sqrt, Power, Abs, Round (`OLD:features/arithmetic.py:L211`, `L291-L297`, `L477`, `L549-L555`) | none | `SQRT`, `POW`, `ABS`, `ROUND` | No domain guards. |
| Clip (`OLD:features/arithmetic.py:L397-L411`) | none | `GREATEST(LEAST(c, hi), lo)` | If DuckDB's `LEAST`/`GREATEST` skip NULL, a NULL becomes `hi` and then `max(hi, lo)`, where numpy keeps NaN (recheck). |
| Reciprocal (`OLD:features/arithmetic.py:L624-L633`) | none | `1.0 / NULLIF(c, 0)` | 0 gives NULL, where numpy gives inf. |
| DateParts, Quarter, IsWeekend, DateDiff (`OLD:features/datetime.py:L155-L574`) | none | `EXTRACT(part FROM c)`, `CASE WHEN EXTRACT(DOW) IN (0,6)`, `DATE_DIFF(unit, ref, c)` | DuckDB-specific `DOW` (Sunday 0; the docstring wrongly calls it ISO, `L364-L366`). NULL gives 0 in IsWeekend. Temporal includes `TIME` and `INTERVAL`, where these functions fail. |
| StringLength, Lower, Upper, Trim, Replace, Substring (`OLD:features/string.py:L96-L594`) | none | `LENGTH`, `LOWER`, `UPPER`, `TRIM`, `REPLACE`, `SUBSTRING` | `StringLength.output_schema` uses `columns_`, so the pre-fit schema still says VARCHAR. |
| OutlierHandler (`OLD:features/outlier.py:L153-L290`) | `QUANTILE` 0.25/0.75, or `AVG`/`STDDEV_POP` | clip: `GREATEST(LEAST(…))`; remove: a query step with `WHERE c BETWEEN lo AND hi AND …` | Discrete quantiles. `remove` also drops NULL rows, and it filters rows at **transform** time, test data included. The same NULL-to-bound issue as Clip. |
| TargetTransform (`OLD:features/target.py:L86-L235`) | `AVG(LN(c))` (Box-Cox auto only) | `LN(c+1)`, `SQRT`, `(POW(c,λ)-1)/λ` | Not sk's `TransformedTargetRegressor` and not `PowerTransformer`: λ = `1/(1+|mean ln c|)`, a made-up heuristic rather than maximum likelihood (`L167-L178`). No inverse. `_default_columns=None` means it targets **all** columns. |
| Lag, Lead, RollingMean, RollingStd, Rank, RowNumber (`OLD:features/window.py:L161-L917`) | none | `SELECT *, LAG(c, k) OVER (PARTITION BY … ORDER BY …) AS c_lagk FROM (…)`, and so on | Not sk. `output_schema` needs `columns_`, so the new columns are invisible to planning. Rolling uses `STDDEV_POP` (pandas `rolling.std` uses ddof 1). |
| AutoDatetime (`OLD:features/auto.py:L293-L503`) | `MIN`, `MAX`, `COUNT(DISTINCT EXTRACT(HOUR))` | up to 28 `EXTRACT` or `CASE` columns per granularity | Before fit, `output_schema` declares the **superset** of all parts. A later layer then resolves columns that the narrowed view does not have, so a dynamic step after it should fail to bind (inference). NULL gives 0 in the flags. |
| AutoNumeric (`OLD:features/auto.py:L589-L794`) | `AVG`, `STDDEV_POP`, `SKEWNESS`, `QUANTILE` 0.01/0.99, `MIN`, `MAX` | `LN(c+1)` when skew > 2, `SQRT` when skew > 1, clip at p01/p99 | Heuristic, not sk. `LN` and `SQRT` on negative data. `SKEWNESS` is DuckDB's estimator (bias convention unchecked). |
| AutoFeatures (`OLD:features/auto.py:L1186-L1571`) | an internal Pipeline | delegated | Works only standalone; a no-op inside a Pipeline. `to_explicit` with no steps builds `Rename(mapping={})`, which raises (`L1554-L1557`, `OLD:ops/rename.py:L123-L125`). |
| VarianceThreshold (`OLD:feature_selection/variance.py:L118-L254`) | `VAR_POP` | query step: `SELECT <kept cols> FROM (…)` | Matches sk's `var <= threshold` drop and ddof 0. An all-NULL column is kept. Stale `_dropped` on refit. It selects from `input_schema_`, the planned schema, so columns added by an earlier step are dropped silently if the plan did not know them (inference). |
| DropCorrelated (`OLD:feature_selection/correlated.py:L120-L291`) | `CORR(a, b)` for every pair, all in one query | query step | Not sk. O(n²) aggregates. Greedy drop by pair count, ties broken by the alphabetically last name. |
| SelectKBest (`OLD:feature_selection/kbest.py:L116-L302`) | `CORR(c, y)` | query step | `f_classif` and `mutual_info` are accepted but all use \|corr\| (`L83` against `L146-L150`). \|r\| ranks the same as `f_regression`. Without `y`, it is silently a no-op. |
| Drop (`OLD:feature_selection/drop.py:L118-L190`) | none | query step | Selects from the planned `input_schema_`. |
| Cast (`OLD:ops/cast.py:L101-L146`) | none | `CAST(c AS t)` | Fine. |
| Filter (`OLD:ops/filter.py:L74-L129`) | none | CTE with `WHERE <condition>` | Invisible to its own layer's fit; applies at transform time. |
| Rename (`OLD:ops/rename.py:L136-L193`) | none | query step with aliases | Fine. |
| Deduplicate (`OLD:ops/deduplicate.py:L135-L336`) | none | `DISTINCT`, or `ROW_NUMBER() OVER (PARTITION BY subset ORDER BY subset[0])`, or `COUNT(*) OVER` | `keep="first"`/`"last"` sort by a partition column, which is constant inside the partition, so which row is kept is arbitrary, and "last" is no different from "first". |
| Sample (`OLD:ops/sample.py:L147-L198`) | none | `ORDER BY RANDOM() LIMIT n`, or `WHERE RANDOM() < f` | `seed` is accepted and **never used**. It samples at transform time, so test data is sampled too and results are not reproducible. |
| Lookup (`OLD:data/lookup.py:L181-L349`) | `DESCRIBE source` at fit | `LEFT JOIN 'file' AS __lookup__ ON …` | Duplicate keys multiply rows. The external source is read at transform time. |
| Expression, custom (`OLD:custom.py:L80-L389`) | `custom(learn={…})`: aggregates parsed from templates | the template with `{col}` and `{param}` replaced **as text** | Unquoted column names in text, so a name with a space or a quote breaks or injects. `str(None)` gives `None`. New columns are always typed DOUBLE. |
| Columns (`OLD:core/columns.py:L26-L522`) | the branches' discover, keys prefixed `__{group}__` | merge of the branches' expressions; remainder `drop` or `passthrough` | Matches sk's `ColumnTransformer` remainder default `drop`. It calls a branch's `expressions()` directly, skipping `_apply_expressions`, so a branch's `condition` and `suffix` are ignored. A `query()` branch is ignored silently. |
| Union (`OLD:core/union.py:L30-L498`) | the branches' discover, keys prefixed `{branch}__` | branch columns prefixed `{branch}_` | Like sk's `FeatureUnion` (`name__col`, unsure). The stale `output_schema_` on first fit, noted under **Fit, traced**. |

`concat` and `merge` (`OLD:data/concat.py:L170-L322`,
`OLD:data/merge.py:L219-L579`) are free functions. Called without `backend=`,
each opens a new in-memory `DuckDBBackend`, creates a persistent view there,
and returns the view's name. That connection is then unreachable, so the name
is useless to a Pipeline (inference). The shared key of an outer merge comes
from the left only; pandas coalesces it.

## Against v0.4

From the v0.4 batch notes (`../sqlearn-v04/notes/B-compiler.md`) and v0.4's
review, not re-read here.

- **Inherited**: the five-hook contract
  (`discover`/`discover_sets`/`expressions`/`query`/`output_schema`),
  `_default_columns`, three-tier static/dynamic classification with "if in
  doubt, dynamic", the boundary rule "dynamic and schema-changing", batched
  aggregates in one `SELECT` per layer, temporary views between layers,
  `"{col}__{stat}"` parameter keys, OneHot as DISTINCT plus `CASE WHEN`,
  `NULLIF` safe division, type-category selectors with `matching` and
  `dtype`, the `__input__` placeholder, numpy output from `fetchall`, and
  sqlglot as the representation. The same-layer Impute-then-Scale defect is
  in both.
- **v0.4 fixed or added**: JSON `to_config`/`from_config` with a version
  number and the training schema (here there was only pickle); an opt-in
  training-schema `validate()`; a warning when Filter breaks X/y alignment;
  the `__sqlearn_rid__` row id.
- **v0.4 broke or lost**:
  - **Static-step substitution into aggregates.** v0.4's `discover()` gets
    only column names (v0.4 B notes, Summary). Here, `_substitute_columns`
    already gave `AVG(LN(x + 1))` for static prefixes.
  - **Structured parameter routing.** Here it is `(step index, param)`
    tuples (`OLD:core/compiler.py:L648-L650`); v0.4 splits on `__`.
  - **Using what `discover_sets` returns.** Here any `SELECT` is executed (so
    Frequency's `GROUP BY` works); v0.4 ignored it and issued its own
    DISTINCT.
  - **Correct layer views.** Here a view composes only its own layer's steps
    over the previous view; v0.4 re-applied every step from step 0 over the
    previous view.
  - **CTE promotion.** Wired in here (`OLD:core/compiler.py:L963-L968`);
    `cte.py` is dead code in v0.4.
  - **`Columns`.** It works here; v0.4's raised on resolution.
  - **scikit-learn method names and `get_params`/`set_params`/`clone`.**
    v0.4 renamed them to `learn`/`apply`/`sql` and stored parameters under
    `_name`.
  - **A backend per pipeline.** v0.4 used a process-global connection.
- **Same in both**: Filter and other query steps are invisible to fit in their
  own stage; the target is not excluded; learned NULL and date literals are
  unhandled; selectors resolve against pre-fit schemas; and the
  expression blow-up from repeating `exprs[col]` per category.
- **Universal parameters changed**: here `columns`, `suffix` and `condition`
  (all consumed: `suffix` renames, `condition` becomes `CASE WHEN` in
  transform and `FILTER`/`WHERE` in fit). v0.4 has `where`, `drop_null`,
  `group_by`, `order_by` and `dtype`, the last two never consumed.

## New against the baseline

- A **substitution route to one-query fit already existed** and worked for
  static prefixes: `AVG(LN("x" + 1))` in the same aggregate query
  (`OLD:core/compiler.py:L572-L597`). Extending it to dynamic prefixes (once
  their parameters are known) is the cheap route that the baseline suggests.
  The missing piece is the order of execution, not the mechanism.
- Set queries need the same substitution. This attempt shows the failure
  concretely: categories learned from raw values, compared with transformed
  ones (Lower then OneHot).
- **Planning before fit is itself a defect class**. Any `output_schema()` that
  depends on learned state makes the plan wrong. Ordinal and Frequency look
  unchanged; AutoDatetime declares a superset; Union computes its output
  before its branches are fitted. The plan has to be redone after each stage,
  or the schema that a step declares has to be derivable before it learns
  anything.
- **Lazily cached decisions**: decisions derived from parameters and cached
  on the first `query()`/`output_schema()` call (`_dropped`, `_selected`)
  survive a refit. `params_` is reused rather than reset.
- **The standalone transformer could not fit** (`NotImplementedError`), so
  the scikit-learn contract was only ever met through Pipeline.
- **Sampling, outlier removal and deduplication at transform time**: row-level
  operations that make sense only on training data run on test data too, and
  Sample ignores its seed.
- **Composite steps by key prefixing** (`__{group}__param`, `{branch}__param`)
  plus a distribution hook worked, but they bypass the wrapper (`condition`,
  `suffix`) and give a stale `output_schema_`.
- Signs of a commercial plan in the core: `ProFeatureError` with a licence key
  (`OLD:core/errors.py:L130-L139`), and a FrozenPipeline and `Search`
  mentioned in stubs (`OLD:core/transformer.py:L478`, `L742-L751`).

## Contradicts the baseline

- "Both renamed scikit-learn's methods and then added bridges back." This
  attempt **kept** scikit-learn's names (`fit`, `transform`, `fit_transform`,
  `get_feature_names_out`, `get_params`, `set_params`); the renaming came
  later, in v0.4. Only `to_sql` is new.
- "Both kept it [learned state] … saved as JSON." Here there is **no** JSON
  and no save at all, only pickle via `__getstate__`. JSON arrived in v0.4.
- "Keys split on `__`" is a v0.4 regression. Here the aggregate routing is
  structured, and the set key split is safe; composite steps still prefix
  with `__`, but split by `startswith`.

## Confirms the baseline

- Within a stage, a learning step reads raw input rather than an earlier
  learning step's output: Impute then Scale scales un-imputed statistics.
- Learned state is Python values inlined as SQL literals; float literals are
  never checked; NULL and dates are unhandled.
- sqlglot from the start, with type-checker noise (379
  `pyright: ignore`) and AST aliasing worked around one place at a time.
- Portability is claimed but untested: one backend, `supports()` always
  `True`, and DuckDB-only functions throughout.
- Tables were never considered for state; temporary views were used only for
  intermediate stages.
- Transform materialises everything in Python (numpy), against
  "larger than memory".
- Nothing in transform queries data (true here, unlike v0.4's TargetEncode),
  apart from Lookup's join to its external source.

## Worth keeping

- **Static-prefix substitution into aggregates**
  (`OLD:core/compiler.py:L572-L597`), extended to dynamic prefixes and to set
  queries.
- **Parameter routing by structured key** (`(step index, param)`), not by
  string splitting.
- **`discover_sets` returning a real `SELECT`** that the compiler only
  completes with `FROM` and `WHERE`. This allows GROUP BY counts, not only
  DISTINCT.
- **Layer views that compose only their own layer over the previous view.**
- **CTE per query step and depth-based CTE promotion**, plus a repetition
  rule (a subtree used k times should become a CTE column).
- **`get_params` from the `__init__` signature across the MRO, `set_params`,
  `clone`**: scikit-learn's convention, which needs no serialisation guesswork.
- **Passthrough plus output-schema filtering** in `_apply_expressions`, with
  a warning for undeclared new columns.
- **`suffix=`** (keep the original and add a transformed copy) and
  **`condition=`** consumed in both fit (`FILTER`) and transform
  (`CASE WHEN`). Their semantics must be shared through one composer.
- **Collision detection** for new columns produced by two steps
  (`OLD:core/compiler.py:L931-L947`), without calling `expressions()` twice.
- **Reserved-name check** on input columns (`OLD:core/schema.py:L166-L172`).
- **Composable selectors** (`|`, `&`, `~`, `-`, `columns()`, `all_columns()`)
  (`OLD:core/schema.py:L352-L773`).
- **A backend per pipeline** with a lazy connection, a context manager, and
  user-owned connections never closed (`OLD:core/pipeline.py:L352-L376`,
  `L674-L689`).

## Defects

1. Same-layer dynamic steps fit on un-transformed input: Impute then Scale
   (`OLD:core/compiler.py:L734-L749`).
2. Set queries never see upstream expressions, not even static ones
   (`OLD:core/compiler.py:L685-L702`): Lower then OneHot gives all zeros
   (inference).
3. Query steps (Filter, Deduplicate, Sample, OutlierHandler remove) are
   invisible to their own layer's fit but visible to later layers'
   (`OLD:core/compiler.py:L735-L743`, `OLD:core/pipeline.py:L462-L471`).
4. The plan is built from pre-fit schemas and never redone: Ordinal,
   Frequency and StringLength look unchanged; AutoDatetime declares a
   superset that a later layer cannot bind (inference); window steps' new
   columns are invisible.
5. Union's `output_schema_` is computed before its branches are fitted
   (`OLD:core/pipeline.py:L393-L396`; inference).
6. A refit keeps stale state: `params_` and `sets_` are reused, `_dropped` and
   `_selected` are cached, and `CREATE TEMPORARY VIEW` has no
   `OR REPLACE` (`OLD:core/pipeline.py:L444-L446`, `L465-L471`; inference).
7. File-path sources become a qualified table name in `FROM`
   (`OLD:core/compiler.py:L754`), so fitting a dynamic step on `.parquet`
   is probably broken; the tests only cover static steps (inference,
   recheck).
8. Exceptions are swallowed: `discover()` errors mean "learns nothing"
   (`OLD:core/compiler.py:L623-L628`); the collision check catches
   everything (`L934`); and SelectKBest without `y` passes through silently.
9. Learned NULL renders `None`; learned dates render unquoted; missing keys
   default silently to 0 or 1 (inference).
10. The target column is neither recorded nor excluded: scaled, imputed and
    returned in transform output (inference).
11. Discrete `QUANTILE` against continuous `MEDIAN`; `MODE` with an
    arbitrary tie-break; zero-scale columns become NULL; NULL clipped to a
    bound (recheck the DuckDB behaviour).
12. AutoEncoder's "frequency" is uniform `1/n`
    (`OLD:encoders/auto.py:L341-L360`); TargetTransform's Box-Cox λ is a
    made-up heuristic; SelectKBest's `f_classif` and `mutual_info` are
    |corr|.
13. Sample ignores `seed`; Deduplicate's `keep` orders by a constant; both,
    and OutlierHandler remove, act on test data.
14. Expressions are evaluated twice per step in compose (collision check,
    then apply); `exprs[col]` is shared without copying under k CASE
    branches.
15. `custom()` substitutes raw column names and values as text
    (`OLD:custom.py:L242`, `L282-L285`).
16. AutoFeatures is a no-op inside a Pipeline; `to_explicit` can build an
    invalid `Rename({})`.
17. Standalone transformers cannot fit; `exclude_target`, `batch_size` and
    `out=` are stub parameters only (`OLD:core/transformer.py:L668-L698`).
18. DataFrames are registered and never unregistered; layer views are never
    dropped; `concat` and `merge` without `backend=` create views on a
    connection that is thrown away.
19. numpy is a runtime dependency only for the output array
    (`OLD:core/pipeline.py:L14`, `L528-L532`).
20. Docstrings promise more than the code does: "Compile ML preprocessing
    pipelines to SQL" with `.parquet` examples, "ISO" day of week,
    `FitError` "for all-NULL columns" (never raised for that), and
    `UnseenCategoryError` (never raised).

## Files covered

- [x] `__init__.py`: re-exports 86 names; `__version__ = "0.3.0"`.
- [x] `py.typed`: empty marker.
- [x] `core/__init__.py`: re-exports the core API.
- [x] `core/errors.py`: 13 exception classes; four are never raised.
- [x] `core/io.py`: `resolve_input` (a string passes through; a pandas
  DataFrame is registered as `__sqlearn_input_N`).
- [x] `core/backend.py`: the `Backend` protocol and the lazy `DuckDBBackend`
  (execute, fetch_one, describe, register, close).
- [x] `core/schema.py`: frozen `Schema`, type categories, composable
  selectors, `resolve_columns`.
- [x] `core/transformer.py`: the base contract, sklearn introspection, clone,
  `_apply_expressions` (passthrough, condition, suffix, filtering), and
  stubs for standalone fit and transform.
- [x] `core/compiler.py`: classification, schema-change detection,
  `plan_fit` layers, `build_fit_queries` with substitution,
  `compose_transform` with CTEs.
- [x] `core/pipeline.py`: step normalisation, fit by layers with temporary
  views, transform to numpy, `to_sql`, `+`, clone, context manager.
- [x] `core/columns.py`: per-group routing with prefixed parameters,
  distribution to the groups, remainder.
- [x] `core/union.py`: horizontal union of branches with prefixed columns and
  parameters.
- [x] `custom.py`: `Expression()` (static, one new column) and `custom()`
  (string templates, optional `learn=`).
- [x] `scalers/__init__.py`: re-exports.
- [x] `scalers/standard.py`: `AVG`/`STDDEV_POP`, `NULLIF`.
- [x] `scalers/minmax.py`: `MIN`/`MAX`, feature range.
- [x] `scalers/maxabs.py`: `MAX(ABS)`.
- [x] `scalers/robust.py`: `MEDIAN` plus discrete `QUANTILE`.
- [x] `scalers/normalizer.py`: static row norms L1, L2 and max.
- [x] `imputers/__init__.py`: re-exports.
- [x] `imputers/imputer.py`: auto, mean, median, mode, zero or a constant;
  `COALESCE`.
- [x] `encoders/__init__.py`: re-exports.
- [x] `encoders/onehot.py`: DISTINCT plus `CASE WHEN`, alphabetical
  truncation.
- [x] `encoders/ordinal.py`: DISTINCT plus a `CASE` index; unknowns become
  NULL.
- [x] `encoders/frequency.py`: `COUNT(*)` plus GROUP BY counts.
- [x] `encoders/hash.py`: static `ABS(HASH) % n` buckets.
- [x] `encoders/auto.py`: chooses by cardinality; uniform fake frequency.
- [x] `features/__init__.py`: re-exports.
- [x] `features/arithmetic.py`: Log, Sqrt, Power, Clip, Abs, Round,
  Reciprocal.
- [x] `features/datetime.py`: DateParts, DateDiff, IsWeekend, Quarter.
- [x] `features/string.py`: StringLength, Lower, Upper, Trim, Replace,
  Substring.
- [x] `features/outlier.py`: IQR or z-score fences; clip or remove (a query
  step).
- [x] `features/target.py`: TargetTransform (log, sqrt, heuristic Box-Cox).
- [x] `features/window.py`: Lag, Lead, RollingMean, RollingStd, Rank,
  RowNumber as query steps.
- [x] `features/auto.py`: AutoDatetime, AutoNumeric, AutoFeatures (an
  internal Pipeline), `to_explicit`.
- [x] `feature_selection/__init__.py`: re-exports.
- [x] `feature_selection/drop.py`: static Drop as a query step.
- [x] `feature_selection/variance.py`: `VAR_POP` threshold, lazy drops.
- [x] `feature_selection/correlated.py`: pairwise `CORR`, greedy drop.
- [x] `feature_selection/kbest.py`: `CORR` with `y`; `score_func` ignored.
- [x] `ops/__init__.py`: re-exports.
- [x] `ops/cast.py`: `CAST` by mapping.
- [x] `ops/filter.py`: a `WHERE` query step.
- [x] `ops/rename.py`: an alias query step.
- [x] `ops/deduplicate.py`: DISTINCT, `ROW_NUMBER` or `COUNT` windows.
- [x] `ops/sample.py`: `RANDOM()` sampling; seed unused.
- [x] `data/__init__.py`: re-exports (not in the brief's list; read anyway).
- [x] `data/lookup.py`: a join step; the lookup schema is described at fit.
- [x] `data/concat.py`: a `UNION ALL` view over sources, optionally aligned.
- [x] `data/merge.py`: a join view; inner, left, right, outer or cross.

Also consulted, outside the batch: `pyproject.toml` (dependencies), and
`tests/core/test_pipeline.py:L267-L280`, `L782-L830` (file-path fit
coverage). One local sqlglot `dialects/duckdb.py` from the uv cache was
checked for `Quantile` rendering. Nothing was skipped; no read hung.

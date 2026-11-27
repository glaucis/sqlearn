---
type: spec
tags: [sqlearn, fit-execution, learned-state, dialects, war-room]
summary: "Batch B war-room specs covering sqlearn core fit execution, learned state, and the multi-engine backend and connection design after the 2026-04-30 redesign."
related: [docs/questions/earlier-attempts/sqlearn-private-war-room/notes/B-core-specs.md]
mdindex: [type=d4f02e, tags=c2b008, summary=2b1a43, related=192de0]
---
# Batch B: core, backend and connection specs (war room)

OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem/sqlearn-private`
(GitHub `glaucis/sqlearn-private`, 26 April – 13 June 2026). Citations write
`P/` for `projects/sqlearn/`, so `OLD:P/core/step.md:L10` is
`OLD/projects/sqlearn/core/step.md`, line 10. Read only; nothing in OLD was run.
"Inference" marks a conclusion drawn from the text, not stated in it. All 26
files were read in full; none hung. DuckDB checks were run on DuckDB 2.0.0 from
`/Users/tomas/coding/glaucis/sqlearn` with `uv run python -c`.

These are the specs written after the "2026-04-30 multi-dialect redesign"
(`OLD:P/core/pipeline.md:L704-L705`), the redesign that superseded
`sqlearn_000`'s open reports. Most files cite archived plans and locked
question IDs (`Q-IO-*`, `Q-CONN-*`, "TBD-3"), which live outside this batch.
No code accompanies them.

## Summary

- **The fit defect is still designed in.** Only a "dynamic" step (one whose
  output schema depends on learned values) cuts a layer; scalar learners
  such as `Mean`, and so `Impute` and `Scale`, are "static". The learn layer
  computes "every step's learning … aggregated together in one query"
  against the layer's input (`OLD:P/core/pipeline.md:L156-L170`,
  `OLD:P/core/inspector.md:L147-L165`, `L222-L225`). `Impute` then `Scale`
  still scales un-imputed data.
- **New: row filters reach fit.** `Filter`, `DropNulls`, `Distinct` and the
  `where=` kwarg fold into the `WHERE` of every later step's input, fit
  included (`OLD:P/core/pipeline.md:L236-L319`,
  `OLD:P/core/step.md:L195`). Column transforms do not.
- **Learned state is on the step objects**: `result_` on `Aggregate`
  instances (catalogue or "bare-string" substeps), `categories_`,
  `bin_edges_` on others. It is written back from the result row by a
  `cte_index_map` keyed on `id(step)` and inlined as SQL literals through
  `__format__`, `.ast` or `.result_` (`OLD:P/core/compiler.md:L92-L101`,
  `L278-L324`, `OLD:P/core/substeps.md:L278-L335`). Access before learning
  raises `NotLearnedError`; a learned NULL is a value.
- **No float-literal rule.** `__format__` renders `42.5`, which DuckDB 2.0.0
  types as `DECIMAL(3,1)` (checked); the format spec is reserved
  (`OLD:P/core/substeps.md:L289`, `L611-L617`).
- **SQL representation: sqlglot plus a per-step dialect table.** Each
  aggregate declares `natives[dialect]` ∈ `high_node` / `low_node` /
  `alias_node`; a resolver swaps nodes, then sqlglot transpiles "syntax
  only". The war room states in writing that sqlglot's rewrites are not
  semantics-safe (`OLD:P/core/resolver.md:L117-L208`,
  `OLD:P/core/dtypes.md:L704-L805`).
- **Multi-engine became the core requirement**: DuckDB, Postgres (Tier 1),
  MySQL and ClickHouse (Tier 2), SQLite (Tier 3, run through DuckDB by
  default), with an `engine="duckdb"` ATTACH route for any of them except
  ClickHouse (`OLD:P/core/resolver.md:L291-L330`,
  `OLD:P/backend/clickhouse.md:L449-L490`).
- **DuckDB was demoted to an optional extra**; a bare install falls back to
  stdlib `sqlite3` (`OLD:P/connections/connection.md:L408-L439`,
  `L669-L684`). This contradicts `backend/duckdb.md` ("Required dependency",
  `OLD:P/backend/duckdb.md:L31-L32`) and the project's ADR 0004.
- **The connection layer is new and large**: a tiered `ConnectionAdapter`
  Protocol, an isinstance detector, sync and async registries, a plugin
  API, attribute-first version detection, BYO ownership and pool checkout
  (`OLD:P/connections/connection.md:L128-L723`).
- **Warnings shrank to dialect plumbing**: three classes, all about node
  substitution or version detection; no data or fit warnings
  (`OLD:P/core/warnings.md:L28-L33`, `L380-L425`).
- **The specs contradict each other on facts**: `Std` is sample in one file
  and population in four; `Mean` is static in one and dynamic in another;
  one backend says DuckDB's `STDDEV` is population (it is sample, checked).

## Fit execution as specified

**The flow.** For each `learn` / `apply` / `learn_apply`: the inspector
plans layers (dialect-agnostic), the compiler resolves `engine_alias` per
step, then per layer: compose one AST, resolve it for the dialect, execute
it, and "distribute" the result row to the step instances
(`OLD:P/core/compiler.md:L40-L106`). The compiler "owns the *order* and the
*handoff*" (`L108-L109`).

**What cuts a layer.** The inspector's verdict is `static` or `dynamic`.
Its Tier 3 checklist returns `dynamic` only for a set-valued aggregate
"driving a downstream column-count expansion", a data-dependent sugar
(`bins="auto"`), an overridden `learn`, or an opaque `apply`; otherwise
`static` (`OLD:P/core/inspector.md:L147-L165`). Its worked reason string is
"Built-in `Mean` declares `_classification='static'`" (`L222-L225`). So
static here means "fixed output schema", not "learns nothing": the same rule
as the April repo's "cut only after a dynamic, schema-changing step",
renamed (inference; see the April notes, Summary).

**Does a learning step learn from an earlier learning step's output? No.**
- A pipeline with dynamic steps is "typically 2 layers": a learn layer whose
  AST covers "every step's learning — static stats and dynamic categories
  aggregated together in one query", then an apply layer that uses the
  literals (`OLD:P/core/pipeline.md:L156-L170`). The compiler repeats "1 or
  2" layers for "impute, scale, encode, bin in any combination"
  (`OLD:P/core/compiler.md:L129-L134`).
- Substep queries are batched "into a single learn-pass SELECT against
  `{input}`, one projection per substep × column"
  (`OLD:P/core/substeps.md:L253-L256`), "the same composition-by-batching
  mechanism the catalog uses for `StandardScale`'s `Mean` + `Std` substeps"
  (`L272-L276`).
- Nothing substitutes an earlier step's expression into a later aggregate.
  The inspector tracks only the column schema between steps
  (`OLD:P/core/inspector.md:L332-L348`). The April spec's
  static-to-dynamic substitution (`AVG(LN(price + 1))`) has no counterpart
  in this batch (inference from absence).
- Checked on DuckDB 2.0.0 with `price = 1, 2, NULL, 5` and mean
  imputation: the batched `STDDEV_POP(price)` is 1.6997; the staged one,
  over `COALESCE(price, AVG(price))`, is 1.4720. The specs' plan yields the
  first.
- The one place a later step sees an earlier one is across a schema
  boundary: in `sq.Join` / `sq.Union`, "children fit pre-Join; parent fits
  post-Join" and "layer count = dependency depth across the whole tree"
  (`OLD:P/core/io.md:L923-L929`). The worked examples only ever put a
  learner *after* a static transform in the same child (`Mean` then `Log`,
  `Median` then `Sqrt`), never a learner after a learner
  (`L934-L959`, `L1207-L1229`).

**Set queries.** No separate set-query path. `OneHot` categories are
"dynamic categories aggregated together" in the same learn query as the
static statistics (`OLD:P/core/pipeline.md:L161-L163`); output order is
"the order returned by the learn-pass `DISTINCT` query"
(`OLD:P/core/step.md:L496-L497`). A `DISTINCT` after an imputer in the same
layer therefore reads un-imputed values (inference). Bare-string substeps
must be scalar; set-valued ones raise `SubstepResultError`
(`OLD:P/core/substeps.md:L454-L480`).

**Row steps during fit: specified, and new.** A `Filter` "scopes all
subsequent steps in its own Pipeline: the predicate folds into the input of
every step that comes after it"; stacked filters `AND` into one `WHERE`;
a nested Pipeline without `data=` inherits them, one with `data=` does not
(`OLD:P/core/pipeline.md:L247-L305`). Row filters never add a layer
(`L139-L144`, `L307-L315`). `where=` is now one meaning, a pre-filter that
"lowers to `WHERE` before the step's reduction/transform"
(`OLD:P/core/step.md:L195`), ending the April repo's two meanings. It is
sugar for stacking a `Filter` upstream (`L207-L233`). The rule covers row
filters only; a column transform before a learner is still not seen
(inference from the composition table, `OLD:P/core/pipeline.md:L189-L194`).

**One query or staged?** Staged by layer, each layer one query; the default
hand-off between layers is "in-database materialization", a temporary
table, with CTE chaining as an optimisation for small pipelines
(`OLD:P/core/compiler.md:L344-L363`). `learn_apply` is one query only when
every step is static; otherwise it runs `learn` then `apply`
(`L203-L232`). The promise is "one compilation per layer and one execution
per layer … 1–2 SQL queries total — independent of step count", "the
central efficiency promise of sqlearn versus sklearn"
(`OLD:P/core/pipeline.md:L321-L339`). `io.md` states it differently: "one
SQL query per dependency-depth pass (Pass 1 … Pass N …; final apply = ONE
giant AST)" (`OLD:P/core/io.md:L1398-L1402`).

**Within-step rules that matter for fit.** A "consumer context"
(`Impute(value=sq.Mean())`) inherits the consumer's columns and expands one
aggregate per column; an explicit `columns=` is broadcast as a shared
scalar (`OLD:P/core/dtypes.md:L1120-L1177`). The same instance used twice
is computed once; two equal instances are computed twice
(`OLD:P/core/pipeline.md:L214-L221`, `OLD:P/core/compiler.md:L305-L324`).
A runtime guard raises `StaticViolationError` if a static step's apply AST
references an uncached aggregate (`OLD:P/core/inspector.md:L307-L319`).

**Cross-validation** is out of the core: `cv=` is not a step kwarg; `sq.Search`
"wraps the pipeline and injects fold-id columns internally"
(`OLD:P/core/step.md:L99-L105`, `L203-L205`). No per-fold state model is in
this batch.

**Does this round fix the defect? No.** It improves the count (one batched
learn query instead of `sqlearn_000`'s one query per aggregate) and adds
row filters to fit, but a learner after a learner still reads the layer's
input.

## Learned state and saving

- **Where it lives.** On the step instances: `result_` and "learned-state
  attributes like `categories_` / `bin_edges_`", cleared recursively on
  every `learn()` (`OLD:P/core/pipeline.md:L100-L126`, `L341-L363`,
  `OLD:P/core/step.md:L1203-L1220`). `Aggregate` is a real subclass of
  `BaseStep` with `result_` (`OLD:P/core/dtypes.md:L583-L607`); a
  multi-column consumer's aggregate holds a dict,
  `{"price": 12.50, "quantity": 4.0}` (`L1151-L1157`). `io.md` calls it
  `Mean.value_` (`OLD:P/core/io.md:L366-L368`).
- **How it reaches SQL.** Three views of one cached value: `__format__`
  for f-strings (`"42.5"`), `.ast` for a sqlglot `Literal`, `.result_` for
  Python; `.ast` deliberately returns the literal, not the `AVG` recipe
  (`OLD:P/core/substeps.md:L278-L335`, `OLD:P/core/dtypes.md:L626-L660`,
  `L1084-L1101`). Learned state is therefore literals only; no relation or
  table form is specified.
- **Writing back.** The compiler names every CTE `_sqlearn_<N>` and keeps
  `cte_index_map: dict[BaseStep, str]` and its reverse, keyed on
  `id(step)`, to send each result value to the step that produced it
  (`OLD:P/core/compiler.md:L92-L101`, `L234-L324`). No `__`-split string
  keys, the v0.4 and April failure. The map "persists with a saved learned
  pipeline" (`L299-L303`), although identity keys cannot survive a process
  (inference).
- **"Not fitted" against "learned NULL".** All three views raise
  `NotLearnedError` before `learn()`; a learned `NULL` "is a scalar —
  propagates through the protocols cleanly" (`OLD:P/core/substeps.md:L287-L291`,
  `L465`). This separates the two states, which `sqlearn_000`'s
  `result_ is not None` did not (inference; the sentinel is not named).
- **Shared objects.** State still lives on shared instances: a child
  Pipeline reused in two parents has its state "replaced" by each
  `learn()`, and concurrent re-fit is out of scope
  (`OLD:P/core/io.md:L1349-L1362`). The cross-validation overwrite the
  baseline records is not addressed in this batch (inference).
- **Saving.** "Dialect-neutral": step list, constructor parameters,
  learned state, each step's `input_dialect`, metadata; the target dialect
  is chosen per `apply` (`OLD:P/core/pipeline.md:L376-L445`). A child's
  `data=` is stripped because a DataRef "carries a live database
  connection, which is not picklable" (`L398-L406`). The format lives in
  `rules/serialization.md`, outside this batch. Selectors are schema-free so
  they can be saved; their round-trip is still open
  (`OLD:P/core/selectors.md:L32-L45`, `L470-L477`).
- **Train here, deploy there.** Learn on DuckDB, save, load, emit Postgres
  SQL with `apply(…, output="sql", dialect="postgres")`
  (`OLD:P/core/pipeline.md:L408-L442`, `OLD:P/core/io.md:L583-L607`).

## SQL representation and engines

**sqlglot throughout.** Steps emit through one of three flavours,
`apply_ast`, `apply_sql` (parsed with the step's `input_dialect`) or
`apply_cte`; all normalise to a sqlglot AST before the resolver
(`OLD:P/core/step.md:L26-L60`, `L745-L789`). `input_dialect` defaults to
`"duckdb"` and is saved with the pipeline (`L633-L646`). A `ctx` object
carries `dialect`, `input_dialect`, `engine_alias` and reserved fields, and
is passed only to methods whose signature asks for it (`L699-L743`).
Composition fuses column projections into one `SELECT`, folds row filters
into `WHERE` and opens a CTE only for "scoped" steps such as windows
(`OLD:P/core/pipeline.md:L184-L204`).

**The resolver and `natives`.** Every concrete `Aggregate` must declare
`natives`, one entry per framework dialect, checked at class definition
(`OLD:P/core/dtypes.md:L716-L791`):
- `high_node`: the canonical form is native; pass through.
- `low_node`: substitute the step's own decomposition (a polyfill), with an
  `info` record.
- `alias_node`: substitute an engine-native alias form, only when
  `engine_alias=True`; otherwise fall back to `low_node`
  (`OLD:P/core/resolver.md:L69-L115`).

Bodies live inline in each step's spec, "no central polyfill catalog"
(`L216-L222`); the resolver rewrites to a fixed point and raises
`PolyfillCycleError` on a cycle (`L210-L255`). The backend files'
`supported_functions` lists are demoted to documentation checked by a
coverage CSV in CI (`L60-L67`, `L201-L208`). Composite steps may declare
`decomposes_into = [Mean, Std]` so their `natives` are derived as the
most-degraded constituent slot (`OLD:P/core/dtypes.md:L879-L1018`).

**"Engine alias".** A universal kwarg with a `None` sentinel that inherits
along the parent chain at compile time; explicit step values win
(`OLD:P/core/step.md:L235-L389`). It is opt-in to an engine's own spelling
when the step author has accepted it; authors "reject" aliases whose
semantics differ (`OLD:P/core/dtypes.md:L838-L868`). Postgres `MODE() WITHIN
GROUP` and `PERCENTILE_CONT … WITHIN GROUP` are declared as `alias_node`
(`OLD:P/backend/postgres.md:L124-L134`, `L289-L304`).

**Why sqlglot is not trusted for semantics.** "Sqlglot does **not**
synthesize algorithms, does **not** check whether a name-rewrite preserves
numerical semantics": a `duckdb → mysql` `STDDEV` rewrite "produces
silently wrong numbers", Postgres's `MODE` alias and canonical forms look
alike, and sqlglot cannot gate by version
(`OLD:P/core/resolver.md:L139-L178`). This is the first attempt to record
that limit as an architectural rule rather than an admission.

**Tiers and engines.** Tier 1 compiles natively; Tier 2 compiles natively
with polyfills; Tier 3 runs through DuckDB-as-engine by default
(`OLD:P/core/resolver.md:L316-L330`):

| Engine | Tier | Notes |
|---|---|---|
| DuckDB 1.4+ | 1 | Reference; also the fallback engine (`OLD:P/backend/duckdb.md:L9-L27`). |
| Postgres 12+ | 1 | `postgres_scanner` for engine mode (`OLD:P/backend/postgres.md:L7-L20`, `L358-L396`). |
| MySQL 8.0+ | 2 | `MEDIAN`, `CORR`, percentiles polyfilled; 5.x auto-routed to DuckDB (`OLD:P/backend/mysql.md:L8-L22`, `L439-L449`). |
| ClickHouse 23.8+ | 2 | `median`, `quantile`, `mode` polyfilled; no DuckDB route (`OLD:P/backend/clickhouse.md:L12-L38`, `L449-L490`). |
| SQLite 3.25+ | 3 | DuckDB-as-engine by default; always polyfill `MEDIAN` even on 3.51+ (`OLD:P/backend/sqlite.md:L8-L22`, `L320-L330`). |

**DuckDB-as-engine.** The compiler opens a process-local DuckDB, loads the
scanner named in the target's backend spec, ATTACHes the user's database,
runs DuckDB SQL and optionally writes back with `CREATE TABLE AS`; routing
is per call, never mixed per layer (`OLD:P/core/compiler.md:L169-L201`).
`engine="duckdb"` is a free verb kwarg; cross-connection `sq.Join` "falls
out for free" by ATTACHing every child's database
(`OLD:P/core/io.md:L272-L301`). `output="duckdb"` and `output="arrow.stream"`
force this route on non-DuckDB connections (`L548-L581`). Credentials go
through DuckDB `CREATE SECRET`, not the ATTACH string
(`OLD:P/connections/duckdb.md:L260-L273`).

**Why multi-engine.** The files assert it rather than argue it: the
compiler is "dialect-agnostic", plugins may add dialects only by a core
PR, and the save-then-deploy example is the stated motivation for `save` /
`load` (`OLD:P/core/dtypes.md:L761-L770`,
`OLD:P/core/pipeline.md:L436-L442`). The rationale is in
`redesign-overview.md`, outside this batch.

**Row identity.** Every IO entry injects
`_sqlearn_primary_key = row_number() OVER ()`, regenerated at every Join or
Union and stripped at exit, after an outer `ORDER BY` on it
(`OLD:P/core/io.md:L303-L428`). Output rows are "emitted in
`_sqlearn_primary_key` order" for scikit-learn parity (`L387-L390`). A
`row_number() OVER ()` with no `ORDER BY` has no defined order in SQL, so
the stability claim rests on engine behaviour (inference; not checked).
User primary keys are detected from the catalogue and reported on stdout
(`L429-L477`).

**DuckDB claims rechecked on 2.0.0.**
- `STDDEV` = `STDDEV_SAMP` = 1.5275 and `STDDEV_POP` = 1.2472 for 1, 2, 4:
  bare `STDDEV` is sample, as `backend/postgres.md` and
  `backend/clickhouse.md` say (`OLD:P/backend/postgres.md:L312-L317`) and
  against `backend/mysql.md`, which says DuckDB aliases it to population
  (`OLD:P/backend/mysql.md:L148-L154`).
- `LOG(100)` = 2.0: base 10, as stated (`OLD:P/backend/duckdb.md:L297-L303`).
- `LN(0)` = `-inf`, `LN(-1)` = `NaN`, and the same for `LOG`. The claim that
  DuckDB 1.5.x "raise[s] `OutOfRangeException` … rather than returning
  `NULL`" (`OLD:P/backend/duckdb.md:L268-L286`) does not hold on 2.0.0,
  which neither raises nor returns NULL. The proposed `LN(NULLIF(x, 0))`
  guard still returns `NaN` for negatives (inference from the check).
- `SELECT version()` returns `'v2.0.0'`, as `connections/duckdb.md` expects
  (`OLD:P/connections/duckdb.md:L138-L154`).

## Substeps, dtypes, selectors

**Substeps.** A custom step's `setup()` may assign aggregates to attributes,
either a catalogue instance (`self._lower = sq.Quantile(q=lower)`) or a
"bare-string" SQL template (`self._range = "MAX({col}) - MIN({col})"`); the
framework walks `vars(self)` after `setup()`, wraps strings into anonymous
`Aggregate`s and batches them into the learn query
(`OLD:P/core/substeps.md:L32-L115`, `L238-L276`). Templates are classified
by prefix as bare expression, full `SELECT` or full `WITH`, parsed with
`input_dialect`, and may use `{col}`, `{<kwarg>}` and `{input}`
(`L130-L236`). The same `Aggregate` machinery backs consumer "value forms":
literal, bare class, instance, or a string shortcut for parameterless
aggregates (`L482-L553`). A substep cannot reference another substep
(`L618-L624`). `setup()` replaces `__init__` as the authoring shape
(`OLD:P/core/step.md:L155-L178`). Inference: substeps are the only route to
a learned value, so a learned value can never depend on another learned
value inside one step either.

**Dtypes.** A storage taxonomy of 26 bare canonical classes (`Int8` …
`UInt64`, `Float32/64`, `Decimal`, `Bool`, `Varchar`, `Text`, five temporal,
`Uuid`, `Binary`, `Bit`, `Array`, `Struct`, `Map`, `Json`), with no
parameters (`OLD:P/core/dtypes.md:L36-L77`). A frozen `DtypeRule(storage,
role)` with `|`, `&`, `~` and presets `INTEGRAL` (which includes `Bool`),
`FLOATING`, `NUMERIC`, `TEMPORAL`, `TEXTUAL`, `ORDERABLE`, `HASHABLE`,
`ANY`; `role` is reserved for a later semantic layer (`L79-L319`). Each
backend maps raw type names to classes; unknown names fall through to
`Json` (`L321-L367`). Steps declare `accepts`; standalone use with
`columns=None` auto-picks and records `skipped_`, a consumer context is
strict (`L499-L581`). The check never raises in `inspect_dialect`, and
raises `DtypeMismatchError` at `learn` and `apply` (`L499-L517`).

**Float literals and precision.** Nothing. `Decimal` is a storage class
only; the April `precision="decimal38"` mode is gone; the literal rendering
is `"42.5"` with the format spec "reserved for future numeric-format flags"
(`OLD:P/core/substeps.md:L289`, `L611-L617`). SQLite maps `DECIMAL` to
`Float64` (`OLD:P/backend/sqlite.md:L174-L176`). Checked on 2.0.0:
`typeof(42.5)` is `DECIMAL(3,1)`, `typeof(12.50)` `DECIMAL(4,2)`,
`typeof(1e-20)` `DOUBLE`.

**`Std` semantics are contradictory.** `dtypes.md` pins `sq.Std`'s
`high_node` as "sample standard deviation (`STDDEV_SAMP` semantics)"
(`OLD:P/core/dtypes.md:L823-L836`). The Postgres, MySQL and ClickHouse
backends say "Both steps' framework contract is population (ddof=0)"
(`OLD:P/backend/postgres.md:L327-L346`, `OLD:P/backend/mysql.md:L161-L165`,
`OLD:P/backend/clickhouse.md:L366-L379`). scikit-learn's `StandardScaler`
uses population (inference from its documentation, not rechecked).

**Selectors.** A frozen `Selector` with `rule`, `pattern`, `name_set`,
`bounds` and children, combined with `|`, `&`, `~`; factories `numeric()`,
`integral()`, `floating()`, `numeric_range()`, `categorical()`,
`temporal()`, `textual()`, `matching()`, `dtype()`, `all()`, `exclude()`
(`OLD:P/core/selectors.md:L62-L237`). They resolve at learn time against the
schema reaching the step, so a selector after `OneHot` sees its indicator
columns (`L32-L45`, `L311-L317`). `categorical()` is admitted to be a
structural surrogate that also picks floats (`L147-L168`). Zero matches
raise `EmptyResolutionError` (`L319-L406`). The target column is not
excluded from any selector (inference from the catalogue).

## Connections and backend

**Split.** `backend/<dialect>.md` is the capability side (tier, functions,
dtype map, quirks, engine mode); `connections/<dialect>.md` is the
lifecycle side (driver handle, detection, execution, pools)
(`OLD:P/connections/connection.md:L20-L46`).

**Protocol.** Required core: `dialect: str`, `version: tuple[int, ...]`,
`execute(sql, params=None)`; additive mixins `SupportsAttach`,
`SupportsCopy`, `SupportsStreaming`, `SupportsServerSideAggregation`
checked by `isinstance` (`OLD:P/connections/connection.md:L128-L191`).
The `execute` return type is open (`L779-L785`).

**Detection and registry.** A flat isinstance unique-match over registered
`conn_types`; collisions are rejected at registration, so the detector
never arbitrates (`L193-L219`). Five async types raise
`AsyncNotYetSupportedError` (`L221-L235`). `RawDBAPIAdapter` is explicit
opt-in with a required `dialect=`, never a silent fallback (`L237-L245`,
`OLD:P/connections/raw_dbapi.md:L92-L149`). `register_adapter` is strict,
`sq.override_adapter` replaces silently, entry points are discovered
alphabetically (`OLD:P/connections/connection.md:L284-L406`).

**Connection model.** The connection travels only inside `data`
(`sq.table(conn, "t")`, `sq.sql(conn, "…")`, a `DuckDBPyRelation`, or an
in-memory frame); there is no `conn=` anywhere; "a single Pipeline runs all
of its steps against the one connection carried by its `data`"
(`OLD:P/connections/connection.md:L468-L511`, `OLD:P/core/io.md:L84-L202`).
`learn` and `apply` take the same data source; splits are `Search`'s job
(`OLD:P/core/step.md:L99-L105`). Child Pipelines in `Join` / `Union` carry
`data=`; mixing both raises `DataWiredTwiceError`
(`OLD:P/core/io.md:L204-L270`). sqlearn never closes a user's connection;
the outermost executor checks out one connection (or pool checkout) for the
whole compilation (`OLD:P/connections/connection.md:L607-L667`).

**Auto-default and install model.** In-memory data with no connection gets
a per-call ephemeral DuckDB if the `[duckdb]` extra is installed, else
stdlib `sqlite3`, with a one-time advisory; suppression raises
`MissingConnectionError` (`OLD:P/connections/connection.md:L408-L466`).
"DuckDB is the `[duckdb]` optional extra, not a hard dependency … a 30 MB
native dependency" (`L669-L684`, `OLD:P/connections/duckdb.md:L42-L51`).
Inference: with no DuckDB, a SQLite auto-default is a Tier 3 engine whose
default route is DuckDB-as-engine, which is not installed; the specs do not
resolve this. `io.md` still says in-memory frames get "a fresh DuckDB
session" (`OLD:P/core/io.md:L191-L197`).

**Version detection.** Attribute first (`conn.info.server_version`,
`conn.server_version`, `client.server_version`,
`sqlite3.sqlite_version_info`), then `SELECT version()`, normalised to a
tuple, cached; eager with soft-fail to the floor plus
`AmbiguousVersionWarning`; `version_override=` / `dialect_override=` escapes
(`OLD:P/connections/connection.md:L513-L560`). `VersionConstraint` compares
by prefix and strips pre-release suffixes (`L562-L605`). Per dialect:
Postgres decodes a packed integer, MySQL flips to `"mariadb"` on a suffix,
SQLite reads the module constant, DuckDB strips a `v`
(`OLD:P/connections/postgres.md:L116-L166`,
`OLD:P/connections/mysql.md:L128-L184`,
`OLD:P/connections/sqlite.md:L114-L159`,
`OLD:P/connections/duckdb.md:L120-L163`). There is no `mariadb` backend and
it is not in `FRAMEWORK_SUPPORTED_DIALECTS` (`OLD:P/core/dtypes.md:L756-L759`;
inference). ClickHouse is a fifth dialect against that four-entry constant.

**Middleware adapters.** SQLAlchemy reads the dialect from
`engine.dialect.name` and is "a compatibility option, not the foundation"
(`OLD:P/connections/sqlalchemy.md:L52-L79`); jupysql is a thin wrapper over
it whose connection class is not yet known
(`OLD:P/connections/jupysql.md:L45-L62`, `L313-L319`).

**Verification status.** Much of the backend and connection detail is
marked unconfirmed: sqlglot's ClickHouse emission, attribute shapes,
scanner writeback "worked in our spot-checks but has not been validated"
(`OLD:P/backend/clickhouse.md:L555-L594`,
`OLD:P/backend/postgres.md:L445-L449`,
`OLD:P/connections/mysql.md:L311-L333`). The SQLite polyfill's "~1.5x
overhead vs native on 1M-row tables" has no source
(`OLD:P/backend/sqlite.md:L324-L327`).

**Network.** Scanner extensions "install lazily … require network
connectivity on first use"; air-gapped users must pre-populate the cache
(`OLD:P/backend/duckdb.md:L288-L295`). Relevant to ADR 0006 (inference).

## Warnings

- **Hierarchy.** `SqlearnWarning(UserWarning)` with three subclasses:
  `AliasSubstitutionWarning` (info), `AmbiguousVersionWarning` and
  `PreReleaseVersionWarning` (advisory); `warning` severity is reserved
  (`OLD:P/core/warnings.md:L23-L33`, `L125-L148`, `L380-L425`).
- **One object is both category and record**, with ten base fields
  (`step`, `dialect`, `reason`, `severity`, `message`, `message_template`,
  `format_args`, `code`, `path`, `source`) and a derived `doc_url`
  (`L35-L123`). A dotted `code` is separate from the gettext message ID
  (`L150-L175`).
- **Two surfaces**: the full, undeduplicated list in
  `inspect_dialect().warnings`, and `warnings.warn(instance, stacklevel=2)`
  at execution; stdlib dedup (`L177-L214`). Suppression is plain
  `warnings.filterwarnings` by class; no registry (`L236-L267`).
- **"Silent" substitution** means no noise at compile time; the record still
  surfaces at execution ("Invariant 6", `OLD:P/core/resolver.md:L646-L669`).
  `Mean → Avg` emits nothing (`OLD:P/core/warnings.md:L216-L234`).
- **A display API** of `show()` with five verbosity levels and ten named
  shortcuts (`L269-L352`).
- **A second, untyped channel**: `StepClassification.warnings`, free text
  from the inspector (`L354-L378`, `OLD:P/core/inspector.md:L266-L285`).
- **Absent**: every data-quality, ordering, leakage or fit-time check of the
  April repo. The only data-facing report is the user-PK stdout line, which
  is "informational, not a warning" (`OLD:P/core/io.md:L442-L456`).

## Against the April specs and sqlearn_000

| Topic | April specs | `sqlearn_000` (code) | War room |
|---|---|---|---|
| Layer rule | Cut after dynamic, schema-changing step | No layers; one query per aggregate | Same rule, renamed static / dynamic; "dependency depth" |
| Learner after learner | Reads layer input | Reads raw input | Reads layer input |
| Static before learner | Substituted (`AVG(LN(…))`) | Not substituted | Not specified |
| Row steps in fit | Unspecified | n/a | `Filter` / `where=` fold into every later input |
| Learned state | `params_` / `sets_`, `step__col__stat` keys | `result_` on aggregate steps | `result_` on aggregates and substeps; `id(step)` map |
| Saving | JSON, plus a frozen SQL artefact | JSON | Dialect-neutral; format elsewhere |
| SQL | sqlglot, transpile | sqlglot, DuckDB only | sqlglot plus per-step `natives` and a resolver |
| Engines | DuckDB, federated in "pro" | DuckDB | Five dialects; DuckDB optional |
| Precision | `decimal38` mode | None | None |
| Warnings | 14 fit-time checkers, `group_by` rules | None | Dialect and version only |

Why it changed, as far as this batch says:
- The redesign made dialect portability "the" requirement; `sqlearn_000`'s
  sqlglot transpilation was found to be semantically unsafe (the `STDDEV`
  divergence), so a per-step dispatch table replaced trust in sqlglot
  (`OLD:P/core/resolver.md:L180-L199`).
- `sqlearn_000`'s `Impute(value=Mean("price"))` aggregate-as-parameter
  pattern was kept and generalised into substeps and value forms
  (`OLD:P/core/pipeline.md:L206-L221`); its one-query-per-aggregate learn
  became one batched query.
- `sqlearn_000`'s nested-`SELECT` apply became fused projections with CTEs
  only at scope changes (`OLD:P/core/pipeline.md:L184-L204`).
- `sqlearn_000`'s process-wide connection and `__input__` view gave way to
  connection-in-`data` with BYO ownership
  (`OLD:P/connections/connection.md:L607-L637`).
- April's precision mode and fit warnings disappear without a stated reason
  in this batch (inference: they were out of the v0.1.0 scope the files
  repeatedly name).

## New against the baseline

- Row filters (`Filter`, `DropNulls`, `Distinct`, `where=`) are applied
  during fit to every later step; `where=` has one meaning
  (`OLD:P/core/pipeline.md:L236-L319`, `OLD:P/core/step.md:L195`).
- An explicit statement that sqlglot transpilation is syntax-only and that
  semantic rewrites belong to a per-step `natives` table with
  `high_node` / `low_node` / `alias_node` forms
  (`OLD:P/core/resolver.md:L117-L208`).
- A cross-dialect alias table: bare `STDDEV` / `VARIANCE` are sample on
  DuckDB, Postgres and ClickHouse and population on MySQL; ClickHouse has no
  `VARIANCE`; ClickHouse `log` is natural, DuckDB `LOG` base 10
  (`OLD:P/backend/clickhouse.md:L341-L379`, `L419-L430`). The DuckDB rows
  checked on 2.0.0.
- `NotLearnedError` on access versus a learned `NULL` value: the first
  design that keeps the two apart (`OLD:P/core/substeps.md:L287-L291`,
  `L465`).
- Result distribution by object identity with opaque `_sqlearn_<N>` CTE
  names, never user or class names (`OLD:P/core/compiler.md:L234-L342`).
- A storage dtype taxonomy with composable `DtypeRule`s, `accepts` per
  step, and standalone-skip versus consumer-strict checking
  (`OLD:P/core/dtypes.md:L36-L581`).
- Substeps: learned scalars declared as attributes in `setup()`, including
  SQL template strings (`OLD:P/core/substeps.md:L32-L276`).
- A full connection-adapter layer and a five-engine backend matrix; DuckDB
  as an optional extra with a `sqlite3` fallback
  (`OLD:P/connections/connection.md:L128-L684`).
- `sq.Join` and `sq.Union` as steps with fresh row identity at each boundary
  and "children fit pre-merge, parent post-merge"
  (`OLD:P/core/io.md:L656-L1257`).
- On DuckDB 2.0.0, `LN` / `LOG` of 0 and negatives return `-inf` / `NaN`, not
  NULL and not an error (checked; contradicts
  `OLD:P/backend/duckdb.md:L268-L286`).

## Contradicts the baseline

- The baseline's "every attempt used sqlglot, chosen for multi-database"
  still holds, but its "portability was never tested beyond parsing" now
  has a counterpart: the war room designed per-step dispatch precisely
  because transpilation is unsafe. Still nothing was tested
  (`OLD:P/backend/clickhouse.md:L555-L594`).
- The baseline lists DuckDB as the one runtime dependency across attempts
  (and ADR 0004 requires it); this round makes it optional
  (`OLD:P/connections/connection.md:L669-L684`).
- The baseline says learned state is "normally Python values inlined as SQL
  literals, saved as JSON". Here the save format is not stated in the
  batch; `pipeline.md` strips `data=` because it is "not picklable", which
  hints at pickle (`OLD:P/core/pipeline.md:L398-L406`; inference).
- The baseline says the April repo "added a test requiring five learning
  steps to fit in one query"; this round's promise is "1–2 SQL queries"
  per `learn`, with temporary tables between layers
  (`OLD:P/core/pipeline.md:L321-L339`, `OLD:P/core/compiler.md:L344-L363`).

## Confirms the baseline

- The fit defect is kept: a learner after a learner reads the layer input
  (`OLD:P/core/pipeline.md:L156-L170`).
- Set queries are not treated as a boundary (`L161-L163`).
- Learned state lives on shared step objects; refit replaces it
  (`OLD:P/core/io.md:L1349-L1362`).
- Float literals are never checked (`OLD:P/core/substeps.md:L289`).
- The target column is never excluded from default columns or selectors
  (`OLD:P/core/step.md:L512-L537`, `OLD:P/core/selectors.md:L118-L132`).
- `y` and `fit` departures continue: `learn` / `apply` / `learn_apply`
  names, `learn(data)` taking a data source (`OLD:P/core/step.md:L62-L86`).
- No whole-pipeline comparison with scikit-learn appears in this batch.
- Hand-typed numbers are unsourced (`OLD:P/backend/sqlite.md:L324-L327`)
  and specs disagree on facts (the `Std` and `STDDEV` items above;
  `Mean` static at `OLD:P/core/inspector.md:L222-L225` against dynamic at
  `OLD:P/core/io.md:L937-L938`; `result_` against `value_`).
- Process outgrew product: 26 spec files, about 15,000 lines, i18n
  comment blocks on every message, no code.

## Worth keeping

- The sqlglot boundary rule: trust it for syntax, never for semantic
  rewrites; keep semantic choices in our own per-operation table
  (`OLD:P/core/resolver.md:L117-L208`). If ADR 0002 keeps DuckDB-only, the
  rule still applies to anything we transpile for export.
- The cross-dialect `STDDEV` / `VARIANCE` / `LOG` / `MODE` facts, and the
  habit of emitting only explicit forms (`STDDEV_POP`, `LN`)
  (`OLD:P/backend/postgres.md:L306-L346`).
- Row filters folded into the input of every later step, fit included, with
  stacked filters `AND`ed (`OLD:P/core/pipeline.md:L247-L305`). The same
  shape is what the fit boundary needs for column transforms.
- Pre-learn access raising, learned `NULL` as a value
  (`OLD:P/core/substeps.md:L287-L291`, `L465`).
- Identity-keyed result distribution and opaque CTE names
  (`OLD:P/core/compiler.md:L234-L342`), though held apart from the step
  objects, not on them.
- Standalone-skip versus consumer-strict dtype checks, and zero-match as an
  error (`OLD:P/core/dtypes.md:L519-L581`,
  `OLD:P/core/selectors.md:L319-L335`).
- `inspect_dialect()` as a never-raising dry run that returns a plan
  (`OLD:P/core/resolver.md:L351-L484`).
- BYO connection ownership: never close what the user opened
  (`OLD:P/connections/connection.md:L607-L637`).
- The ClickHouse honesty: a documented "no route" rather than an assumed
  scanner (`OLD:P/backend/clickhouse.md:L449-L490`).

## Files covered

Core (`OLD:P/core/`):

- [x] `resolver.md` (715): `natives` dispatch, sqlglot boundary, polyfill
  rewriter, DuckDB-as-engine, plan shape, warnings at execution.
- [x] `pipeline.md` (733): Pipeline as step, layers, composition table,
  Filter scope, 1–2 query promise, clean-slate refit, saving.
- [x] `step.md` (1328): `BaseStep`, three emission flavours, `setup()`,
  universal kwargs, `engine_alias` cascade, arities, run-now mode.
- [x] `substeps.md` (631): catalogue and bare-string substeps, grammar,
  placeholders, batching, three composition protocols, value forms.
- [x] `compiler.md` (459): orchestration, per-layer flow, `_sqlearn_<N>`
  CTEs and identity map, engine routing, cross-layer temp tables.
- [x] `dtypes.md` (1492): storage taxonomy, `DtypeRule`, presets, dialect
  maps, `Aggregate` class, `natives` slot, composites, error templates.
- [x] `selectors.md` (484): `Selector` type, catalogue, composition,
  learn-time resolution, empty-resolution error.
- [x] `inspector.md` (663): static / dynamic tiers, classification record,
  runtime guard, dtype pass, selector binding, placeholders.
- [x] `io.md` (1470): `data` input forms, primary-key lifecycle, nine output
  modes, `sq.Join`, `sq.Union`, fit across merges.
- [x] `warnings.md` (476): `SqlearnWarning` hierarchy, data model, surfaces,
  suppression, display API, two channels.

Backend (`OLD:P/backend/`):

- [x] `_template.md` (388): backend spec shape, tiers, reference function
  list, dtype map, alias-rejection patterns, engine mode.
- [x] `duckdb.md` (402): Tier 1 reference, functions, dtype map, `LN` and
  `LOG` quirks, extension downloads, 1.4 floor.
- [x] `postgres.md` (457): Tier 1, ordered-set aggregates, `STDDEV` alias
  table, `postgres_scanner` writeback.
- [x] `mysql.md` (482): Tier 2, polyfilled gaps, `TINYINT(1)`, 5.x routed to
  DuckDB, wrong DuckDB `STDDEV` claim.
- [x] `sqlite.md` (494): Tier 3, affinity mapping, always-polyfill lock,
  DuckDB-as-engine default.
- [x] `clickhouse.md` (594): Tier 2, wrapper unwrap, approximate quantiles,
  no engine route, unconfirmed emission items.

Connections (`OLD:P/connections/`):

- [x] `_template.md` (281): adapter spec shape; no `natives` in adapters.
- [x] `connection.md` (785): Protocol, mixins, detector, registries, plugin
  API, auto-default, scope, versions, ownership, pools, install model.
- [x] `duckdb.md` (344): adapter, optional extra, `version()` detection, all
  four mixins, ATTACH lifecycle, secrets.
- [x] `postgres.md` (323): psycopg 3 adapter, packed-integer version,
  `SupportsCopy`, `psycopg_pool`.
- [x] `mysql.md` (333): mysql-connector adapter, MariaDB flip, pool,
  C-extension class open.
- [x] `sqlite.md` (301): stdlib adapter, auto-default fallback, module
  version constant, no pool.
- [x] `clickhouse.md` (344): clickhouse-connect HTTP client, dotted version,
  `SupportsCopy` and server-side aggregation.
- [x] `jupysql.md` (336): thin wrapper delegating to SQLAlchemy; class
  unknown.
- [x] `raw_dbapi.md` (361): explicit opt-in PEP-249 fallback, required
  `dialect=`, empty floor.
- [x] `sqlalchemy.md` (414): meta-adapter, dynamic dialect,
  `server_version_info`, Engine and pool checkout.

---
type: note
tags: [sqlearn, step-specs, aggregates, war-room, batch-c]
summary: "Batch C review of 32 sqlearn-private war-room step specs (v0.1.0 walking skeleton): aggregates as a new spec family, per-engine dispatch, filters, and known dep"
related: [docs/questions/archived/earlier-attempts/sqlearn-private-april/notes/C-transform-specs.md]
mdindex: [type=edb465, tags=c19946, summary=1d38b8]
---
# Batch C: step specs (sqlearn-private war room, April to June 2026)

Source: OLD is the war room, `sqlearn-ecosystem/sqlearn-private` under ROOT
(GitHub `glaucis/sqlearn-private`, 26 April to 13 June 2026). Nothing in OLD
was run or opened beyond reading. Citation shorthand, all under
`OLD:projects/sqlearn/`:

- `OLD:A/x.md:Ln` is `aggregates/x.md` line n; `E` is `encoders/`, `F` is
  `filters/`, `I` is `imputers/`, `S` is `scalers/`, `T` is `transforms/`.
- Line numbers are those of the files as read (blank lines counted).
- "(inference)" marks my reading, not a quotation. "(checked)" marks a claim
  I ran on DuckDB 2.0.0 with `fetchall`, against literals, not against OLD.

Scope: 32 files, 7,640 lines (14 aggregates, 4 encoders, 4 filters, 3
imputers, 3 scalers, 4 transforms). Every file was read; the pure boilerplate
sections (translator tables, "Connection to other rules" tables, reference
lists) were skimmed. Nothing was cloud-only or unreadable. Two things to know
about the batch: it is the **v0.1.0 walking skeleton** of the multi-dialect
redesign, so it is far smaller than the April set (26 steps against 77), and
it is **a different spec language** (sqlglot `high_node` / `low_node` /
`alias_node` slots, `natives` per dialect, `engine_alias` cascade) from the
April pages. The previous round is in
[the April batch C](../../sqlearn-private-april/notes/C-transform-specs.md).

## Summary

- **Aggregates are a spec family of their own, and that is the new idea.**
  Thirteen aggregate specs (`Avg`, `Mean`, `Sum`, `Count`, `Min`, `Max`,
  `Median`, `Mode`, `Quantile`, `Std`, `Var`, `Corr`, `DistinctValues`)
  are public steps, callable alone (`sq.Mean(df, "price")`), usable as
  `value=` of another step, and the building blocks of scalers and encoders
  (`OLD:A/README.md:L3-7`, `L17-46`; `OLD:I/impute.md:L7`;
  `OLD:S/standard_scale.md:L7`). Earlier rounds had aggregates only as
  hidden `discover()` output. Learned state lives on the substep
  (`result_`), not on the consumer.
- **Three of the known departures are fixed at the aggregate level.**
  `Median` and `Quantile` use the interpolating `QUANTILE_CONT` and say why
  (`OLD:A/median.md:L63`, `OLD:A/quantile.md:L65`); `Mode` is written
  `mode(col ORDER BY col)` with smallest-tie as the contract
  (`OLD:A/mode.md:L9`, `L45`); `Std` and `Var` insist on `STDDEV_POP` and
  `VAR_POP` and reject the bare, dialect-dependent names
  (`OLD:A/std.md:L62`, `L74`). All three match what I checked. The others
  (RobustScale, Clip, Winsorize, Round, FrequencyEncode, Normalize) have no
  page in this batch.
- **Two known departures are confirmed as deliberate, not fixed.**
  `MissingIndicator` still flags every column and the spec pins scikit-learn
  to `features='all'` to make that comparable (`OLD:I/missing_indicator.md:
  L19`, `L236`, `L248`). `StandardScale` and `MinMaxScale` leave a constant
  column to SQL division, which the spec believes gives NULL
  (`OLD:S/standard_scale.md:L119`, `OLD:S/min_max_scale.md:L131`). On
  DuckDB 2.0.0 it gives NaN or inf (checked), so the written behaviour is
  wrong as well as different from scikit-learn (0).
- **The fit-order defect is designed in again.** Every scaler, imputer,
  filter and encoder here is classed `static` or `dynamic` by whether its
  AST depends on data, and static steps "collapse into a single query"
  (`OLD:E/cyclical_encode.md:L13`). `Impute` and `StandardScale` are both
  `static` (`OLD:I/impute.md:L11`, `OLD:S/standard_scale.md:L11`) and the
  composer "batches the aggregate's learn-pass with all other aggregates in
  the same layer" (`OLD:I/impute.md:L125`). So `Mean` for the imputer and
  `Std` for the scaler would be learned together on the un-imputed input
  (inference). No page states the boundary rule.
- **Filters are a new spec family: row-count-changing static steps.** They
  are `static`, learn nothing, run the same logic at learn and at apply,
  fold into the next step's `WHERE`, and keep a framework primary key
  (`_sqlearn_primary_key`) that gives `Distinct` a deterministic survivor
  (`OLD:F/README.md:L23-37`, `L74-80`; `OLD:F/distinct.md:L46-63`). The
  key is a row identity that could serve `y` alignment (inference), but no
  page mentions `y` or a target at all.
- **Encoders move towards scikit-learn and away from April.** `OneHot` and
  `Ordinal` default to *error on an unseen category* (scikit-learn's
  default; the April pages gave zeros and NULL). `NULL` is a learned
  category in `OneHot` (April filtered it). `CyclicalEncode` is added and
  keeps the source column. But the `Ordinal` unseen-category check can never
  fire: `list_indexof` returns NULL, not 0, for an absent value (checked),
  so unseen values silently become NULL (`OLD:E/ordinal.md:L74`,
  `L104-113`).
- **Several DuckDB claims are false on 2.0.0** (see the checked table):
  `SQRT(-1)` and `LN(0)` "raise" (`OLD:T/sqrt.md:L90-95`,
  `OLD:T/log.md:L88-96`); division by zero gives NULL; `STDDEV_POP`
  rejects Inf or NaN; `CORR` of a constant column is NULL. The page for
  `Log` and the page for `Sqrt` also disagree with each other about what a
  bad domain does.
- **The `low_node` polyfills for other engines are wrong with NULLs.** The
  window-based `Median` and `Quantile` bodies and the running-sums `Corr`
  body count NULL rows, giving 3.5 for a median that is 2.5, 2.25 for a
  quantile that is 1.7, and -0.06 for a correlation that is 0.99 (checked
  on DuckDB). The `Std` body loses all precision at magnitude 1e9 (0.0
  against 0.816). These are plain SQL, so the error is in the spec, not the
  engine.

## Spec families and template

### The six families

| Family | Base | Learns | Row effect | Pages |
|---|---|---|---|---|
| Aggregates | `Aggregate(BaseStep)` | one scalar, set or mapping per column (`result_`, `categories_`) | collapses to one row | 13 |
| Scalers | `BaseStep`, composes aggregates | nothing itself; `mean_`, `std_` read from substeps | none | 2 |
| Imputers | `BaseStep` | nothing, or a substep's `result_` | none; `MissingIndicator` adds a column | 2 |
| Encoders | `BaseStep` | category list (via `DistinctValues`), or nothing | `OneHot` fans out, `Cyclical` adds | 3 |
| Transforms | `BaseStep` | nothing | none | 3 |
| Filters | `BaseStep` | nothing | rows out <= rows in | 3 |

Citations: aggregates `OLD:A/README.md:L185-207`; scalers
`OLD:S/README.md:L167-181`; imputers `OLD:I/README.md:L175-185`; encoders
`OLD:E/README.md:L162-176`; transforms `OLD:T/README.md:L164-173`; filters
`OLD:F/README.md:L191-210`.

### The aggregate as a Step (new)

- `Aggregate` is a shared intermediate class that owns three composition
  protocols (`__format__`, `.ast`, `.result_`) so an aggregate can sit inside
  another step's keyword argument, and a class-definition-time check that
  `natives` is complete (`OLD:A/README.md:L193-207`).
- Every aggregate is `_classification = "dynamic"`, even though its own AST
  is data-independent, "because the learned scalar gets substituted into
  consumers" (`OLD:A/mean.md:L11`, `OLD:A/count.md:L13`). Yet the *consumers*
  `Impute`, `StandardScale`, `MinMaxScale` are `static`
  (`OLD:I/impute.md:L11`). So the taxonomy is inverted relative to April,
  where "dynamic" meant "has a fit query". The classification now says
  nothing about whether the step needs a fit pass (inference).
- Universal keyword block on every step: `columns`, `where=`, `group_by=`,
  `order_by=`, `drop_nulls=`, `dtype=`, `new_column=`, `engine_alias=`
  (`OLD:A/README.md:L79-92`). `where=` and `group_by=` on a scaler are
  pushed down to its `Mean` and `Std` substeps, so statistics and transform
  use the same rows (`OLD:S/standard_scale.md:L24`). Per-group fit is thus
  built in: the transform joins against cached per-group scalars
  (`OLD:S/standard_scale.md:L76`).
- Three execution modes: run-now with data as the first argument
  (`sq.Mean(df, "price")`), explicit `learn` then `apply`, and nested
  pipelines (`OLD:A/README.md:L17-77`). Calling `apply` on an unlearned scaler
  raises `NotLearnedError` (`OLD:S/README.md:L40-41`). Data-first
  positional arguments and the verbs `learn`/`apply` depart from ADR 0003 and
  need their own ADR if wanted.
- `Mean` and `Avg` ship as two sibling steps for vocabulary, not as aliases:
  `Avg` emits `AVG`, `Mean` emits `MEAN` on DuckDB and `AVG` elsewhere
  (`OLD:A/avg.md:L9`, `OLD:A/mean.md:L40-70`). Pure duplication in a design
  for one engine.

### Per-engine dispatch (the new spec language)

Each step declares `natives = {duckdb, postgres, mysql, sqlite, clickhouse}`
mapped to a tier (`OLD:A/README.md:L130-174`):

- `high_node`: the native form passes through.
- `low_node`: an inline decomposition authored as sqlglot nodes.
- `alias_node`: a near-equivalent spelling used only if `engine_alias=True`;
  each substitution emits a structured warning (`OLD:A/README.md:L176-183`).
- `unsupported`: raises.

Declared alias rejections are the useful part: bare `STDDEV`, `VARIANCE` and
`MODE(col)` are refused as aliases because MySQL maps them to the population
form and DuckDB or Postgres to the sample form or an arbitrary tie
(`OLD:A/std.md:L74`, `OLD:A/var.md:L81`, `OLD:A/mode.md:L77-79`). Where
dialects need real polyfills (`Median`, `Quantile`, `Mode`, `Std` and `Var`
on SQLite, `Corr` on MySQL and SQLite) the bodies are given as SQL. Four of
these were run on DuckDB: see the checked table. Dialects other than DuckDB
were not checked and cannot be from this repository.

### The step-spec template (compared with April)

Front-matter-free pages with: title and one-line blurb; Definition (class,
subclass, `_classification`); Constructor; Input flavor (`apply_ast`,
`apply_cte`); AST (compiled SQL); Dialect overrides; Expressions (the
four-slot block); Accepted dtypes (`NUMERIC`, `HASHABLE`, `ORDERABLE`,
`ANY`, `all()`) with an output dtype; Learned state; Errors; Messages (gettext
ids); Used by; Validation (formula, references, comparison libraries,
"cross-library divergences", expected precision in ULPs); Connection;
Open questions.

New against April: every page carries a **Validation** section with a
formula, primary-source references and an ULP floor, and a list of
divergences the validator must pin; a one-line `Output dtype`; an
`accepts` preset; error messages with stable ids and three routes forward.
Still missing: a statement of what is checked on which DuckDB version and
any scikit-learn parity test. Pages say "Populated when the validator
lands" for input datasets in every file (`OLD:A/mean.md:L171`). No
"known departure" section exists.

## Per-spec table

"sk" is the scikit-learn equivalent. "NULL" is the page's NULL rule.

### Aggregates

| Spec | sk | SQL (DuckDB) | NULL, empty, edge |
|---|---|---|---|
| Mean (`A/mean.md`) | `mean_` of StandardScaler | `MEAN(col)`; `AVG` elsewhere | NULL skipped; all-NULL gives NULL (L129) |
| Avg (`A/avg.md`) | same | `AVG(col)` | same (L114) |
| Sum (`A/sum.md`) | none | `SUM(col)` | empty gives NULL not 0, argued (L69) |
| Count (`A/count.md`) | none | `COUNT(col)` | non-NULL count; empty gives 0 (L69) |
| Min, Max (`A/min.md`, `A/max.md`) | `data_min_`, `data_max_` | `MIN`, `MAX` | NULL skipped; empty NULL. `Max` defaults `drop_nulls=True`, `Min` False (`max.md:L19`) |
| Median (`A/median.md`) | `np.nanmedian` | `MEDIAN(col)` | ignores NULL; says `QUANTILE_DISC` forbidden (L63) |
| Quantile (`A/quantile.md`) | RobustScaler quantiles | `QUANTILE_CONT(col, q)`; `q` required (L20) | `method` reserved, only `linear` (L21) |
| Mode (`A/mode.md`) | `most_frequent` | `mode(col ORDER BY col)` | smallest tie (L9); all-NULL gives NULL |
| Std (`A/std.md`) | `np.std(ddof=0)` | `STDDEV_POP` | 1 row gives 0, all-NULL NULL (L136-138) |
| Var (`A/var.md`) | `np.var` | `VAR_POP`, or `VAR_SAMP` if `ddof=1` | 1 row with ddof=1 gives NULL (L177) |
| Corr (`A/corr.md`) | `r_regression` | `CORR(col1, col2)`, two positionals (L15-22) | constant column stored as NaN (L190) |
| DistinctValues (`A/distinct_values.md`) | `categories_` | `array_agg(DISTINCT col)` or `SELECT DISTINCT` | one NULL group kept (L88) |

### Scalers, imputers, encoders

| Spec | sk | Learns and SQL | NULL, constant, unseen |
|---|---|---|---|
| StandardScale (`S/standard_scale.md`) | StandardScaler | `Mean` and `Std` substeps; `(x - mu) / sigma` inlined (L41-46) | sigma 0 "gives NULL" (L119): wrong, see checked |
| MinMaxScale (`S/min_max_scale.md`) | MinMaxScaler | `Min`, `Max`; `(x-min)/(max-min)*(b-a)+a`, `feature_range` kept (L22) | max=min "gives NULL" (L131); scikit-learn 0 |
| Impute (`I/impute.md`) | SimpleImputer | `COALESCE(col, fill)`; `value=` is a literal or an aggregate substep (L24-38) | NULL only; NaN is data (L71). No default strategy; `"mean"` is a string literal (L38) |
| MissingIndicator (`I/missing_indicator.md`) | MissingIndicator | `(col IS NULL)::INTEGER AS col_missing` (L33), source kept | all columns by default (L19) |
| OneHot (`E/one_hot.md`) | OneHotEncoder | `DistinctValues` per column, sorted by string form (L94); `CASE WHEN col = c THEN 1 ELSE 0 END` | unseen: error by default (L129); NULL is a category (L137) |
| Ordinal (`E/ordinal.md`) | OrdinalEncoder | `list_indexof([c...], col) - 1` (L70); order inherited, not sorted (L135) | unseen: `error()` or `unknown_value` (L23, L104-113); NULL kept |
| CyclicalEncode (`E/cyclical_encode.md`) | none (`category_encoders`) | static; `SIN(2*pi*x/T)`, `COS(...)`, `period` required (L23, L72) | NULL propagates; source kept (L77) |

### Filters and transforms

| Spec | sk | SQL | NULL, domain |
|---|---|---|---|
| Filter (`F/filter.md`) | none | `WHERE <predicate>`, string parsed in DuckDB flavour (L64-70) | NULL predicate drops the row (L7-11) |
| DropNulls (`F/drop_nulls.md`) | `dropna` | `WHERE c IS NOT NULL AND ...`; `columns=None` means every user column (L98-104) | equals `Filter("c IS NOT NULL")` (L8-12) |
| Distinct (`F/distinct.md`) | `drop_duplicates` | `row_number() OVER (PARTITION BY ... ORDER BY pk)`; `keep` first, last, none (L46-53, L130-153) | NULL equals NULL (L171-176) |
| Abs (`T/abs.md`) | FunctionTransformer | `abs(col)` | NULL and NaN propagate (L84) |
| Log (`T/log.md`) | `log` | bare `LN(col)`, no offset, no base (L53, L66) | domain left to the engine (L88-96) |
| Sqrt (`T/sqrt.md`) | `sqrt` | `CASE WHEN x < 0 THEN NULL ELSE SQRT(x) END` (L99-106) | negative gives NULL by wrapper (L9-10) |

## Known departures: fixed or not

| Departure (baseline) | Status in this batch |
|---|---|
| `QUANTILE` against `QUANTILE_CONT` | **Fixed** where present: `Median` and `Quantile` name `QUANTILE_CONT` and forbid `QUANTILE_DISC` (`OLD:A/median.md:L63`, `OLD:A/quantile.md:L65`, `L259`). Both agree with 2.5 for 1..4 (checked). RobustScale has no page here |
| `MODE` tie-break | **Fixed**: `mode(col ORDER BY col)` and a SQL fallback `ORDER BY freq DESC, val ASC LIMIT 1` (`OLD:A/mode.md:L45`, `L92-107`). `Impute(value=Mode())` inherits it (`OLD:I/impute.md:L177`) |
| `LEAST` / `GREATEST` with NULL | **Not applicable**: no Clip, Winsorize or Bin page |
| RobustScale IQR 0 | **Not applicable** (no page) |
| Constant columns (Scale, MinMax, MaxAbs) | **Not fixed.** StandardScale and MinMaxScale leave it to division. The page expects NULL (`OLD:S/standard_scale.md:L119`, `OLD:S/min_max_scale.md:L131`); on 2.0.0 the result is NaN for the constant value and +-inf for others (checked); scikit-learn gives 0. The spec names the sklearn choice and rejects it as "silent paternalism". MaxAbs has no page |
| `ROUND` half-even | **Not applicable** (no Round page) |
| MissingIndicator default | **Not fixed, now explicit**: default is all columns; the validator pins `features='all'` (`OLD:I/missing_indicator.md:L236`, `L248`). No `features="missing-only"` option exists |
| Frequency statistics learned in fit | **Not applicable** (no FrequencyEncode or CountEncode). The related rule is stated for scalers: statistics come from `Mean` and `Std` learned in `learn`, then inlined as literals (`OLD:S/standard_scale.md:L65`). For OneHot, `Ordinal` the category list is learned in `learn` (`OLD:E/one_hot.md:L98`) |
| Row-count-changing steps and `y` alignment | **Partly**: filters are first-class, `static`, applied identically at learn and apply, and fold into the next `SELECT` (`OLD:F/README.md:L28-30`, `L74-80`). A framework primary key provides order and identity (`OLD:F/distinct.md:L59-63`). No page mentions `y`, a target or alignment; `transform` on test data also drops rows (inference) |
| Fit sees what transform sees (fit-order) | **Not fixed**; designed in again (see Summary). The one place fit and transform agree is `where=`/`Filter`, where the filter predicate sits in the same `WHERE` as the transform (`OLD:F/filter.md:L103-107`) |
| NULL and NaN | **Worse**: NaN is "ordinary data" for every step (`OLD:I/README.md:L8-11`, `OLD:I/impute.md:L71`), yet `AVG`, `MEDIAN` and `MAX` return NaN once one NaN is present (checked), so `Impute` followed by `StandardScale` would turn a column to NaN. The spec never raises this |

## DuckDB claims checked

Run on DuckDB 2.0.0 with `uv run python`, `fetchall`, literals only.

| Claim in OLD | Result on 2.0.0 | Verdict |
|---|---|---|
| `MEDIAN` is `QUANTILE_CONT(.,0.5)` (`A/median.md:L63`) | 2.5 for 1..4; `QUANTILE(x,0.5)` and `QUANTILE_DISC` give 2 | Confirmed |
| `mode(col)` is non-deterministic on ties; `ORDER BY col` fixes it (`A/mode.md:L49`) | 3 against 1 for 3,1,3,1,2 | Confirmed |
| `STDDEV_POP` is ddof=0, `STDDEV` is sample (`A/std.md:L62`) | `STDDEV_POP` 1.247, `STDDEV` 1.528, `VARIANCE` 2.333 on 1,2,4 | Confirmed |
| 1 row: `STDDEV_POP` 0, `VAR_SAMP` NULL (`A/var.md:L176-177`) | 0.0, 0.0, NULL | Confirmed |
| All-NULL `STDDEV_POP` is NULL (`A/std.md:L136`) | NULL | Confirmed |
| `COUNT` of all-NULL is 0; `SUM`, `AVG`, `MIN`, `MAX` are NULL (`A/count.md:L69`, `A/sum.md:L69`) | 0, NULL, NULL, NULL, NULL | Confirmed |
| `SUM([-3, 3])` is 0, so NULL-on-empty keeps information (`A/sum.md:L69`) | 0 | Confirmed |
| `array_agg(DISTINCT x)` keeps one NULL; no order (`A/distinct_values.md:L88-90`) | `[None, 'b', 'a']` | Confirmed |
| `PARTITION BY` and `DISTINCT` treat two NULLs as equal (`F/distinct.md:L171`) | one row survives; `count(*) OVER` group of 2 | Confirmed |
| `WHERE` drops a NULL predicate (`F/filter.md:L7-11`) | `x > 1` keeps only 3 from (1, NULL, 3) | Confirmed |
| `IS NULL` is false for NaN (`I/missing_indicator.md:L47`) | `'NaN' IS NULL` false; `NaN = NaN` true | Confirmed |
| `COALESCE` does not touch NaN (`I/impute.md:L71`) | NaN stays NaN | Confirmed |
| `LN`, not `LOG`, is the natural log (`T/log.md:L66`) | `LOG(100)` is 2.0 | Confirmed |
| `SQRT(-1)` raises "Out of Range" (`T/sqrt.md:L90-95`) | NaN, no error | **Contradicted** |
| `LN(x <= 0)` raises on DuckDB 1.5 and later (`T/log.md:L88-96`) | `LN(0)` is -inf, `LN(-1)` is NaN, on 2.0.0 | **Contradicted** (the page's "1.5" boundary cannot be checked here) |
| Division by zero gives NULL (`S/standard_scale.md:L119`, `S/min_max_scale.md:L131`) | `1.0/0` is inf, `0::DOUBLE/0` NaN; `(x-5.0)/0.0` gives NaN, inf, -inf. `5 // 0` raises | **Contradicted** |
| `STDDEV_POP` rejects Inf or NaN (`A/std.md:L142`) | returns NaN, no error | **Contradicted** |
| `CORR` of a constant column is NULL (`A/corr.md:L190`, L273) | NaN (the page maps NULL to NaN anyway); 1 row gives NaN | Differs, harmless |
| `list_indexof` of an absent value is 0 (`E/ordinal.md:L74`) | **NULL**, also `list_position`; for a present value 1-based | **Contradicted**; the `= 0` branch with `error()` never runs, unseen becomes NULL silently |
| `error()` inside a `CASE` raises only for unseen rows (`E/ordinal.md:L104-113`) | not reached, see above | Unverified for the real path |
| `Corr` pairwise-complete NULL handling (`A/corr.md:L194`) | `CORR(a,b)` ignores pairs with a NULL: 1.0 on a toy set | Confirmed |
| `low_node` Median `AVG(x) WHERE rn IN (floor((n+1)/2), ceil(...))` (`A/median.md:L108-118`) | with two NULL rows in 1,2,3,4: **3.5**; native 2.5. Correct only with no NULLs | **Wrong with NULLs** |
| `low_node` Quantile ranking (`A/quantile.md:L108-128`) | with two NULL rows, q=0.25: **2.25**; native 1.7 | **Wrong with NULLs** |
| `low_node` Corr sums (`A/corr.md:L90-98`) | with NULL pairs: **-0.0585**; native 0.9934 (uses `COUNT(*)`) | **Wrong with NULLs** |
| `low_node` Std one-pass (`A/std.md:L86-93`) | on 1e9+1, 1e9+2, 1e9+3: **0.0**; native 0.8165. The page admits instability (L95) but not total loss | Confirmed unstable |
| `low_node` Mode `ORDER BY freq DESC, val ASC LIMIT 1` (`A/mode.md:L94-107`) | 1 for 3,1,3,1,2,NULL | Confirmed |
| `SUM` uses Kahan compensation (`A/sum.md:L174`) against naive `AVG` (`A/avg.md:L163`) | 10 x 0.1 gives 1.0 for `sum`, `fsum`, `sumkahan` alike; `avg` and `favg` both 0.1 | Inconclusive; the two pages disagree with each other |
| `SIN(2*pi*25/24)` equals `SIN(2*pi*1/24)` (`E/cyclical_encode.md:L216`) | 0.2588190451025211 against 0.25881904510252074: equal to 15 digits, not bit-equal | Confirmed to ULPs |
| `"10" < "9"` for the string-form sort (`E/one_hot.md:L94`) | `'10' < '2' < '9'` | The caveat the April pages noted still holds |
| `SELECT DISTINCT *` on a table with a primary key never drops anything | trivially true (every key differs); the page handles it by `EXCLUDE` or `PARTITION BY` (`F/distinct.md:L59-63`) | Sound (inference) |

## New against the baseline

- **Aggregates as public steps** with `where=` and `group_by=`, a sibling
  convention (`Mean`/`Avg`), `result_` and `categories_` on the substep,
  and the aggregate-as-value pattern `Impute(value=Mean())`
  (`OLD:I/impute.md:L24-38`). The baseline has `custom(learn={...})`
  templates and `discover()`; this is a cleaner idea of one learned scalar
  per named step. Worth keeping, given the new fit design.
- **Per-group fit as a core feature**: `group_by=` on any step gives per-group
  statistics and a join at transform (`OLD:S/standard_scale.md:L76`,
  `OLD:I/impute.md:L61`). Not in sklearn; needs an ADR.
- **The `natives` tier model and `engine_alias` cascade**, and the explicit
  alias-rejection rule (never substitute a name whose meaning changes
  between engines). The baseline had only "transpilation is syntactic, not
  semantic". This is the first written rule for engine divergence, and a
  reason to keep any multi-engine work behind DuckDB `ATTACH` (baseline).
- **Errors that contain the SQL**: the `Ordinal` unseen-category message is
  built at learn time and embedded as the argument of `error()` in the
  generated `CASE`, so the engine raises it (`OLD:E/ordinal.md:L83-113`).
  A transform that fails closed inside the query, with no Python round trip.
  The idea is good; the `= 0` test it relies on is wrong (checked).
- **Filters as a family** (`Filter`, `DropNulls`, `Distinct`, and reserved
  `Sample`, `Limit`, `Head`, `Tail`, `OLD:F/README.md:L239-253`). The April
  set had Filter, Sample, Deduplicate inside `ops/`. New: the
  `DropNulls = Filter("c IS NOT NULL")` identity as a documented, not
  inherited, relation (`OLD:F/drop_nulls.md:L14-20`); `Distinct` keep modes
  `first`, `last`, `none` with a primary-key tie-break; NULL equals NULL for
  dedup; `SubsetEmptyError` and `PKReferencedError`
  (`OLD:F/distinct.md:L277-288`).
- **A framework row key, `_sqlearn_primary_key`**, injected at load, excluded
  from comparisons, stripped and re-injected at union boundaries
  (`OLD:F/distinct.md:L59-63`, `L178-182`). A concrete answer to "which row
  is first" for dedup, and a possible handle on `y` alignment (inference).
- **`DistinctValues` as the vocabulary substep** of `OneHot` and `Ordinal`
  with an `over="columns" | "rows"` choice (`OLD:A/distinct_values.md:L23-26`).
  A category list is an aggregate result like any other.
- **`Corr` as a two-column aggregate** with a written carve-out from the
  collection rule (`OLD:A/corr.md:L13-22`); `Count` is explicit that it is
  not a row count, with `RowCount` reserved (`OLD:A/count.md:L9`, `L204`).
- **A Validation section per step** with a formula, a primary source
  (DLMF, NIST, MathWorld), the library defaults that differ (ddof, tie,
  Cleveland against Hyndman-Fan, polars `nearest`), and an expected-ULP row
  (`OLD:A/quantile.md:L263-267`, `OLD:A/std.md:L181`). Still no parity run.
- **Reserved parameters**: `Quantile(method=)` accepts only `linear` but
  reserves the other numpy names (`OLD:A/quantile.md:L21`); `Corr(method=)`
  reserves `spearman`, `kendall` (`OLD:A/corr.md:L33`).
- **`CyclicalEncode`** (period required, no default, source kept)
  and its warning that `columns=None` applies one period to every numeric
  column (`OLD:E/cyclical_encode.md:L101`). Not present in April.
- **`OneHot` output named `<col>_<category>`** with a category sanitiser left
  open (`OLD:E/one_hot.md:L328`); `new_column=` length checked at learn
  because the width is data-dependent (`OLD:E/one_hot.md:L24`).

## Contradicts the baseline

- **Unseen categories.** April: `OneHot` gives zeros and `Ordinal` gives NULL
  (April batch C, `onehot.md:L62-65`, `ordinal.md:L63-65`). War room: error
  by default, `handle_unknown="use_encoded_value"` opt-in for `Ordinal`,
  and a proposed `OneHotIgnore` sibling for `OneHot`
  (`OLD:E/one_hot.md:L127-135`, `OLD:E/ordinal.md:L23`). Matches
  scikit-learn's defaults but breaks the "NULL preserved" rule, and the
  `Ordinal` path is broken (checked).
- **NULL in `OneHot`.** April filtered NULL from the categories (all-zero
  row). War room makes NULL a category and adds a column, with the suffix
  left open (`OLD:E/one_hot.md:L137`, `L331`). scikit-learn also treats
  missing as a category when present in training.
- **`OneHot` output dtype and column naming are self-contradictory:** `Bool`
  at `OLD:E/one_hot.md:L67`, `INTEGER` at `L106`, and the example uses 1/0
  (`L77`). `Log`'s AST aliases `price_log` (`OLD:T/log.md:L53`) while its
  constructor says it replaces in place (`L20`).
- **`MinMaxScale` now has `feature_range`** and a short-circuit for (0, 1)
  (`OLD:S/min_max_scale.md:L22`, `L41-49`); April said it had none, on
  purpose.
- **`Log` is bare `LN(x)`** with no `log1p` offset, no base (April: offset 1,
  optional base, `log.md:L24-31`), and its siblings `SignedLog`,
  `SignedSqrt` are deferred (`OLD:T/log.md:L117`). It is not a drop-in for
  `FunctionTransformer(np.log1p)`.
- **`Sqrt` wraps negative to NULL** (`OLD:T/sqrt.md:L99-106`). April said
  "NULL in most dialects" and the baseline checked NaN. The war room cites a
  raise instead; neither the raise nor NULL is what DuckDB 2.0.0 does for a
  bare call (checked), so the wrapper is needed for NULL but not for the
  reason given. `Log` takes the opposite stance (engine decides). The
  two pages are inconsistent about the same principle.
- **`Impute` has no default strategy**: `value=` is required and `"mean"`
  is a plain string literal (`OLD:I/impute.md:L38`). April defaulted to
  `mean` with `"mean"`, `"median"`, `"mode"` sugar. scikit-learn
  defaults to `mean`; this is a departure that would need an ADR.
- **April's "dynamic means has a fit query"** is replaced by the opposite
  reading (see Spec families). Scalers and imputers move from dynamic to
  static (`OLD:S/standard_scale.md:L11`).
- **Constant column**: April spec wrote literal `0` for `Scale`/`MinMax`,
  the war room writes NULL by a division rule that is false (checked).
- **"Pipelines of static steps collapse into a single learn_apply query"**
  (`OLD:E/cyclical_encode.md:L13`) contradicts the baseline's staged fit
  unless "static" excludes any step that reads a learned scalar; `Impute`
  with an aggregate and `StandardScale` are classed static but do.

## Confirms the baseline

- **Population statistics** (`STDDEV_POP`, `VAR_POP`, ddof=0) as scikit-learn's
  choice, and the `x / NULLIF(scale, 0)`-style guard being absent from the
  scalers is the same gap as April (`OLD:S/standard_scale.md:L119`).
- **Interpolating quantile is what scikit-learn uses**; the baseline's
  checked fact is repeated and the discrete form is named a trap.
- **Ordered `MODE` is the only deterministic form**
  (`OLD:A/mode.md:L186-188`), as the baseline found.
- **Learned values inlined as literals** (`OLD:S/standard_scale.md:L65`,
  `OLD:I/impute.md:L52-56`), including the float-literal problem the
  baseline notes (the example substitutes `42.7`).
- **Row-level steps fold into one `SELECT`; whole-query steps need a CTE.**
  Filters fold into `WHERE`; keyed `Distinct` needs a window CTE and is
  "the one filters step that is not a pure `WHERE`-fold"
  (`OLD:F/distinct.md:L104-106`). The baseline's two kinds of step stand.
- **No scikit-learn parity test, no pipeline-level comparison, no data**
  ("Populated when the validator lands" on every page). The baseline's
  validation bullet holds.
- **Planning outgrew the product again**: 7,640 lines of spec for 26 steps
  and no code in this batch; the identical 150-line README and the
  5-dialect `natives` blocks repeated per page.
- **The target is never excluded or mentioned**; `y` as a column name never
  appears. Consistent with "never excluded the target".
- **Worth-keeping SQL idioms reappear**: `STDDEV_POP`, `VAR_POP`, ordered
  `MODE`, `COALESCE`, `CASE WHEN`.
- **`MissingIndicator` must run before `Impute`**; the README example shows
  it (`OLD:I/README.md:L56`), as the April note found.

## Worth keeping

- The aggregate-as-step idea with one learned value per step; composing
  `Mean` and `Std` into a scaler as substeps; `where=` and `group_by=`
  pushed down to substeps.
- The alias-rejection rule, and the table of which names mean different
  things on different engines (`STDDEV`, `VARIANCE`, `MODE`, `LOG`).
- `STDDEV_POP`/`VAR_POP`/`QUANTILE_CONT`/`mode(x ORDER BY x)` as the exact
  spellings, each with its reason on the page.
- Filters as `static`, row-count-changing, with a stable row key and
  `keep=first|last|none`; `DropNulls` as an identity with `Filter`.
- Failing inside the query with `error()` and a message built at fit time,
  once the absent-value test is fixed to `IS NULL`.
- `Count` against `RowCount`, `Sum` empty is NULL, and writing the
  empty, all-NULL and one-row result of every aggregate in its Errors section
  (`OLD:A/std.md:L134-142`, `OLD:A/var.md:L173-178`).
- The "defaults divergence" lists (ddof, tie, quantile type, `na.rm`) as the
  input for the test bound the baseline lacks.
- Reserving parameter names (`method=`, `feature_range=`) so the API can
  grow without breaking.
- Not worth keeping: the `Mean`/`Avg` pair, the five-engine `natives`
  blocks and warning machinery, the repeated READMEs, gettext ids per page,
  and the `low_node` bodies (wrong with NULLs, checked).

## Files covered

- [x] `OLD:A/README.md`: aggregate family, three modes, `natives`, catalog.
- [x] `OLD:A/avg.md`: `AVG`, SQL-vocabulary sibling of `Mean`.
- [x] `OLD:A/corr.md`: Pearson `CORR`, two positionals, MySQL/SQLite polyfill.
- [x] `OLD:A/count.md`: non-NULL `COUNT`, empty gives 0, `RowCount` deferred.
- [x] `OLD:A/distinct_values.md`: `array_agg(DISTINCT)`, `over=`, NULL kept.
- [x] `OLD:A/max.md`: `MAX`, `drop_nulls=True` default, empty NULL.
- [x] `OLD:A/mean.md`: `MEAN` on DuckDB, `AVG` elsewhere, silent fallback.
- [x] `OLD:A/median.md`: `MEDIAN` as `QUANTILE_CONT`, window `low_node`.
- [x] `OLD:A/min.md`: `MIN`, selection-only, used by `MinMaxScale`.
- [x] `OLD:A/mode.md`: ordered `mode`, smallest tie, bare form rejected.
- [x] `OLD:A/quantile.md`: `QUANTILE_CONT`, `q` required, `method` reserved.
- [x] `OLD:A/std.md`: `STDDEV_POP`, bare `STDDEV` rejected, SQLite sums.
- [x] `OLD:A/sum.md`: `SUM`, empty is NULL, NaN policy not exposed.
- [x] `OLD:A/var.md`: `VAR_POP`/`VAR_SAMP`, `ddof` 0 or 1, `Std^2 = Var` pact.
- [x] `OLD:E/README.md`: encoder family, learned against static encoders.
- [x] `OLD:E/cyclical_encode.md`: static sin/cos, required `period`, additive.
- [x] `OLD:E/one_hot.md`: `CASE` fan-out, error on unseen, NULL category.
- [x] `OLD:E/ordinal.md`: `list_indexof - 1`, `error()` branch that never fires.
- [x] `OLD:F/README.md`: row-filter family, `WHERE` fold, deferred members.
- [x] `OLD:F/distinct.md`: windowed dedup, `keep` modes, primary-key tie-break.
- [x] `OLD:F/drop_nulls.md`: `IS NOT NULL` filter, identity with `Filter`.
- [x] `OLD:F/filter.md`: predicate string as `WHERE`, NULL predicate drops row.
- [x] `OLD:I/README.md`: NULL-only missing, `MissingIndicator` before `Impute`.
- [x] `OLD:I/impute.md`: `COALESCE` with literal or aggregate `value=`.
- [x] `OLD:I/missing_indicator.md`: `IS NULL` flag per column, all by default.
- [x] `OLD:S/README.md`: scalers compose aggregates; `NotLearnedError`.
- [x] `OLD:S/min_max_scale.md`: `Min`/`Max` substeps, `feature_range`, NULL
      claim.
- [x] `OLD:S/standard_scale.md`: `Mean`/`Std` substeps, ddof=0, NULL claim.
- [x] `OLD:T/README.md`: stateless per-row transforms, three-step catalog.
- [x] `OLD:T/abs.md`: `abs`, dtype preserved, 0 ULP.
- [x] `OLD:T/log.md`: bare `LN`, engine decides domain, `SignedLog` deferred.
- [x] `OLD:T/sqrt.md`: `CASE` wrapper to NULL on negative, `SignedSqrt`
      deferred.

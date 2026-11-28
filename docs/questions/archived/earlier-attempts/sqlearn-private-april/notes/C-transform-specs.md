---
type: note
tags: [sqlearn, transformers, specs, duckdb, design-review]
summary: "Batch C review of archived sqlearn-private transformer and helper specs, with checked DuckDB claims and taxonomy of transform kinds."
related: [docs/questions/archived/earlier-attempts/sqlearn-private-april/notes/C-transform-specs.md]
mdindex: [type=edb465, tags=f55595, summary=e8bcd5]
---
# Batch C: transformer and helper specs (sqlearn-private, April 2026)

Source: OLD is
`.../sqlearn-ecosystem_old/sqlearn-private` (GitHub `glaucis/sqlearn-private`,
9-24 April 2026). Citation shorthand, all under
`OLD/_old/projects/sqlearn/src/`:

- `OLD:T/x.md:Ln` is `transforms/x.md` line n.
- `OLD:H/x.md:Ln` is `helpers/x.md` line n.

Nothing in OLD was run. The DuckDB facts marked "(checked)" were run by
me on DuckDB v2.0.0 with the `duckdb` CLI against literals, not against OLD.
Everything marked "(inference)" is my reading, not a quotation. Line numbers
are those of the files as read (blank lines counted).

The files are specifications, not code: each page describes a step that the
v0.4 code (batch C of the v0.4 review) implemented. Where this note says
"spec", it means the page; where it says "v0.4 code", it means the earlier
review's reading of `src/sqlearn/transforms/`.

## Summary

- 88 transformer files (11 `INDEX.md`, 77 specs, about 81 classes) and 25
  helper files. 52 specs are `classification: static`, 19 `dynamic`, 6
  `hybrid`; 76 are `shipped`, one (`CollapseRare`) `parked`
  (`OLD:T/encoders/collapse_rare.md:L3`). Version tags: 8 at 0.1.0, 37 at
  0.2.0, 25 at 0.3.0, 6 at 0.4.0.
- The specs are the *design* behind the v0.4 code, and they are looser than
  the code. They fix none of the eight known departures. Two of them
  (FrequencyEncode, GroupAggregate computing statistics at apply time) are
  written down as deliberate behaviour, with a learned sibling, `CountEncode`,
  offered as the alternative (`OLD:T/encoders/count_encode.md:L15-21`).
- The static/dynamic/hybrid axis means "has a fit query", not "uses data
  statistics". `FrequencyEncode`, `GroupAggregate` and every window step are
  `static` yet read the whole input at transform time. That is the fit/
  transform leak from the baseline, built into the taxonomy.
- Two kinds of step are explicit: row-expression steps (`expressions()`, one
  flat `SELECT`) and whole-query steps (`query()`, a subquery boundary). A
  third axis, schema-changing, forces a "layer boundary". Row-count change has
  no rule beyond an "alignment warning" (`OLD:T/ops/deduplicate.md:L64-66`).
- The spec for `QuantileScale` and `Winsorize` names `PERCENTILE_CONT`
  (`OLD:T/scalers/quantile_scale.md:L46-50`, `OLD:T/outlier/winsorize.md:L31`),
  which is the continuous function (checked: 2.5 for 1,2,3,4, same as
  `QUANTILE_CONT`; `QUANTILE` gives 2.0). `RobustScale` names plain
  `QUANTILE` (`OLD:T/scalers/robust_scale.md:L32-33`). So the v0.4 code
  drifted from some of its own specs; the spec set is inconsistent.
- Several spec claims about DuckDB are wrong (checked): `SQRT(-1)` is NaN, not
  NULL; `TRIM` does not remove tabs or newlines; `BinaryEncode`'s SQL gives
  fractions, not bits; `VAR_POP` of an all-NULL column is NULL, not 0;
  `POW(0,-1)` is `inf`.
- `CollapseRare` is the richest spec: a 21-row "Rule 0" options catalogue, a
  12-row options matrix that becomes 12 tests, and a staged fit written as a
  `WITH collapsed AS (...)` CTE feeding a later learning step
  (`OLD:T/encoders/collapse_rare.md:L282-301`). It confirms the baseline's
  staged-fit idea. Its own apply-time example then contradicts itself (see
  Contradicts).
- Helpers: the part that bears on the core is `explore_caching.md` (planned
  v0.7): per-fold statistics in one scan with `FILTER (WHERE __sq_fold__ !=
  :k)` and a `CROSS JOIN stats` CTE (`OLD:H/explore_caching.md:L540-548`),
  two-phase discovery (category universe from the full training data, values
  per fold), a `FILTER`-versus-subset test across ten aggregates, and a
  `FILTER` to `CASE` fallback for other engines.
- `check.md` (planned v1.0) lists 11 rules; one is "target in features: a real
  bug that costs users hours" (`OLD:H/check.md:L106`), which confirms the
  baseline's finding that no attempt excluded the target from default columns.
- Planning outgrew the product again: two planned helpers are 1,899 and 1,343
  lines (`connection_management.md`, `explore_caching.md`), more than the whole
  `transforms/` tree's largest page (639).

## Spec template and taxonomy

### The template

Every spec page follows one shape (`OLD:T/scalers/scale.md:L1-150` is
typical):

1. Front matter: `title`, `status` (`shipped` or `parked`), `introduced`
   (version), `classification` (`static`, `dynamic`, `hybrid`), `keywords`.
2. H1 and a one-paragraph definition that names the scikit-learn equivalent
   ("is the sqlearn equivalent of sklearn's `StandardScaler`").
3. `## Behavior`: `### What gets learned` (the `discover()` aggregates, keys
   `{col}__{stat}`), `### Produced expressions` (the SQL), guards (constant
   column, zero division), default column routing, schema effect.
4. `## Interface`: the class skeleton with `_default_columns` (`"numeric"`,
   `"categorical"`, `"temporal"`, `"all"` or `None`), `_classification`, the
   `__init__` signature (keyword-only, `columns=`, `**kwargs`), then `Usage`.
5. `## Dependencies`: base class, siblings, helpers.
6. `## Rationale` in about a third of the pages, as Context, Options
   considered, Decision, Consequences (for example
   `OLD:T/scalers/scale.md:L106-150`, `OLD:T/encoders/onehot.md:L123-181`,
   `OLD:T/branch.md:L148-212`).

`CollapseRare` adds a Parameters table, a master options catalogue ("Rule 0":
`where=`, `group_by=`, `out_column=`, `cv=`, NULL input, empty input, schema
drift, serialisation, portability, 21 rows,
`OLD:T/encoders/collapse_rare.md:L212-240`), an options matrix of 12 rows each
named as a test (L242-260), an end-to-end compiled-SQL example (L262-335), and
a reference implementation sketch (L441-611). It is the only page with a NULL
rule, an empty-input rule and a test list.

### What the template lacks

No page has: a scikit-learn parity test or tolerance; a "known departure"
section; behaviour on all-NULL, empty or constant input (except `CollapseRare`
and the constant guards of four scalers); NULL-versus-NaN handling; the
DuckDB version the SQL was checked on. Claims about DuckDB are asserted, not
tested, which is how the wrong ones in the Summary survived.

### Taxonomy

| Kind | How it computes | Members (pages) |
|---|---|---|
| Static row-expression | `expressions()`: one expression per column, composed into one `SELECT` | arithmetic (14), string (6 of 8), datetime (5), Binarize, Clip, Ratio, Interaction, Polynomial, Cast, Drop, MissingIndicator, HashEncode, Normalize, Expression |
| Dynamic row-expression, scalar stats | `discover()` returns aggregate ASTs; results inlined as literals | Scale, MinMax, MaxAbs, Robust, Quantile, Power, Impute, Winsorize, OutlierHandler (clip), Bin, CountEncode, TargetEncode, DropLowVariance, DropCorrelated, SelectKBest, SelectPercentile |
| Dynamic, set-valued | `discover_sets()` returns a multi-row query (categories, keep set) | OneHot, Ordinal, BinaryEncode, CollapseRare (`OLD:T/encoders/onehot.md:L125-145`) |
| Schema-changing or adding | overrides `output_schema()`; "layer boundary" | OneHot, Cyclical, StringLength, DateDiff, DateParts, Drop, Cast, Rename, selection, Interaction, Polynomial |
| Whole-query (`query()`) | wraps the upstream query as a subquery | Filter, Sort, Sample, Deduplicate, Rename, FrequencyEncode, GroupAggregate, Lookup, OutlierHandler (remove), SQL (query mode), all window steps |
| Composite or wrapper | fans the contract out to children | Union (`{branch}__{col}`), Branch (`CASE WHEN`, per-branch `b{i}__` keys), TargetTransform, custom(), SQL |

Notes on the taxonomy:

- The classification is declared (`_classification`, "Tier 1") and checked by
  a parametrised CI test, `test_declaration_matches_reality`
  (`OLD:T/encoders/collapse_rare.md:L173-185`), against criteria D1b and
  SC1-SC4 that live in `compiler/classify.md` (not in this batch).
- `Union` and `Branch` classify themselves from their children (`_classify()`,
  `OLD:T/union.md:L46-53`, `OLD:T/branch.md:L66-71`); `custom()`, `SQL` and
  `Bin` classify from their arguments (`OLD:T/custom.md:L78-85`,
  `OLD:T/binning/bin.md:L67-70`).
- `custom()` is a template with a `learn=` dict of aggregate templates:
  `custom("{col} - {mean}", learn={"mean": "AVG({col})"})`, keys namespaced
  `{col}__{param}` (`OLD:T/custom.md:L43-62`, L228-233). It has five contract
  checks, C1-C5 (L122-132) and a three-level ladder: built-in, `Expression`,
  `custom()`, subclass, `SQL` as last resort (`OLD:T/sql.md:L176-182`).
- Output naming is still ad hoc: `{col}_missing`, `{a}_x_{b}`,
  `{num}__div__{den}`, `{col}__sin`, `{col}_bit_k`, `{col}_hash_k`,
  `{col}_lag_n`, `{col}_rmean_n`, `rank`, `row_number`.

## Per-transformer table

Legend: "learns" is what `fit` computes; "SQL" is the transform expression;
"NULL" is what the spec says or leaves unsaid. "Spec silent" means the page
does not say.

### Scalers (`OLD:T/scalers/`)

| Step | sklearn | Learns and SQL | NULL, constant, empty |
|---|---|---|---|
| Scale (`scale.md`) | StandardScaler | `AVG`, `STDDEV_POP` (L33-34); `(CAST(x AS DOUBLE) - mean) / std` (L48) | std 0: literal `0` for the column (L58-64). NULL: spec silent, and a literal `0` would turn NULL into 0 (inference) |
| MinMaxScale (`minmax_scale.md`) | MinMaxScaler | `MIN`, `MAX` (L32-33); `(x-min)/(max-min)` baked (L44-50) | max=min: literal `0` (L52-57). No `feature_range` (L122-139), deliberate |
| MaxAbsScale (`maxabs_scale.md`) | MaxAbsScaler | `MAX(ABS(x))` (L31); `x / NULLIF(max_abs, 0)` (L38) | Contradicts itself: all-zero gives NULL (L43-44) and also literal `0` "matches sklearn" (L55-56) |
| RobustScale (`robust_scale.md`) | RobustScaler | `MEDIAN`, `QUANTILE(x, lo)`, `QUANTILE(x, hi)` (L31-33); `(x-median)/NULLIF(q3-q1, 0)` (L43) | IQR 0 gives NULL (L48-49). sklearn gives `x - median` (scale 1). Not the v0.4 code's `0` either |
| Normalize (`normalize.md`) | Normalizer | static; `x_i / NULLIF(norm, 0)` with l1, l2, max norms (L29-42) | Zero row gives NULL, documented as a deliberate departure from sklearn's 0 (L57-62). A NULL in the row nulls the whole row (inference) |
| PowerScale (`power_scale.md`) | PowerTransformer | lambda by "maximum-likelihood ... Python-side" (L24-43); piecewise Yeo-Johnson `CASE` (L45-55) | Box-Cox raises on zeros or negatives at fit (L65-66). No `standardize`. NULL silent |
| QuantileScale (`quantile_scale.md`) | QuantileTransformer | `PERCENTILE_CONT` boundaries, `n_quantiles=100` (L39-50); step `CASE WHEN x <= q_i THEN i/n` (L55-63) | A step function, not sklearn's interpolation. `ELSE 1.0` so NULL lands in the top bucket (inference, checked: `CASE WHEN NULL < 5 ... ELSE` takes ELSE) |

### Imputation, indicators, fill

| Step | sklearn | Learns and SQL | NULL, constant, empty |
|---|---|---|---|
| Impute (`impute.md`) | SimpleImputer | `AVG`, `MEDIAN`, `MODE(col)` or constant (L25-30); `COALESCE(x, fill)` (L44-52) | Only NULL is missing, no NaN. `MODE(col)` has no `ORDER BY`. Default strategy `mean`, default columns `all` (L57-58, L118-121). All-NULL column: spec silent |
| MissingIndicator (`missing_indicator.md`) | MissingIndicator | static; `CASE WHEN x IS NULL THEN 1 ELSE 0 END AS x_missing` (L34-37) | Default flags **every** column (L72). Must run before `Impute` (L58-61) |
| FillForward/Backward (`fill.md`) | none (pandas) | static; `COALESCE(x, LAST_VALUE(x IGNORE NULLS) OVER (ORDER BY o ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))` (L45-48) | Leading NULLs stay NULL (L52-53). Stateless: a test set gets no history (inference). ORDER BY ties unspecified |

### Encoders (`OLD:T/encoders/`)

| Step | sklearn | Learns and SQL | NULL, unseen |
|---|---|---|---|
| OneHot (`onehot.md`) | OneHotEncoder | `SELECT DISTINCT` per column, sorted by string (L28-35, L55-58); `CASE WHEN x='c' THEN 1 ELSE 0 END` | NULL filtered from categories, NULL row gives all zeros (L62-65). Unseen gives zeros. Always drops the source (L172-175). `"10" < "9"` caveat (L162-164) |
| Ordinal (`ordinal.md`) | OrdinalEncoder | distinct values, sorted; `CASE ... ELSE NULL` (L44-52) | Unseen gives NULL. Spec says this is sklearn's default (L63-65); sklearn's default is `handle_unknown="error"` (my knowledge, not checked here) |
| BinaryEncode (`binary_encode.md`) | category_encoders | distinct values; `(CASE ... END / POW(2, k)) % 2` (L65-73) | Unseen gives NULL bits. The SQL is wrong (checked: `5/POW(2,1)%2` = 0.5; integer division is `//`) |
| CountEncode (`count_encode.md`) | none | `HISTOGRAM(col)` at fit (L34-37); `CASE ... ELSE unseen_value` | Learned, frozen; unseen gives `unseen_value`=0 (L53-60) |
| FrequencyEncode (`frequency_encode.md`) | none | **static**; `COUNT(*) OVER (PARTITION BY x) / COUNT(*) OVER ()` at transform time (L32-43) | Spec: "recalculated every time ... against whatever data is being transformed" (L57-60) |
| HashEncode (`hash_encode.md`) | FeatureHasher | static; `CASE WHEN ABS(HASH(x)) % n = i THEN 1 ELSE 0 END` (L35-39) | NULL spec silent. Cross-backend instability noted (L57-68), cross-version not (checked: `HASH` is UBIGINT) |
| TargetEncode (`target_encode.md`) | TargetEncoder | per-category `AVG(y)`, `COUNT`, global mean; `(n*m + s*g)/(n+s)`, `smooth=1.0` (L31-51) | Unseen gives the global mean (L71-73). No cross-fitting (the leak in training) and no `smooth="auto"`. Needs target |
| CollapseRare (`collapse_rare.md`, parked) | none | `SELECT x GROUP BY x HAVING COUNT(*) >= min_count` (L42-48); `CASE WHEN x IN (...)` | NULL is a value, kept or collapsed by `min_count` (L83-103). Rejects continuous floats (L105-130) |

### Arithmetic, binning, outliers

| Step | sklearn | SQL | NULL, domain |
|---|---|---|---|
| Abs, Ceil, Floor, Sign, Exp | FunctionTransformer | `ABS`, `CEIL`, `FLOOR`, `SIGN`, `EXP` | Static; NULL propagates (inference) |
| Sqrt (`sqrt.md`) | FunctionTransformer | `SQRT(x)` | Spec: "Negative inputs produce NULL in most dialects (DuckDB, Postgres)" (L20); checked: NaN on DuckDB |
| Log (`log.md`) | log1p | `LN(x + offset)`, offset 1, optional `/ LN(base)` (L24-31) | Change of base chosen "for portability" (L34-37). No domain guard |
| Log2, Log10 | FunctionTransformer | `LOG2(x)`, `LOG10(x)` | Spec: "NULL in most dialects" (`log2.md:L24`); checked: NaN. Inconsistent with Log's rationale |
| Power | FunctionTransformer | `POW(x, e)` | Spec: "NULL or error depending on dialect" (`power.md:L29-31`); checked: `POW(0,-1)` = inf, `POW(-8,.5)` = NaN |
| Reciprocal | FunctionTransformer | `1.0 / NULLIF(x, 0)` | Zero gives NULL (numpy gives inf), documented (L24-30) |
| Round (`round.md`) | FunctionTransformer(np.round) | `ROUND(x, d)` | Half-even not mentioned (checked: `ROUND(2.5)` = 3) |
| Binarize | Binarizer | `CASE WHEN x > t THEN 1 ELSE 0 END` | NULL gives 0 (inference, checked CASE rule) |
| Clip (`clip.md`) | none | `GREATEST(LEAST(x, u), l)` (L22-31) | NULL becomes the bound (checked, see below); spec silent |
| Bin (`binning/bin.md`) | KBinsDiscretizer | `CASE WHEN x < e1 THEN 0 ... ELSE n-1` (L45-51); strategies uniform, quantile, custom | NULL falls to `ELSE` (inference). The worked example gives 5 edges and 4 thresholds starting at the minimum, so bin 0 is empty (inference, L43-51). No `kmeans` |
| Winsorize (`winsorize.md`) | none | `PERCENTILE_CONT(x, 0.05/0.95)`; `GREATEST(LEAST(...))` (L31-44) | NULL becomes the lower bound (inference) |
| OutlierHandler (`outlier_handler.md`) | none | IQR (`Q1`, `Q3`, factor 1.5) or z-score; `clip` or `remove` via `query()` WHERE (L26-65) | `remove` drops rows (see row-count section). Quantile function unnamed |

### Datetime, string, window

| Step | Equivalent | SQL | Notes |
|---|---|---|---|
| DateParts | none | `EXTRACT(part FROM x)`, source kept (L28-38) | `DOW`: 0=Sunday on DuckDB (`is_weekend.md:L27`) |
| DateDiff | none | `DATEDIFF('DAY', ref, x)`; reference is a column or an ISO literal by shape (L45-50) | Checked: DuckDB `date_diff` counts boundaries crossed (23:00 to 01:00 next day = 1 day). Spec silent |
| IsWeekend, Quarter | none | `CASE WHEN EXTRACT(DOW ...) IN (0,6)`; `EXTRACT(QUARTER ...)` | NULL gives 0 in IsWeekend (inference) |
| Cyclical | SplineTransformer(periodic) | `SIN(2*PI()*x/period)`, `COS(...)`, source dropped (L33-42) | Table maps both `"hour"` and `"day"` to 24 (L51) |
| Lower, Upper, Trim, Replace, Substring | none | `LOWER`, `UPPER`, `TRIM`, `REPLACE`, `SUBSTRING` | `trim.md:L23-25` says TRIM strips tabs and newlines; checked: it strips spaces only |
| StringLength, StringStats, RegexExtract | none | `LENGTH`; word count `ARRAY_LENGTH(STR_SPLIT(TRIM(x), ' '))` (`stats.md:L54`); `REGEXP_EXTRACT(x, p, g)` | Word count splits on single spaces, yet the table says whitespace (L32); empty string gives 1 (checked: `str_split('', ' ')` has one element) |
| Lag, Lead | none | `LAG(x, n) OVER (PARTITION BY p ORDER BY o)` (L31-33) | First n rows NULL (L59-63). `Lead` suggested for target construction (`lead.md:L38-43`) |
| RollingMean, RollingStd | none | `AVG`, `STDDEV_POP` over `ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW` | `n` >= 2; short windows at the start are not discussed (inference) |
| Rank, RowNumber, Cumulative* | none | `RANK/DENSE_RANK/ROW_NUMBER() OVER`; `SUM/MIN/MAX/COUNT ... UNBOUNDED PRECEDING` | Ties "broken arbitrarily" (`rank.md:L27`, `row_number.md:L17`); no tiebreak column |

### Selection, ops, composition

| Step | sklearn | Learns and SQL | Notes |
|---|---|---|---|
| DropLowVariance | VarianceThreshold | `VAR_POP`; drop if `<= threshold` (L28-29) | Claims all-NULL variance is "typically 0 in SQL" (L36); checked: NULL |
| DropCorrelated | none | pairwise `CORR`, greedy drop by pair count (L27-39) | Greedy, ties by column order |
| SelectKBest, SelectPercentile | same names | `\|CORR(x, y)\|` only; `f_classif`, `chi2` deferred (`select_k_best.md:L30-35`) | Target required; `percentile` keeps `max(1, ceil(p*N))` |
| Filter, Sort, Sample, Deduplicate | none | `WHERE`; `ORDER BY`; `USING SAMPLE 10% (reservoir, 42)`; `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY __sqlearn_rid__)` | Row-count section below |
| Drop, Rename, Cast | none | empty `expressions()` plus schema change; aliasing; `CAST` | Cast type string embedded verbatim (L42-46) |
| GroupAggregate | none | **static**; `AVG(x) OVER (PARTITION BY g) AS x_avg_by_g` (L39-45) | Window at apply time (L51-57); aggregates include `MEDIAN` and `MODE(col)` |
| Lookup | none | `LEFT`/`INNER JOIN` to a file or table; `discover()` only resolves the schema (L90-100) | Fan-out on a non-unique key not discussed (inference) |
| Interaction, Polynomial, Ratio | PolynomialFeatures | `a*b`; `POW(a,k)`; `CASE WHEN den = 0 THEN NULL ELSE num/den END` (`ratio.md:L58`) | Ratio `null_on_zero=True` by default |
| Union, Branch | FeatureUnion, none | prefix `{branch}__`; `CASE WHEN cond THEN ... ELSE x END` | Branch learns from all rows: "v0.2 compiler does not yet support filtered aggregates" (`branch.md:L81-88`) |
| TargetTransform | TransformedTargetRegressor | wraps `Log` etc. on the target; `inverse_target()` in Python (L47-60) | Inverse needs `inverse_expressions()` |

## Known departures: fixed or not

| Departure | What the specs say | Fixed? |
|---|---|---|
| `QUANTILE` vs `QUANTILE_CONT` | QuantileScale and Winsorize name `PERCENTILE_CONT`; RobustScale names `QUANTILE`; Bin, OutlierHandler, `distribution()` percentiles name nothing. The FILTER test list uses `PERCENTILE_CONT` (`OLD:H/explore_caching.md:L661`) | Partly, by name, in 2 of 6 places. v0.4 code used `QUANTILE` throughout, so the specs were ahead of the code |
| `MODE` tie-break | `MODE(col)` for Impute (`impute.md:L29`) and GroupAggregate (`group_aggregate.md:L88`); the FILTER test lists bare `MODE` (`explore_caching.md:L662`) | No |
| `LEAST`/`GREATEST` with NULL | Clip, Winsorize, OutlierHandler(clip), Normalize(max) use them; no NULL rule anywhere | No |
| RobustScale IQR 0 | `NULLIF` gives NULL (`robust_scale.md:L48-49`). sklearn: scale 1, so `x - median`. v0.4 code: `0` | No: a third behaviour |
| Constant columns | Scale, MinMax: literal `0`, "matches sklearn" (partly true for non-NULL rows; NULL rows become 0, unmentioned). MaxAbs contradicts itself (NULL, then `0`). `DropLowVariance` removes them upstream | Documented, not fixed |
| `ROUND` half-even | `ROUND(x, d)`, silent | No (checked: 3 for 2.5) |
| MissingIndicator default | all columns, static (`missing_indicator.md:L72`); no "missing-only" learned in fit | No |
| FrequencyEncode learned in fit | static by design; `CountEncode` is the learned version and a table contrasts them (`count_encode.md:L62-70`) | Not fixed; offered as a separate step. `GroupAggregate` has no learned twin |
| Row-count-changing steps | `Deduplicate` "emits an alignment warning when row counts change" (L64-66). `Filter` "travels with the deployment artifact" (`filter.md:L143-146`), so it also runs at transform | Not fixed: no fit-only rule, no `y` alignment |

Other departures the specs state or leave: Normalize zero row gives NULL
(stated, deliberate); Reciprocal zero gives NULL (stated); Bin and
QuantileScale NULL falls to the last bucket; Binarize and IsWeekend NULL gives
0; Log, Sqrt, Power have no domain guard; OneHot drops the source and ignores
unseen; TargetEncode has no cross-fitting; PowerScale learns lambda in Python
(see Contradicts).

Row-count-changing steps in the specs: `Filter`, `Sample`, `Deduplicate`,
`OutlierHandler(action="remove")` (`outlier_handler.md:L33-36, L67-68`),
`Lookup(how="inner")`, `Sort` (reorders), `concat()` and `merge()` before the
pipeline. `Deduplicate` depends on a `__sqlearn_rid__` row-identity column
"the compiler automatically injects at pipeline entry (v0.3+)"
(`deduplicate.md:L56-60`). `Sample` takes a seed and uses `USING SAMPLE ...
(reservoir, seed)` (`sample.md:L43-47`); run at transform time it would sample
the data being scored (inference).

## Helpers

25 files, about 6,700 lines. Read fully: `INDEX`, `explore`, `from_sklearn`,
`quick`, `check` (L1-170), `explore_caching` (L1-135, L455-680, L1285-1300),
`connection_management` (L20-100), `profile`, `distribution`, `outliers`,
`cardinality`, `peek`, `merge`, `concat`, `target`, `missing`. Skimmed by
heading or first screen: the rest.

### Bears on the core

- **`explore.md` and `explore_caching.md`** (cross-validation). The v0.4
  `explore()` cached metric floats keyed by the hash of the whole pipeline
  config, so shared-prefix reuse was documented but never delivered
  (`OLD:H/explore.md:L28-38`, `OLD:H/explore_caching.md:L51-110`), the same
  "docs promised, code did not" pattern as the process lessons. v0.7 plans:
  - Two tiers: fitted state in Python dicts, transformed data in a DuckDB
    schema `_meta_exploration_data`, one table per `(prefix_hash, fold,
    split)` (L114-135).
  - Baked versus self-contained compilation: baked for `learn`/`apply`/`sql`;
    self-contained for cross-validation, with a `stats` CTE using `AVG(x)
    FILTER (WHERE __sq_fold__ != :k)` joined by `CROSS JOIN` (L518-561).
    Claimed 5x on 100M rows x 5 folds (inference: a stated estimate, no
    measurement).
  - Two-phase discovery: `discover_sets()` (category universe) from the full
    training data, "not leakage", baked into every fold; `discover()` scalars
    per fold. Zero-variance superset columns are kept in SQL and skipped at the
    numpy/arrow boundary using `MIN = MAX` (L455-516).
  - Fold column `__sq_fold__` from `NTILE(k) OVER (ORDER BY HASH(rowid ||
    seed))`, stratified, grouped and time-series variants (L569-590).
  - `FILTER` fallback to `AVG(CASE WHEN ... THEN x END)` for MySQL, Snowflake,
    BigQuery; a test requires every aggregate used by a transformer to equal
    the subset result for `AVG, MEDIAN, STDDEV_POP, MIN, MAX,
    PERCENTILE_CONT(.25/.75), MODE, COUNT, SUM` (L614-678).
  - Reserved prefix `__sq_*__` is checked on schema reads (L592-612), but
    `__sqlearn_rid__` and `__dedup_rn__` (`deduplicate.md:L46`) do not match
    it (inference: inconsistent names).
- **`check.md`** (planned v1.0): advisory, never raises (L28-29). Leakage
  rules L1-L5 (identifier columns by `COUNT(DISTINCT)/COUNT(*) > 0.99`,
  `ABS(CORR) > 0.95`, constant-after-split, future data, train/test
  duplicates by `INTERSECT`) and mistake rules M1-M6 (scaling before tree
  models, OneHot on more than 100 values, already-binary, already-scaled,
  target in features, redundant steps) (L143-162).
- **`from_sklearn.md`**: maps 16 classes (`StandardScaler` to `Scale`, and so
  on, L24-41); returns an unfitted pipeline and re-learns, because the learned
  state "may differ numerically from sklearn's numpy-based implementations"
  (L56-62). That contradicts `Scale`'s "byte-for-byte agreement" claim
  (`scale.md:L22-24, L121-124`).
- **`quick.md`**: profile, then Impute(mean) and Scale for numerics, OneHot for
  categoricals; `target=` is passed through but no step uses it (L57-61).
- **`connection_management.md`** (planned v0.9, 1,899 lines): named
  multi-connection registry, bring-your-own connection, state migration by
  `EXPORT`/`IMPORT DATABASE`, a four-layer source-inheritance cascade
  (L34-67). Large for a feature the first library core does not need.
- **`profile`, `analyze`, `distribution`, `cardinality`, `missing`,
  `outliers`, `target`**: single-query aggregate profiling (`profile.md:
  L43-53`), eight-tier cardinality classes (`cardinality.md:L40-51`), MAR/MNAR
  hints (`missing.md:L42-51`), outlier method chosen by skewness (`outliers.md:
  L34-39`). `distribution()` reports percentiles and `iqr` without naming the
  quantile function.
- **`normality.md`**: five tests, only Jarque-Bera computable in pure SQL; the
  rest need SciPy, "optional" (L36-40, L146). `outliers` Mahalanobis uses
  numpy (`outliers.md:L121`). Both strain ADR 0004's one-runtime-dependency
  rule (inference).
- **`merge`/`concat`**: pre-pipeline DuckDB views, `__merge_n__`; `merge`
  defaults to `inner` while `Lookup` defaults to `left` (`merge.md:L49`,
  `lookup.md:L74`).
- **`attach`**: wraps DuckDB `ATTACH`, read-only by default. **`peek`**: the
  pipeline's transform with `LIMIT n`, returns a string. **`lineage`**: pure
  derivation, no SQL. **`model_info`**: a static registry of model needs
  (`needs_scaling`, `handles_nulls`) rather than detection. **`help_system`**
  (planned): `.help()` on every step, docs bundled offline. **`explain`**:
  narrative of an `explore()` result.

## New against the baseline

1. **The leak is in the spec.** `FrequencyEncode`
   (`OLD:T/encoders/frequency_encode.md:L15-19, L57-60`) and `GroupAggregate`
   (`OLD:T/group_aggregate.md:L51-57`) are specified `static` with apply-time
   window statistics, and `CountEncode` exists specifically as the learned
   alternative. The earlier review called this a bug; the specs show it was a
   choice, made because the static/dynamic label was tied to "has a fit query".
2. **The spec set disagrees with the v0.4 code** on quantile function (spec
   `PERCENTILE_CONT` for 2 steps), RobustScale IQR 0 (spec NULL, code `0`) and
   PowerScale (spec maximum likelihood, code a skewness grid). A spec per step
   with no test tying it to the code drifted within three days.
3. **Staged fit as CTE, written once** (`OLD:T/encoders/collapse_rare.md:
   L282-301`): fit of a later step reads `collapsed`, the output of an earlier
   step. It is the baseline's idea, in the one page that needed it.
4. **Cross-validation design**: self-contained per-fold CTE with `FILTER`,
   two-phase discovery with the category universe taken from all training
   data, a `__sq_fold__` column from `NTILE` over a hash, and a test that every
   aggregate matches its subset. The category-universe rule is a new decision:
   scikit-learn fits `OneHotEncoder` per fold, so folds can differ.
5. **Row identity**: a compiler-injected `__sqlearn_rid__` at pipeline entry
   (v0.3) used by `Deduplicate` and `outliers()` (`outliers.md:L49-51`). The
   v0.4 review noted `ROW_NUMBER() OVER ()` injected into every query; the spec
   names it a feature.
6. **Spec template extras**: `Rule 0` catalogue, options matrix as tests, C1-C5
   custom-step contract checks, a declared-versus-reality CI test for the
   static/dynamic label. The label test does not catch a mislabel that is
   consistent with the criteria, as in item 1 (inference).
7. **`custom()` with `learn={name: aggregate template}`** is a compact way to
   state any scalar-learning step as SQL, and the first sketch of fit as data
   rather than code.
8. **Checked on DuckDB 2.0.0**, new to the baseline's table:

   | Behaviour | Result |
   |---|---|
   | `5/POW(2,1)%2` | 0.5 (use `//` for integer division) |
   | `TRIM(E'\t x \n')` | length 5, tabs and newlines kept |
   | `SQRT(-1)`, `POW(-8,0.5)`, `LOG2(-1)` | NaN |
   | `POW(0,-1)`, `LN(0)` | `inf`, `-inf` |
   | `CASE WHEN NULL < 5 THEN 0 ELSE 9 END` | 9 |
   | `date_diff('day', 2020-01-01 23:00, 2020-01-02 01:00)` | 1 (boundaries) |
   | `VAR_POP` of one NULL | NULL |
   | `ARRAY_LENGTH(STR_SPLIT('', ' '))` | 1 |
   | `PERCENTILE_CONT(0.5) WITHIN GROUP` on 1,2,3,4 | 2.5, equals `QUANTILE_CONT` |
   | `HASH('a')` | UBIGINT, so `ABS` is safe |
   | `EXTRACT(SECOND ...)` on 5.5 s | 5 (fraction dropped) |

9. **Where the Python/SQL line sits**: PowerScale optimises lambda "Python-side
   ... not cleanly expressible in SQL" (`power_scale.md:L38-40`), which breaks
   ADR 0002 as written. A grid scored by SQL aggregates would keep it in SQL
   (inference).
10. **Process**: 25 helper pages for a library with no stable core; two planned
    pages exceed the whole of `transforms/`' largest. A helper `explore()`
    shipped with a cache that never hit.

## Contradicts the baseline

- **Review table, "`SQRT(-1)` is NaN, no error"**: the spec says NULL in
  DuckDB and Postgres (`OLD:T/arithmetic/sqrt.md:L20`, `log2.md:L24`). The
  baseline is right; the spec is wrong.
- **v0.4 batch C, "FrequencyEncode: design bug (classification static but
  statistical)"**: the spec presents it as intended, with the trade-off
  tabulated against CountEncode. The *defect* stands; the *cause* is a design
  decision, not an oversight.
- **v0.4 batch C, RobustScale emits 0 for IQR 0**: the spec says NULL. Neither
  is scikit-learn's.
- **v0.4 batch C, PowerScale "not MLE"**: the spec says MLE. The spec is a
  claim the code did not meet.
- **Baseline, "nothing in transform may query data"**: `Lookup.discover()`
  resolves a join target's schema, and fold-aware `explore()` queries per fold;
  the spec treats the learn phase as the place where such lookups happen. No
  conflict if `discover` is read as fit-time (inference).
- **`CollapseRare` against itself**: the example header says the apply-time
  query is "all literals" (`collapse_rare.md:L304`), but it recomputes the
  group statistics with `AVG(price) OVER (PARTITION BY ...)` (L313-324), so the
  per-group `Scale(group_by=...)` it demonstrates would again learn from the
  data being transformed. The learned statistics from the fit CTE (L286-301)
  are unused at apply time.
- **Scale "byte-for-byte" with scikit-learn** (`scale.md:L22-24, L121-124`)
  against `from_sklearn.md:L56-62` (results "may differ numerically").
- **`MaxAbsScale`** states both NULL and `0` for an all-zero column (L43-44
  versus L55-56). **`Log`** justifies `LN` plus change of base by dialect
  portability (L34-37), but `Log2` and `Log10` call `LOG2`/`LOG10` directly.

## Confirms the baseline

- **Fit boundary**: the CollapseRare staged CTE (L282-301) is the "learning
  step reads a value an earlier step changed" rule, as a `WITH`. Per-fold
  `FILTER` aggregates in one scan (`explore_caching.md:L540-548`) match the
  baseline's checked claim for `AVG`, `STDDEV_POP`, `MEDIAN`, `MODE`.
- **Learned state as a relation**: the `stats` CTE with `CROSS JOIN`
  (`explore_caching.md:L541-548`) is the baseline's design.
- **Learned state in Python and inlined as literals** (`scale.md:L36-39`);
  keys `{col}__{stat}` (the `__` split risk); `categories` as a list.
- **sqlglot everywhere**, with cross-dialect claims never tested (HASH
  transpiling, DOW, `FILTER` fallback are all "should").
- **`y` is a column name** (`learn("data.parquet", target="price")`,
  `select_k_best.md:L86`), and the target is not excluded from default columns
  (`check.md:L92-107` makes it a warning to catch afterwards).
- **Two kinds of step**: row-expression and whole-query, with the `query()`
  hook; row-count-changing steps need a rule they do not have.
- **Mode, LEAST/GREATEST, ROUND, MissingIndicator, FrequencyEncode** from the
  baseline list all recur unfixed.
- **Process lessons**: hand-typed counts drift (`INDEX` says 8 string
  transforms, `string/` has 8; `transforms/INDEX.md:L32-37` says 7 encoders,
  the folder has 8 including parked CollapseRare); a documented capability
  (`explore` shared prefix) that the code lacked.

## Worth keeping

- The `custom()` shape: `template` plus `learn={name: aggregate template}`,
  namespaced keys, with contract checks C1-C5.
- The four-level ladder (built-in, `Expression`, `custom()`, subclass, `SQL`
  last) and the rule that a raw `SQL` step loses single-`SELECT` composition.
- `CollapseRare`'s "NULL is a value" rule, its reject-continuous-floats check
  and its options-matrix-as-tests habit; the numeric sentinel must be explicit.
- `CountEncode` (learned counts via `HISTOGRAM`, `unseen_value`) as the model
  for any statistic that should be frozen at fit.
- `Normalize`'s documented zero-row departure and `Reciprocal`'s documented
  zero rule: a departure written next to its reason is better than a silent
  one.
- Two-phase discovery's idea: freeze the *schema* (categories) separately from
  the *values* (statistics), and keep schema-stable folds (to be decided; it
  differs from scikit-learn's per-fold fit).
- A `FILTER`-versus-subset test across every aggregate the library uses
  (`explore_caching.md:L658-669`), extended with `QUANTILE_CONT` and
  `MODE ... ORDER BY`.
- `check()` rules L1-L5 and M1-M6 as a checklist for a later advisory layer.
- Names to avoid: `rank` and `row_number` as fixed output names; `{col}_{part}`
  collisions; an output suffix scheme per step.

## Files covered

Legend: [x] read in full, [~] skimmed (headings and first screen).

### transforms/ (88 files)

- [x] `OLD:T/INDEX.md`: table of the 14 top-level specs and 10 subsystems.
- [x] `OLD:T/impute.md`: Impute; MODE with no order; only NULL.
- [x] `OLD:T/missing_indicator.md`: flags every column; flag before impute.
- [x] `OLD:T/fill.md`: forward and backward fill with `IGNORE NULLS`.
- [x] `OLD:T/group_aggregate.md`: static window aggregates; apply-time stats.
- [x] `OLD:T/interaction.md`: pairwise products `a_x_b`.
- [x] `OLD:T/polynomial.md`: powers and interactions; combinatorial growth.
- [x] `OLD:T/ratio.md`: null-on-zero ratios.
- [x] `OLD:T/lookup.md`: LEFT/INNER JOIN; discover resolves schema.
- [x] `OLD:T/target_transform.md`: target wrapper; Python inverse.
- [x] `OLD:T/union.md`: branch-prefixed parallel features; hybrid.
- [x] `OLD:T/branch.md`: CASE routing; learns from all rows.
- [x] `OLD:T/custom.md`: `custom()` with `learn=`; checks C1-C5.
- [x] `OLD:T/expression.md`: Level 1 static template.
- [x] `OLD:T/sql.md`: raw SQL escape hatch, two modes.
- [x] `OLD:T/scalers/INDEX.md`: list of 7 scalers.
- [x] `OLD:T/scalers/scale.md`: StandardScaler; constant column literal 0.
- [x] `OLD:T/scalers/minmax_scale.md`: no `feature_range`.
- [x] `OLD:T/scalers/maxabs_scale.md`: self-contradictory zero rule.
- [x] `OLD:T/scalers/robust_scale.md`: IQR 0 gives NULL; `QUANTILE`.
- [x] `OLD:T/scalers/normalize.md`: zero row NULL by design.
- [x] `OLD:T/scalers/power_scale.md`: MLE claimed, Python-side.
- [x] `OLD:T/scalers/quantile_scale.md`: `PERCENTILE_CONT`, step function.
- [x] `OLD:T/encoders/INDEX.md`: list of 8 encoders.
- [x] `OLD:T/encoders/onehot.md`: DISTINCT, sorted, zeros for NULL/unseen.
- [x] `OLD:T/encoders/ordinal.md`: unseen NULL; wrong sklearn default claim.
- [x] `OLD:T/encoders/binary_encode.md`: bit SQL uses `/` (wrong).
- [x] `OLD:T/encoders/count_encode.md`: learned counts via `HISTOGRAM`.
- [x] `OLD:T/encoders/frequency_encode.md`: static, apply-time proportion.
- [x] `OLD:T/encoders/hash_encode.md`: `ABS(HASH(x)) % n` buckets.
- [x] `OLD:T/encoders/target_encode.md`: smoothed means, fixed smooth.
- [x] `OLD:T/encoders/collapse_rare.md`: parked; Rule 0; staged CTE (read to
  L620 of 639; the last 19 lines are further notes on the sketch).
- [x] `OLD:T/arithmetic/INDEX.md`: list of 14.
- [x] `OLD:T/arithmetic/abs.md`: `ABS`.
- [x] `OLD:T/arithmetic/binarize.md`: strict `>`, default 0.
- [x] `OLD:T/arithmetic/ceil.md`: `CEIL`.
- [x] `OLD:T/arithmetic/clip.md`: `GREATEST(LEAST())`, NULL unstated.
- [x] `OLD:T/arithmetic/exp_transform.md`: `EXP`; file name note.
- [x] `OLD:T/arithmetic/floor.md`: `FLOOR`.
- [x] `OLD:T/arithmetic/log.md`: `LN(x+1)`, change of base.
- [x] `OLD:T/arithmetic/log10.md`: `LOG10`, no guard.
- [x] `OLD:T/arithmetic/log2.md`: `LOG2`; NULL claim wrong.
- [x] `OLD:T/arithmetic/power.md`: `POW`; dialect claim wrong.
- [x] `OLD:T/arithmetic/reciprocal.md`: `1.0 / NULLIF`.
- [x] `OLD:T/arithmetic/round.md`: `ROUND`, half-even unstated.
- [x] `OLD:T/arithmetic/sign.md`: `SIGN`.
- [x] `OLD:T/arithmetic/sqrt.md`: `SQRT`; NULL claim wrong.
- [x] `OLD:T/binning/INDEX.md`: one entry.
- [x] `OLD:T/binning/bin.md`: three strategies; hybrid; worked example off.
- [x] `OLD:T/datetime/INDEX.md`: list of 5.
- [x] `OLD:T/datetime/cyclical.md`: sin/cos; "hour" and "day" both 24.
- [x] `OLD:T/datetime/date_diff.md`: `DATEDIFF`, boundary count unstated.
- [x] `OLD:T/datetime/date_parts.md`: `EXTRACT`, source kept.
- [x] `OLD:T/datetime/is_weekend.md`: DOW 0/6, replaces source.
- [x] `OLD:T/datetime/quarter.md`: `EXTRACT(QUARTER)`.
- [x] `OLD:T/ops/INDEX.md`: list of 7.
- [x] `OLD:T/ops/cast.md`: inline `CAST`, type string verbatim.
- [x] `OLD:T/ops/deduplicate.md`: rid-ordered `ROW_NUMBER`; alignment warning.
- [x] `OLD:T/ops/drop.md`: empty expressions plus schema change.
- [x] `OLD:T/ops/filter.md`: `query()` WHERE; travels with the artefact.
- [x] `OLD:T/ops/rename.md`: aliasing via `query()`.
- [x] `OLD:T/ops/sample.md`: `USING SAMPLE` with seed.
- [x] `OLD:T/ops/sort.md`: `ORDER BY` via `query()`.
- [x] `OLD:T/outlier/INDEX.md`: two entries.
- [x] `OLD:T/outlier/outlier_handler.md`: IQR/z-score, clip or remove.
- [x] `OLD:T/outlier/winsorize.md`: `PERCENTILE_CONT` bounds, clip.
- [x] `OLD:T/selection/INDEX.md`: four entries.
- [x] `OLD:T/selection/drop_correlated.md`: greedy pairwise `CORR`.
- [x] `OLD:T/selection/drop_low_variance.md`: `VAR_POP`; all-NULL claim wrong.
- [x] `OLD:T/selection/select_k_best.md`: `|CORR|` only; target required.
- [x] `OLD:T/selection/select_percentile.md`: same scoring, percent kept.
- [x] `OLD:T/string/INDEX.md`: list of 8.
- [x] `OLD:T/string/lower.md`: `LOWER`.
- [x] `OLD:T/string/regex.md`: `REGEXP_EXTRACT` groups to new columns.
- [x] `OLD:T/string/replace.md`: literal `REPLACE`.
- [x] `OLD:T/string/stats.md`: seven stats; word count by single space.
- [x] `OLD:T/string/string_length.md`: `LENGTH`, type change.
- [x] `OLD:T/string/substring.md`: 1-based `SUBSTRING`.
- [x] `OLD:T/string/trim.md`: `TRIM`; whitespace claim wrong.
- [x] `OLD:T/string/upper.md`: `UPPER`.
- [x] `OLD:T/window/INDEX.md`: list of 7 files, 10 classes.
- [x] `OLD:T/window/cumulative.md`: four running aggregates.
- [x] `OLD:T/window/lag.md`: `LAG`, NULL at boundary.
- [x] `OLD:T/window/lead.md`: `LEAD`; target-construction use.
- [x] `OLD:T/window/rank.md`: three ranking methods, output `rank`.
- [x] `OLD:T/window/rolling_mean.md`: `AVG` over n-1 preceding.
- [x] `OLD:T/window/rolling_std.md`: `STDDEV_POP` over window.
- [x] `OLD:T/window/row_number.md`: unique number, output `row_number`.

### helpers/ (25 files)

- [x] `OLD:H/INDEX.md`: 21 helpers by version (v0.1 to v1.0 planned).
- [x] `OLD:H/explore.md`: grid, CV, shared prefix promised; v0.4 gap.
- [~] `OLD:H/explore_caching.md`: read L1-135, L455-680, L1285-1300; the rest
  (lifecycle modes, prefix hashing, search levels) skimmed by heading.
- [x] `OLD:H/check.md`: read L1-170 (rules); the data-model and rationale
  sections skimmed.
- [x] `OLD:H/from_sklearn.md`: 16-class mapping; re-learns.
- [x] `OLD:H/quick.md`: baseline auto-pipeline.
- [~] `OLD:H/connection_management.md`: read L20-100 (goals, strategic
  context); the other 1,800 lines skimmed by heading (planned v0.9).
- [~] `OLD:H/connect.md`: basic surface (in-memory, persistent, BYO).
- [~] `OLD:H/attach.md`: wraps `ATTACH`, read-only default.
- [x] `OLD:H/profile.md`: single-query profile.
- [~] `OLD:H/analyze.md`: per-column stats with `level=`.
- [x] `OLD:H/distribution.md`: percentiles, histogram, skew; function unnamed.
- [~] `OLD:H/normality.md`: five tests, SciPy optional.
- [x] `OLD:H/missing.md`: patterns, Jaccard, MAR/MNAR hints.
- [x] `OLD:H/outliers.md`: z-score, IQR, MAD, Mahalanobis; auto by skew.
- [x] `OLD:H/cardinality.md`: eight tiers, ID detection.
- [x] `OLD:H/target.md`: feature-target relations, leakage at 0.95.
- [~] `OLD:H/explain.md`: narrative of an `explore()` result.
- [~] `OLD:H/lineage.md`: column path through a fitted pipeline.
- [x] `OLD:H/peek.md`: `LIMIT n` preview, string output.
- [x] `OLD:H/merge.md`: pre-pipeline join view; default inner.
- [x] `OLD:H/concat.md`: pre-pipeline `UNION ALL` view.
- [~] `OLD:H/correlations.md`: pairwise correlation matrix.
- [~] `OLD:H/model_info.md`: static registry of model needs.
- [~] `OLD:H/help_system.md`: planned `.help()` and bundled offline docs.

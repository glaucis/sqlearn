---
type: note
tags: [sqlearn, transformers, review, duckdb, sklearn-comparison]
summary: "Batch C review of the sqlearn v0.4 transformers, comparing their SQL generation against sklearn and noting departures and bugs."
related: [docs/questions/archived/earlier-attempts/sqlearn-v04/notes/C-transformers.md]
mdindex: [type=edb465, tags=b891d9, summary=d4f4ff]
---
# Batch C: OLD transformers (sqlearn v0.4, `src/sqlearn/transforms/`)

Citation shorthand: `OLD:T/x.py:Ln` = `OLD/src/sqlearn/transforms/x.py` line n.
All lines are from reading only; nothing was run. "sklearn" claims come from
my knowledge and are marked (unsure) where I am not certain. Base class
(`core/transformer.py`) was not in this batch, so hook semantics below are
inferred from the subclasses.

## Summary

- 89 .py files (not ~95), ~9.6k lines, about 60 transformers. Almost all are
  thin: `fit` = a dict of sqlglot aggregate ASTs keyed `"{col}__{stat}"`;
  `transform` = a dict `col -> expression`. Learned scalars are inlined as
  `exp.Literal.number(v)` (the learned state lives in Python, not in the SQL).
- The scaler/imputer family mostly matches sklearn on the happy path
  (`STDDEV_POP`, `AVG`, `MIN/MAX`, `MEDIAN`), but zero-variance handling is
  decided at SQL-generation time in Python (constant column -> literal `0`),
  which matches sklearn (scale_=1 gives 0 after centering) only by accident.
- Probable quantile departure: every quantile uses `QUANTILE(col, p)`
  (RobustScale, QuantileScale, Bin, Winsorize, OutlierHandler). In DuckDB I
  believe `quantile` is an alias of `quantile_disc` (discrete, no
  interpolation), whereas sklearn and numpy use linear interpolation =
  `quantile_cont`. `MEDIAN` is continuous, so RobustScale mixes the two. Verify
  on DuckDB before reuse (unsure).
- `Impute(strategy="mode")` is bare `MODE(col)` with no `ORDER BY col`, so the
  tie-break is not sklearn's smallest-value rule (the review's `MODE(col ORDER
  BY col)` is the fix). Impute also treats only NULL as missing, never NaN.
- `LEAST`/`GREATEST` are used for Clip, Winsorize, OutlierHandler and the max
  norm. DuckDB's variadic `LEAST/GREATEST` ignore NULL arguments (I believe),
  so a NULL input would become the bound instead of staying NULL. Unsure; test.
- No guards on domain errors: `Log` (`LN(x+1)`), `Sqrt`, `Log2/10`, `Power` are
  bare functions; division guard exists only in `Reciprocal`, `MaxAbs`,
  `Robust`, `Normalize`, `Ratio` (via `NULLIF`/`CASE`).
- Transformers that break the aggregate/expression model were handled by a
  second hook `query(input_query) -> Select` that wraps the previous step as a
  subquery (`SELECT ... FROM (<input>) AS alias`): window functions, filter,
  sort, sample, dedupe, join (Lookup), frequency/group aggregates. Composite
  steps (Union, Branch, Nested) forward `discover` and namespace state with a
  `"{name}__"` prefix.
- Evident bugs/smells: FrequencyEncode and GroupAggregate compute stats at
  transform time over the data being transformed (no fit; leaks and differs
  train vs test); TargetEncode runs hand-built SQL from `_learn_source` in
  `expressions()`; PowerScale does not do MLE (skewness heuristic grid, not
  sklearn's Yeo-Johnson/Box-Cox) and mutates `params_` inside `expressions()`;
  Deduplicate looks like it leaks a `__dedup_rn__` column.
- Output naming is ad hoc per transformer (`_pow_2`, `_x_`, `__sin`, `_hash_i`,
  `_bit_i`, `_missing`, `__div__`, `_missing`); schemas are tracked by a
  hand-written `output_schema` in each class (lots of boilerplate).
- Reusable ideas: category set learned via a separate `discover_sets` query;
  `HISTOGRAM(col)` for counts; `CORR` for pairwise correlation; `NULLIF` divide
  guard; `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY rid)` dedupe;
  `IGNORE NULLS` forward/back fill windows;
  `TABLESAMPLE BERNOULLI ... REPEATABLE`.

## Per-transformer table

Column legend: fit = learned in `discover` (SQL aggregate); SQL = transform
expression (col = the incoming column expression). "static" = nothing learned.
Default columns in brackets when not obvious (numeric / categorical /
temporal / all).

### Scalers

| Name | sklearn | fit (aggregate) | transform SQL | NULL / zero / empty | Departures from sklearn | Bugs |
|---|---|---|---|---|---|---|
| Scale (OLD:T/scalers/scale.py:L22) | StandardScaler | `AVG(col)`, `STDDEV_POP(col)` (L48-52) | `(CAST(col AS DOUBLE) - mean) / std` (L75) | NULL propagates. std NULL or 0 -> literal `0` for the whole column (L67-69), so NULL rows also become 0 | ddof=0 correct. No `with_mean/with_std`. sklearn std=0 -> scale_=1 so (x-mean)=0, so 0 also, but NULL inputs would stay NULL in sklearn (NaN); here they become 0. | Literal `0` replaces the expression, hence NULL -> 0 (departure). |
| MinMaxScale (L20 minmax_scale.py) | MinMaxScaler | `MIN`, `MAX` (L40-41) | `(CAST(col AS DOUBLE) - min) / (max - min)` (L65) | span 0 -> literal `0` (L57); `(max or 0)` coerces None to 0 (L54) | No `feature_range`, no `clip`. sklearn range 0 -> scale 1, gives `feature_range[0]` = 0, same. NULL -> 0 on constant column (differs). | `col_min` None (all-NULL column) passes `span==0` check only by accident. |
| MaxAbsScale (maxabs_scale.py:L20) | MaxAbsScaler | `MAX(ABS(col))` (L45-48) | `col / NULLIF(max_abs, 0)` (L66-71) | max_abs None/0 -> literal `0` (L62); NULLIF kept (redundant after the Python guard) | sklearn zero column scale -> 1, output 0; same. NULL -> 0 on all-zero column. | No cast to DOUBLE: integer column / literal might do integer division in other engines; DuckDB `/` is float division so fine. |
| RobustScale (robust_scale.py:L21) | RobustScaler | `MEDIAN(col)`, `QUANTILE(col,q_low/100)`, `QUANTILE(col,q_high/100)` (L65-76) | `(col - median) / NULLIF(q3 - q1, 0)` (L94-118) | iqr==0 -> literal `0` (L106-108) and skips centering result (the `result[col]=0` also discards centering) | `quantile_range`, `with_centering`, `with_scaling` supported. Discrete `QUANTILE` vs sklearn linear interpolation (see Summary; unsure). sklearn IQR 0 -> scale 1 so (x - median), NOT 0. | When iqr==0 and centering is on, output should be `x - median` (sklearn) but is `0`. Also `with_scaling=False` plus `quantile` never learned: fine. Departure and likely bug. |
| Normalize (normalize.py:L21) | Normalizer | static | `col / NULLIF(norm, 0)`; l2 `SQRT(c1*c1+c2*c2+...)`, l1 `ABS(c1)+ABS(c2)+...`, max `GREATEST(ABS(c1),...)` (L105-168) | Any NULL in a row makes l1/l2 norm NULL, so whole row NULL; zero-norm row -> NULL (sklearn leaves zeros: norm 1) | Zero row -> NULL vs sklearn 0. Row with NULL -> NULL (sklearn errors on NaN). GREATEST ignores NULL (unsure). | None clear. Norm expr duplicated per column via `.copy()` (AST bloat O(n^2)). |
| PowerScale (power_scale.py:L21) | PowerTransformer | `AVG, STDDEV_POP, MIN, MAX, SKEWNESS, COUNT` (L67-77), then Python picks lambda | Yeo-Johnson: `CASE WHEN x >= 0 THEN ((x+1)^lam - 1)/lam ELSE -(((-x+1)^(2-lam) - 1)/(2-lam)) END` with `lam≈0 -> LN(x+1)`, `lam≈2 -> -LN(-x+1)`; Box-Cox `(POW(x,lam)-1)/lam` or `LN(x)` (L238-320) | NULL propagates. Box-Cox on <=0 -> lambda forced 1.0 (L130) but expr still fails for x<=0 | NOT sklearn: lambda is chosen by a grid -2.0..3.0 step 0.1 scoring skewness of 7 representative points built from mean/std/min/max (L117-199), not MLE on the data. No `standardize`. | `expressions()` mutates `params_` (L100) and computes lambda there (fit logic in the transform hook). `POW(negative, fractional)` in Box-Cox would be NaN/error. Fixed 1e-10 lambda tolerance. Unsure whether `exp.Neg(Div(...))` precedence prints correctly. |
| QuantileScale (quantile_scale.py:L24) | QuantileTransformer | `QUANTILE(col, i/n)` for i in 0..n (n+1 aggregates per column) (L68-75) | `CASE WHEN col < q1 THEN 0/n WHEN col < q2 THEN 1/n ... ELSE 1.0 END` (step function) (L121-140); normal: A&S 26.2.23 `_ppf` constants in Python (L143-163), clamp 0.001..0.999 | NULL falls through to `ELSE 1.0` (bug: `col < x` is NULL, so ELSE branch is taken) ; missing boundary -> 0.0 (L89) | Step function of n_quantiles buckets, not sklearn's linear interpolation between quantile references; no `subsample`; normal clamp 0.001 vs sklearn 1e-7; ppf accurate only ~4.5e-4. Discrete QUANTILE (unsure). | NULL -> 1.0 (CASE falls to ELSE). Repeated identical boundaries. 101 aggregates per column. |
| (helpers) scale `__init__` etc. | | | | | | |

### Imputation, indicators

| Name | sklearn | fit | SQL | NULL handling | Departures | Bugs |
|---|---|---|---|---|---|---|
| Impute (impute.py:L20) | SimpleImputer | strategy -> `AVG` / `MEDIAN` / `MODE` over col (L49-64, L91-97); constant: nothing | `COALESCE(col, <literal>)` (L79) | Only NULL treated as missing; learned value NULL (all-NULL column) -> `COALESCE(col, NULL)` (keeps NULL; sklearn drops the column unless `keep_empty_features`) | `MODE(col)` has no `ORDER BY col` so ties are not "smallest" (sklearn). No `missing_values=NaN` option, no `add_indicator`, no `strategy="most_frequent"` name (called `mode`; `constant` default 0 in sklearn, here required). Mean on integer column gives DOUBLE literal. `_to_literal` of `bool`/`Decimal` untested. | `_to_literal` for numpy/Decimal/date results may produce bad literal (`Literal.number(date)`); string mode OK. |
| Fill / FillForward / FillBackward (fill.py:L38, L173, L189) | none (pandas ffill/bfill) | static | `COALESCE(col, LAST_VALUE(col IGNORE NULLS) OVER (PARTITION BY p ORDER BY o ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))`; back: `FIRST_VALUE(col IGNORE NULLS) OVER (... ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)` (L100-127) | Leading NULLs stay NULL (forward) | Stateless: applied at transform time on whatever table is passed (the first rows of a test set have no history; no carried state). | ORDER BY ties non-deterministic; relies on ordering columns. |
| MissingIndicator (missing_indicator.py:L35) | MissingIndicator | static | `CASE WHEN col IS NULL THEN 1 ELSE 0 END` named `{col}_missing`, keeps the original col too (L45-58) | NULL only, not NaN | sklearn default `features="missing-only"` (learns which cols had missing in fit); this emits an indicator for every column. Output int vs bool. | None. |

### Encoders

| Name | sklearn | fit | SQL | NULL / unseen | Departures | Bugs |
|---|---|---|---|---|---|---|
| OneHot (encoders/onehot.py:L32) | OneHotEncoder | `discover_sets`: set query of distinct `col` values (L47-50), categories sorted in Python | per category `CASE WHEN col = 'cat' THEN 1 ELSE 0 END`, name `{col}_{cat}` (L68-75); original col removed | Unseen -> all zeros (=handle_unknown="ignore" always); NULL category is filtered (L65) so NULL row -> all zeros | No `drop`, `min_frequency`, `max_categories`, `handle_unknown="error"`; sklearn treats NaN as its own category. Column name `col_cat` vs sklearn `col_cat`. | `sorted()` over mixed types raises; cat compared as string literal `str(cat)` (numeric categories rely on implicit cast); category names with odd characters not quoted. |
| Ordinal (ordinal.py:L31) | OrdinalEncoder | `discover_sets` distinct values (L41-44) | `CASE WHEN col='A' THEN 0 WHEN col='B' THEN 1 ... ELSE NULL END` (L63-71) | unseen/NULL -> NULL | No `categories` order param (always sorted); no `handle_unknown="use_encoded_value"`; empty categories -> literal NULL (L60). | none. |
| BinaryEncode (binary_encode.py) | category_encoders BinaryEncoder (not sklearn) | distinct values | ordinal CASE then `MOD(DIV(ordinal, 2^k), 2)` for k < ceil(log2(max(n,2))) (L70-91), cols `{col}_bit_{k}` | unseen/NULL -> NULL bits | no sklearn equivalent. | uses `IntDiv` on a possibly DOUBLE/INT CASE expr: fine. Whole CASE duplicated per bit. |
| CountEncode (count_encode.py:L51) | none (category_encoders CountEncoder) | `HISTOGRAM(col)` (map value->count) and `COUNT(col)` total (L99-106) | `CASE WHEN col = 'cat' THEN n [/ total if normalize] ... ELSE unseen_value END` (L167-204) | NULL and unseen -> `unseen_value` (default 0); empty histogram -> NULL | not sklearn. | normalize uses non-NULL count as total. Large CASE for high-cardinality columns. |
| FrequencyEncode (frequency_encode.py:L52) | none | static (!) | `query()` hook: `CAST(COUNT(*) OVER (PARTITION BY col) AS DOUBLE) / CAST(COUNT(*) OVER () AS DOUBLE)` over the current data (L89-111) | NULL is its own partition | Not fit/transform: frequency computed from the data being transformed, so a one-row table gives 1.0 and test != train. | Design bug (classification "static" but statistical). Also enumerates the input SELECT's expressions to pass through other columns (L80-114): fragile. |
| HashEncode (hash_encode.py:L56) | FeatureHasher/HashingVectorizer (loosely) | static | `CASE WHEN ABS(HASH(col)) % n = i THEN 1 ELSE 0 END`, cols `{col}_hash_{i}` (L96-116) | NULL -> HASH(NULL)=NULL -> `CASE` -> 0 in all buckets | Different hash than sklearn; no signed hashing. `ABS(HASH())` on UBIGINT is fine; on a signed type ABS(min) overflow not an issue as HASH is UBIGINT (unsure). | DuckDB `HASH` values are not stable across versions (unsure). |
| TargetEncode (target_encode.py:L40) | TargetEncoder | `AVG(y)`, `COUNT(y)` global; `COUNT(DISTINCT col)` (unused); `discover_sets` categories (L66-98); per-category stats via raw SQL `SELECT col, AVG(y), COUNT(*) FROM <source> WHERE col IS NOT NULL GROUP BY col` run in `expressions()` (L126-133) | `CASE WHEN col='c' THEN (n*mean_c + smooth*global)/(n+smooth) ... ELSE global END` (L172-181) | NULL / unseen -> global mean | sklearn: `smooth="auto"` (empirical Bayes using variances), 5-fold cross-fitting in `fit_transform`, handles multiclass. Here fixed `smooth=1.0`, no cross-fitting (leak in train set). | Raw SQL via f-string with `_learn_source` (injection, no quoting of source); `except Exception` swallows errors; fit work done lazily during transform (L155); `__count_distinct` param unused; fallback count=1 (L116). |

### Arithmetic / elementwise

| Name | sklearn | SQL | Notes |
|---|---|---|---|
| Abs, Ceil, Floor, Sqrt, Exp, Sign (arithmetic/*.py) | FunctionTransformer(np.fn) | `ABS(col)`, `CEIL(col)`, `FLOOR(col)`, `SQRT(col)` (bare `exp.Sqrt`), `EXP(col)`, `SIGN(col)` | static, NULL in -> NULL. Sqrt of negative: no guard (the review's CASE guard is not here). `Exp` overflow gives inf or error (unsure). |
| Log (log.py:L20) | FunctionTransformer(np.log1p) | `LN(col + offset)` (offset default 1, L73-78); with `base`: `/ LN(base)` (L81-83) | No guard for `col+offset <= 0`: DuckDB may raise. base==1 rejected. offset>=0 enforced. |
| Log2, Log10 | FunctionTransformer | `LOG2(col)`, `LOG10(col)` | no offset, no guard; inconsistent with Log's offset default. |
| Power (power.py:L18) | PolynomialFeatures-ish / `power` | `POW(col, exponent)` | negative base with fractional exponent: NaN/error. |
| Reciprocal (reciprocal.py) | FunctionTransformer(np.reciprocal) | `1.0 / NULLIF(col, 0)` | zero -> NULL (numpy gives inf). |
| Round (round.py) | FunctionTransformer(np.round) | `ROUND(col, decimals)` | DuckDB rounds half away from zero; numpy rounds half to even. Departure. |
| Binarize (binarize.py:L18) | Binarizer | `CASE WHEN col > threshold THEN 1 ELSE 0 END` | NULL -> 0 (CASE falls to ELSE). sklearn is `> threshold` too. |
| Clip (clip.py:L20) | none (np.clip) | `GREATEST(LEAST(col, upper), lower)` (L71-80) | NULL -> bound (LEAST/GREATEST skip NULLs, unsure). Validates lower<=upper. |

### Binning, outliers

| Name | sklearn | fit | SQL | Notes |
|---|---|---|---|---|
| Bin (binning/bin.py:L39) | KBinsDiscretizer(encode="ordinal") | uniform: `MIN`, `MAX`; quantile: `QUANTILE(col, i/n)` i=0..n; custom: static edges (L70-79) | `CASE WHEN col < e1 THEN 0 WHEN col < e2 THEN 1 ... ELSE n-1 END` (L129-136) | Bin i = [e_i, e_{i+1}); under-range goes to bin 0, over-range to n-1 (matches sklearn clipping). `strategy="kmeans"` missing. NULL -> n-1 (falls to ELSE; bug). `max or 1` bug if max=0 (L101). Discrete QUANTILE (unsure). sklearn quantile bins deduplicate equal edges; here not. |
| Winsorize (outlier/winsorize.py:L38) | none (scipy winsorize) | `QUANTILE(col, lower)`, `QUANTILE(col, upper)` (L66-73) | `GREATEST(LEAST(col, upper_v), lower_v)` (L91-97) | None quantile -> passthrough. NULL -> lower bound (unsure). |
| OutlierHandler (outlier/outlier_handler.py:L63) | none (IQR/zscore rule) | iqr: `QUANTILE(.25)`, `QUANTILE(.75)`; zscore: `AVG`, `STDDEV_POP` (L107-127) | clip: `GREATEST(LEAST(col, upper), lower)` with fences `q1 - f*iqr`, `q3 + f*iqr` or `mean ± k*std`; remove: row filter `col BETWEEN lo AND hi` or `ABS((col - mean)/NULLIF(std,0)) <= threshold` via `query()` (L186-254) | remove drops NULL rows (BETWEEN with NULL is NULL, removed) – surprising. None param -> 0.0. Rows removed also when applying on new data (changes row count at inference). |

### Datetime

| Name | SQL | Notes |
|---|---|---|
| Cyclical (datetime/cyclical.py) | `SIN(2*pi*CAST(col AS DOUBLE)/period)`, `COS(...)` -> `{col}__sin`, `{col}__cos`, replacing col (L113-129); `unit` shortcuts hour/day=24, week/weekday=7, month=12, quarter=4, year=365.25 | static; operates on numeric inputs (period from user), not on timestamps. "day": 24 looks wrong or ambiguous. sklearn's SplineTransformer(periodic) / docs example only. NULL -> NULL. |
| DateParts (date_parts.py) | `EXTRACT(PART FROM col)`, parts year, month, day, dayofweek(DOW), hour, minute, second, quarter, week, dayofyear(DOY); default 5 parts; keeps original (L141-148) | DuckDB DOW: Sunday=0. second extract includes fraction? (unsure). New names `{col}_{part}`. |
| DateDiff (date_diff.py) | `DATE_DIFF(unit, col, ref)` via sqlglot `exp.DateDiff`; ref is another column or an ISO date literal detected by shape (L87-101) | DuckDB `date_diff` counts unit boundaries crossed, not elapsed whole units. Sign direction relies on sqlglot's DuckDB generation (unsure). Column-vs-literal detection by string shape is fragile. |
| IsWeekend | `CASE WHEN EXTRACT(DOW FROM col) IN (0, 6) THEN 1 ELSE 0 END` | NULL -> 0 (CASE ELSE), not NULL. |
| Quarter | `EXTRACT(QUARTER FROM col)` | NULL -> NULL. |

### Strings

| Name | SQL |
|---|---|
| Lower, Upper, Trim | `LOWER(col)`, `UPPER(col)`, `TRIM(col)` (DuckDB trims spaces only) |
| Replace | `REPLACE(col, old, new)` (old non-empty) |
| StringLength | `LENGTH(col)` (characters; type becomes INTEGER) |
| Substring | `SUBSTRING(col, start[, length])`, start >= 1 |
| RegexExtract (string/regex.py) | `REGEXP_EXTRACT(col, pattern, g)` per group -> `{col}__{g}`, keeps col |
| StringStats (string/stats.py:L97) | length `LENGTH(col)`; word_count `CASE WHEN LENGTH(c)=0 THEN 0 ELSE LENGTH(c)-LENGTH(REPLACE(c,' ',''))+1 END` where `c = REGEXP_REPLACE(TRIM(col), '\s+', ' ', 'g')`; upper/lower/digit/space counts `LENGTH(REGEXP_REPLACE(col, '[^A-Z]', '', 'g'))` etc.; special `LENGTH(REGEXP_REPLACE(col,'[A-Za-z0-9\s]','','g'))` (L147-218) |

All static; NULL in -> NULL. Upper/lower counts ASCII-only. `TRIM` leaves
tabs/newlines so the word-count can be off by one for leading tabs.

### Composition / feature-generation / selection

| Name | sklearn | fit | SQL / behaviour | Notes |
|---|---|---|---|---|
| Interaction (interaction.py) | PolynomialFeatures(interaction_only=True) | static | passthrough + `a * b` for all `combinations(columns, 2)` or given pairs, name `{a}_x_{b}` | no bias column, degree fixed 2 |
| Polynomial (polynomial.py:L40) | PolynomialFeatures | static | passthrough, `POW(col, d)` d=2..degree named `{col}_pow_{d}`, pairwise `a*b` (degree >= 2 only) | NOT sklearn: no higher cross-terms (a^2*b), no bias, `x_pow_2` vs `x^2`, ordering differs |
| Ratio (ratio.py:L52) | none | static | `CASE WHEN CAST(den AS DOUBLE) = 0 THEN NULL ELSE CAST(num AS DOUBLE) / CAST(den AS DOUBLE) END` (L148-168), named `{a}__div__{b}`; own `_resolve_columns` | `null_on_zero=False` -> division by zero error in DuckDB or inf (unsure) |
| GroupAggregate (group_aggregate.py:L73) | none | classified static but uses `query()`: `SELECT *, AGG(col) OVER (PARTITION BY g) AS {col}_{agg}_by_{g} FROM (<input>)` (L98-127) | computed over transformed data (same train/test mismatch as FrequencyEncode). aggs avg,sum,min,max,count,stddev,stddev_pop,variance,var_pop,median,mode |
| DropLowVariance (selection/drop_low_variance.py:L37) | VarianceThreshold | `VAR_POP(col)` | keeps `var > threshold` (L71); passthrough for kept columns (dropped column simply absent from the expression dict) | matches sklearn (`variances_ > threshold`, ddof=0); NULL var -> dropped. Selection decided lazily and cached in `_kept_columns` (L66) |
| DropCorrelated (drop_correlated.py:L35) | none (feature-engine) | `CORR(a,b)` for every column pair, O(p^2) aggregates (L56-66) | greedy drop by "involvement" count in Python (L68-101) | `abs(corr) > threshold`; NULL corr treated as not correlated; non-deterministic-ish ordering only by sort key |
| SelectKBest (select_k_best.py:L37) | SelectKBest(f_regression) | `CORR(col, y)` (L67-69) | keep top-k by `abs(corr)` (L83-84) | for regression F is monotone in r^2 so ranking agrees; classification (f_classif) not matched; NULL score -> 0; ties by Python stable sort (column order) vs sklearn's by score then index |
| SelectPercentile (select_percentile.py:L38) | SelectPercentile | `CORR(col, y)` | `k = max(1, ceil(n * pct / 100))` (L85) | sklearn: keeps scores > percentile cutoff (ties differ) (unsure) |
| Expression (expression.py:L35) | FunctionTransformer | static | user template with `{col}` replaced, parsed by `sqlglot.parse_one` (L55-56) | f-string style substitution; column names are not quoted/escaped |
| custom() (custom.py:L21) | FunctionTransformer | `learn={"name": "AGG({col})"}` -> aggregates parsed from templates | transform template with `{col}` and `{name}` replaced by `str(value)` ("NULL" if None) (L108-117) | string substitution of learned values (floats via `str()`, strings unquoted! L114) |
| Sql (sql.py:L64) | none | same `learn` mechanism | if template looks like full query (`_is_full_query`: contains "SELECT ", "FROM ", " JOIN ", " WHERE ") then `{input}` is replaced with the previous step's SQL and `query()` is used, else per-column expression with optional `AS alias` creating a new column (L121-151) | heuristics for classification; output schema for queries unknown; learned param substitution `{param}` loop over cols replaces with last col's value (L112-117: the same `{param}` is replaced for the first col then no placeholder remains) |
| TargetTransform (target_transform.py:L45) | TransformedTargetRegressor | delegates `discover((target,), schema, target)` (L71-75) | applies wrapped transformer's `expressions` to the target column, copying params onto the wrapped instance (L106-111); `inverse_target` is hard-coded per class name (Log, Scale, MinMaxScale, Sqrt, Exp) (L131-161) | inverse by `type(...).__name__` string compare; Exp -> `np.log(predictions)`; Log without offset case ok |

### Row/table operations (outside the expression model, see below)

| Name | SQL |
|---|---|
| Cast (ops/cast.py) | `CAST(col AS type)` from `mapping`; type via `exp.DataType.build` (expression-based, fits the model) |
| Drop (ops/drop.py) | `expressions()` returns `{}`; schema.remove only (column removal handled by the framework) |
| Rename (ops/rename.py) | `query()`: explicit `SELECT col AS new, ... FROM (<input>) AS __renamed` |
| Filter (ops/filter.py) | `query()`: `SELECT * FROM (<input>) AS __filtered WHERE <parsed condition>` |
| Sort (ops/sort.py) | `query()`: `SELECT * FROM (<input>) AS __sort_input ORDER BY ...` |
| Sample (ops/sample.py) | n: `ORDER BY RANDOM() LIMIT n`; fraction: string-built `SELECT * FROM (<input sql>) TABLESAMPLE BERNOULLI(pct PERCENT) REPEATABLE (seed)` (L75-87) |
| Deduplicate (ops/deduplicate.py:L36) | `SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY cols ORDER BY __sqlearn_rid__) AS __dedup_rn__ FROM (<input>)) AS __dedup WHERE __dedup_rn__ = 1` (L62-93) |
| Lookup (lookup.py:L56) | `query()`: `SELECT __input__.cols..., __lookup__.cols... FROM (<input>) AS __input__ LEFT\|INNER JOIN <source> AS __lookup__ ON __input__.k = __lookup__.k [AND...]`, overlapping columns get `suffix` (L141-234); `discover` introspects the lookup source with `DuckDBBackend().describe` (L119-123) |
| Rank, RowNumber (window/rank.py, row_number.py) | `SELECT *, RANK()\|DENSE_RANK()\|ROW_NUMBER() OVER (PARTITION BY p ORDER BY o) AS rank\|row_number FROM (<input>) AS __w` |
| Lag, Lead | `LAG(col, n) OVER (PARTITION BY p ORDER BY o) AS {col}_lag_{n}` (same for LEAD) |
| RollingMean, RollingStd | `AVG(col)` / `STDDEV_POP(col)` `OVER (... ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW)` -> `{col}_rmean_{n}`, `{col}_rstd_{n}`; n >= 2; first rows use partial windows (no min_periods); RollingStd uses population std (pandas rolling().std default is sample, ddof=1) |
| CumulativeSum/Min/Max/Count (window/cumulative.py:L24) | `SUM/MIN/MAX/COUNT(col) OVER (... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`; `{col}_cumsum`, `_cummin`, `_cummax`, `_cumcount`; one base class with `_agg_name`, `_suffix`, `_build_agg` |
| Union (union.py), Branch (branch.py), Nested (nested.py) | composites, see below |

## SQL worth keeping

Exact SQL (rendered from the AST; verified by reading only). Compare with the
review's list (`Std = STDDEV_POP`, `MODE(col ORDER BY col)`, `Distinct` guard,
`Sqrt` guard): the old transformers agree on `STDDEV_POP`
(OLD:T/scalers/scale.py:L49-52) and `VAR_POP`
(OLD:T/selection/drop_low_variance.py:L61), but not the others.

```sql
-- StandardScaler
(CAST(x AS DOUBLE) - :mean) / :std            -- mean = AVG(x), std = STDDEV_POP(x); guard std = 0 in fit
-- MaxAbsScaler
SELECT MAX(ABS(x)) FROM t;  x / NULLIF(:max_abs, 0)
-- RobustScaler (with exact quantile_cont to match numpy)
SELECT MEDIAN(x), QUANTILE_CONT(x, 0.25), QUANTILE_CONT(x, 0.75) FROM t;
(x - :median) / NULLIF(:q3 - :q1, 0)          -- see bugs: sklearn uses scale 1 when IQR = 0
-- Yeo-Johnson (given lambda)
CASE WHEN x >= 0 THEN (POW(x + 1, :lam) - 1) / :lam ELSE -((POW(-x + 1, 2 - :lam) - 1) / (2 - :lam)) END
-- special cases lam ~ 0: LN(x + 1); lam ~ 2: -LN(-x + 1)       (OLD:T/scalers/power_scale.py:L238-296)
-- Box-Cox: (POW(x, :lam) - 1) / :lam ; lam ~ 0: LN(x)
-- Row L2 norm across columns
x / NULLIF(SQRT(a*a + b*b + c*c), 0)
-- Category counts in one aggregate (map value -> count)
SELECT HISTOGRAM(col), COUNT(col) FROM t
-- Category set (OneHot/Ordinal) learned by a separate distinct query
SELECT DISTINCT col FROM t
-- Constant-time safe division / ratio
CASE WHEN CAST(d AS DOUBLE) = 0 THEN NULL ELSE CAST(n AS DOUBLE) / CAST(d AS DOUBLE) END
-- Forward / backward fill
COALESCE(x, LAST_VALUE(x IGNORE NULLS) OVER (PARTITION BY p ORDER BY o ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
COALESCE(x, FIRST_VALUE(x IGNORE NULLS) OVER (PARTITION BY p ORDER BY o ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING))
-- Dedupe keep-first
SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY k ORDER BY rid) rn FROM t) WHERE rn = 1  -- project away rn
-- Row sampling with seed
SELECT * FROM (...) TABLESAMPLE BERNOULLI(10 PERCENT) REPEATABLE (42)
-- Feature scores / selection
CORR(x, y)         -- selection by |r|; VAR_POP(x) for VarianceThreshold (> threshold)
-- Cyclical
SIN(2 * pi() * x / :period), COS(2 * pi() * x / :period)
-- Hash buckets
CASE WHEN ABS(HASH(x)) % :n = :i THEN 1 ELSE 0 END
```

Do not copy as-is: any `QUANTILE(x, p)` (use `QUANTILE_CONT` after checking
DuckDB's documented alias), bare `MODE(x)`, bare `SQRT/LN`, `Clip` via
`LEAST/GREATEST` without a NULL guard, and `CASE ... ELSE` forms that map
NULL to a bucket.

## Authoring pattern

Hooks seen on `Transformer` (all in `core/transformer.py`, not read here):

- Class attributes: `_default_columns` ("numeric" / "categorical" / "temporal" /
  "all" / None) and `_classification` ("static" / "dynamic"; composites leave
  it `None` and implement `_classify()` by scanning children).
- `discover(columns, schema, y_column) -> dict[str, AggregateExpr]`: the fit
  hook; keys `"{col}__{stat}"`; values are sqlglot ASTs built as
  `exp.Anonymous(this="STDDEV_POP", expressions=[col_ref])`. Results land in
  `params_` (dict of scalars, `self.params_[f"{col}__mean"]`).
- `discover_sets(columns, schema, y_column) -> dict[str, Expression]`: the
  second fit hook for learned *sets* (categories); results in `sets_`.
- `expressions(columns, exprs) -> dict[str, Expression]`: the transform hook;
  `exprs` is the current column->expression map so steps compose without
  subqueries; return keys may add columns (`{col}_pow_2`) or omit them (drops);
  several transformers must "re-emit original column to prevent passthrough
  dropping it" (e.g. DateParts L140, RegexExtract L112, MissingIndicator L47),
  which shows that dropped-vs-kept is implicit.
- `query(input_query) -> Select | None`: escape hatch that replaces the
  expression path for steps that need a new FROM, window, filter or join; it
  wraps the previous `Select` as an aliased subquery.
- `output_schema(schema)`: hand-written per class (add/remove/retype); used
  for planning. Pure boilerplate in ~35 classes (types are string literals like
  `"INTEGER"`, `"DOUBLE"`).
- `_resolve_columns(schema)` override for transformers not keyed on one column
  list (Ratio, Rank, RowNumber).
- `__init__(*, columns=None, **kwargs)` ->
  `super().__init__(columns=columns, **kwargs)`, then validation raising
  `ValueError` with `msg = ...; raise ValueError(msg)`; `__repr__`
  re-implemented by hand listing only non-default params in several classes.

Boilerplate/pitfalls:
- Per-column loops with `f"{col}__{stat}"` keys and flat dict state (not a typed
  fitted-state object).
- `exp.Anonymous(this="NAME", expressions=[...])` everywhere instead of typed
  nodes; the same node reused across columns needs `.copy()` (comments at
  hash_encode.py:L94, normalize `norm_expr.copy()`).
- Fit-time statistics read back inside `expressions()`, with Python guard
  branches (`if std is None or std == 0`) that replace the SQL with a literal;
  this pushes decisions out of SQL and loses NULL semantics.
- Several fit-like computations hidden in `expressions()` (PowerScale lambda
  L88-100, TargetEncode category stats, Drop* selection `_compute_*` caches).
- Template-string transformers (`Expression`, `custom`, `Sql`) with `{col}`
  string replacement.

## Transformers outside the row-expression model

| Kind | Transformers | How handled |
|---|---|---|
| Window functions (sequence-dependent, needs ORDER BY) | Lag, Lead, RollingMean, RollingStd, Cumulative*, Rank, RowNumber, FillForward/Backward | `query()` wraps previous select: `SELECT *, <window> AS new FROM (<input>) AS __w` (shared helper `window/_helpers.py:L13-59` builds `Order`, partition, subquery). Fill uses the expression hook since the window yields one value per column. All marked "static"; output depends on row order of the data supplied, nothing learned. Ties in `ORDER BY` are non-deterministic (no row-id tiebreak, unlike Deduplicate). |
| Dataset-level stat applied at transform time | FrequencyEncode, GroupAggregate | `query()` with `COUNT(*) OVER (PARTITION BY ...)`; "static" but really transductive; breaks fit/transform separation (design problem to avoid). |
| Row filtering | Filter, OutlierHandler(action="remove"), Deduplicate, Sample | `query()` with WHERE / ROW_NUMBER filter / TABLESAMPLE or RANDOM LIMIT; changes row count at inference, interacts badly with target `y` alignment. |
| Ordering | Sort | `ORDER BY` in a subquery (order not guaranteed by SQL semantics). |
| Join | Lookup | `query()` LEFT/INNER JOIN to another table/file; `discover` talks to a backend instance (`describe`), so fit needs a live connection; duplicate keys in the lookup multiply rows. |
| Schema rewrite | Rename, Drop, Cast | Rename uses `query()` with explicit select list (needs `_default_columns="all"` to know every column); Drop returns `{}` and relies on `output_schema.remove`. |
| Branch (conditional) | Branch | per-column `CASE WHEN <sql condition string> THEN <child step expr> ... ELSE col END`; children's `discover`/`discover_sets` prefixed `b{i}__`, state redistributed by prefix to the child before `expressions` (branch.py:L80-162). Conditions are SQL strings parsed with sqlglot. |
| Union (parallel feature union) | Union | each named child produces columns prefixed `{name}_`; all input columns replaced; `discover` prefixed `{name}__`; a cached `_output_columns` idempotency guard hack in `output_schema` (L125-128) and `get_params(deep)` mimicking sklearn. Equivalent of ColumnTransformer/FeatureUnion without a SQL UNION. |
| Nested pipeline | Nested | holds a `Pipeline`; discover loops over inner steps threading the schema through `output_schema`; `expressions` runs inner steps' `_apply_expressions` sequentially on the same expr dict; CTE name from a global thread-locked counter (nested.py:L31-41, name unused in the shown code). Does not support inner `query()` steps (only expression steps; unsure). |
| Target transform | TargetTransform | acts on `y_column`; inverse in Python via class-name dispatch. |
| Free-form SQL | Sql, custom, Expression | string templates; `Sql` can be a full query. |

Implication for the new core (design hints): row-expression vs whole-query
steps need two distinct step kinds; window/ordering steps need a deterministic
ordering contract; "fit" must stay data-independent of the data being
transformed; composites need namespaced fitted state (the `"{name}__"` prefix
trick works but is stringly typed).

## Semantics departures and bugs

Ordered by importance.

1. Quantile type (probable): `QUANTILE` (discrete, I believe) vs sklearn/numpy
   linear interpolation; affects RobustScale, QuantileScale, Bin(quantile),
   Winsorize, OutlierHandler(iqr). Also `MEDIAN` continuous in RobustScale,
   inconsistent. Verify against DuckDB docs/behaviour (unsure).
2. RobustScale IQR==0: emits literal `0` instead of `x - median`
   (OLD:T/scalers/robust_scale.py:L106-108); sklearn uses scale 1.
3. Constant-column scalers (Scale, MinMax, MaxAbs) return literal `0`, turning
   NULL into 0; sklearn keeps NaN.
4. NULL falls through `CASE WHEN ... ELSE` into the last bucket in Bin
   (bin.py:L136), QuantileScale (quantile_scale.py:L140), Binarize (-> 0),
   IsWeekend (-> 0), Ordinal ok (-> NULL), OneHot (all zeros).
5. Impute `MODE(col)` tie-break; no NaN as missing; all-NULL column keeps NULL.
6. MissingIndicator always indicates all columns (sklearn default
   "missing-only"); NaN not considered.
7. PowerScale is not Yeo-Johnson/Box-Cox MLE and sets lambda inside
   `expressions()`.
8. TargetEncode: no cross-fitting, fixed smooth; raw f-string SQL in transform
   path (injection, swallowed exceptions).
9. FrequencyEncode, GroupAggregate: statistics computed over the transform
   input, not learned in fit.
10. Polynomial: only degree-2 interactions regardless of degree, no bias;
    Interaction duplicates.
11. Normalize: zero-norm rows -> NULL (sklearn 0); NULL in any column nulls the
    row.
12. Round: DuckDB half-away-from-zero vs numpy half-even.
13. RollingStd: `STDDEV_POP` (pandas default ddof=1); rolling windows without
    min_periods.
14. Log/Sqrt/Log2/Log10 lack domain guards; Reciprocal returns NULL at 0 (numpy
    inf).
15. Deduplicate: `SELECT *` after adding `__dedup_rn__` appears to leave the
    helper column (no EXCEPT/EXCLUDE seen in L62-93, and no `output_schema`);
    also relies on `__sqlearn_rid__` existing. Likely bug (unsure).
16. Sql/custom template: learned values interpolated with `str(value)` (strings
    unquoted, floats lose nothing but repr risk); the `{param}` substitution in
    `Sql.query` loops over columns (L112-117) and replaces on the first column
    only.
17. Sample/Filter/Sort/Deduplicate/Outlier-remove in a pipeline apply at predict
    time too.
18. Cyclical `unit="day"` -> 24 (unclear), `year` 365.25 on day-of-year
    numerics.
19. DateDiff counts boundaries, reference-kind detected by string shape.
20. SelectKBest/Percentile use |CORR| rather than F-score (regression OK;
    classification not); ties by column order.
21. Unused/dead learned values: TargetEncode `__count_distinct`.

## Files covered

- [x] __init__.py
- [x] arithmetic/__init__.py
- [x] arithmetic/abs.py
- [x] arithmetic/binarize.py
- [x] arithmetic/ceil.py
- [x] arithmetic/clip.py
- [x] arithmetic/exp_transform.py
- [x] arithmetic/floor.py
- [x] arithmetic/log.py
- [x] arithmetic/log10.py
- [x] arithmetic/log2.py
- [x] arithmetic/power.py
- [x] arithmetic/reciprocal.py
- [x] arithmetic/round.py
- [x] arithmetic/sign.py
- [x] arithmetic/sqrt.py
- [x] binning/__init__.py
- [x] binning/bin.py
- [x] branch.py
- [x] custom.py
- [x] datetime/__init__.py
- [x] datetime/cyclical.py
- [x] datetime/date_diff.py
- [x] datetime/date_parts.py
- [x] datetime/is_weekend.py
- [x] datetime/quarter.py
- [x] encoders/__init__.py
- [x] encoders/binary_encode.py
- [x] encoders/count_encode.py
- [x] encoders/frequency_encode.py
- [x] encoders/hash_encode.py
- [x] encoders/onehot.py
- [x] encoders/ordinal.py
- [x] encoders/target_encode.py
- [x] expression.py
- [x] fill.py
- [x] group_aggregate.py
- [x] impute.py
- [x] interaction.py
- [x] lookup.py
- [x] missing_indicator.py
- [x] nested.py
- [x] ops/__init__.py
- [x] ops/cast.py
- [x] ops/deduplicate.py
- [x] ops/drop.py
- [x] ops/filter.py
- [x] ops/rename.py
- [x] ops/sample.py
- [x] ops/sort.py
- [x] outlier/__init__.py
- [x] outlier/outlier_handler.py
- [x] outlier/winsorize.py
- [x] polynomial.py
- [x] ratio.py
- [x] scalers/__init__.py
- [x] scalers/maxabs_scale.py
- [x] scalers/minmax_scale.py
- [x] scalers/normalize.py
- [x] scalers/power_scale.py
- [x] scalers/quantile_scale.py
- [x] scalers/robust_scale.py
- [x] scalers/scale.py
- [x] selection/__init__.py
- [x] selection/drop_correlated.py
- [x] selection/drop_low_variance.py
- [x] selection/select_k_best.py
- [x] selection/select_percentile.py
- [x] sql.py
- [x] string/__init__.py
- [x] string/lower.py
- [x] string/regex.py
- [x] string/replace.py
- [x] string/stats.py
- [x] string/string_length.py
- [x] string/substring.py
- [x] string/trim.py
- [x] string/upper.py
- [x] target_transform.py
- [x] union.py
- [x] window/__init__.py
- [x] window/_helpers.py
- [x] window/cumulative.py
- [x] window/lag.py
- [x] window/lead.py
- [x] window/rank.py
- [x] window/rolling_mean.py
- [x] window/rolling_std.py
- [x] window/row_number.py

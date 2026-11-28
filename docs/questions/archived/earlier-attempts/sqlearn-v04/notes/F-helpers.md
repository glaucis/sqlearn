---
type: note
tags: [sqlearn, helpers, review, statistics, duckdb, legacy]
summary: "Review of old sqlearn v0.4 helper functions: what each computes, where (SQL vs Python), statistical correctness, and dependencies, to inform the new app."
related: [docs/questions/archived/earlier-attempts/sqlearn-v04/notes/F-helpers.md]
mdindex: [type=edb465, tags=bb2b25, summary=2daa73]
---
# Batch F: helpers, user guide, notebooks, api/quickstart (old sqlearn v0.4)

OLD = "/Users/tomas/Desktop/Desktop - Tomas’s MacBook
Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn" Citations are
`OLD:path:Lnn` relative to OLD. "(inf)" marks inference, not read directly. Read
only; nothing in OLD was run or modified.

## Summary

- The old "analysis primitive family" (profile, analyze, distribution,
  normality_tests, missing_patterns, outliers, cardinality, target_analysis,
  correlations) is a ready-made spec for the data-exploration app's per-column
  and per-pair statistics. Most numeric work really is DuckDB aggregates (AVG,
  STDDEV_POP, SKEWNESS, KURTOSIS, QUANTILE_CONT, APPROX_QUANTILE, CORR, COUNT
  FILTER). OLD:src/sqlearn/helpers/distribution.py:L348-L376
- The shared result contract is worth copying: frozen dataclass, `row_count`,
  text / HTML / `to_dict()` renderings, no plotting dependency, `.to_dict()`
  feeds an external UI. OLD:src/sqlearn/helpers/_primitive_base.py:L17-L62;
  OLD:docs/user-guide/analysis.md:L106-L145
- The pattern "one aggregate query for all columns, parse by alias" is sound but
  has bugs: aliases are built from raw column names (`{col}__count`), which
  break on spaces or punctuation (only cardinality/target use `_safe_alias`, and
  that one can collide). OLD:src/sqlearn/helpers/analyze.py:L374-L398;
  OLD:src/sqlearn/helpers/cardinality.py:L443-L451
- Several statistical outputs are wrong or misleading: KS against N(0,1) with
  estimated mean/std (needs Lilliefors), Spearman via `RANK()` (ties get min
  rank, NULLs ranked), Kendall is tau-a and O(n²), outlier `row_ids` from
  `ROW_NUMBER() OVER ()` with no ORDER BY (not stable), missingness
  "MCAR/MAR/MNAR" labels from percentage thresholds, `id_like` fires on any
  continuous column.
- Several helpers pull whole columns into Python: five of six normality tests
  (all non-null values via `fetchall`), Mahalanobis (all rows into numpy),
  Cramér's V (contingency table in Python), Kendall (SQL self-join),
  model-search scoring (target column to Python lists). Dependencies leaked
  beyond duckdb: numpy (core), sqlglot (core, concat/merge/compiler), scipy and
  statsmodels (optional extras, but required for most normality tests).
- `sq.explore()` is not model selection. It "scores" a pipeline by comparing the
  transformed target column with the raw target, with no model. Its fold view
  uses unseeded `RANDOM()` inside a VIEW so train and test folds can overlap,
  and any exception silently sets predictions equal to truth (perfect score). Do
  not port it as designed. OLD:src/sqlearn/helpers/explore.py:L278-L299,
  L432-L456
- sklearn bridge: `as_sklearn()` (SklearnAdapter, duck-typed, numpy out) and
  `from_sklearn()` (class-name lookup table, drops all hyperparameters). Neither
  is needed by an independent project; the adapter is also incorrect under
  `clone` / `GridSearchCV` (inf).
  OLD:src/sqlearn/helpers/sklearn_adapter.py:L19-L106;
  OLD:src/sqlearn/helpers/from_sklearn.py:L11-L82
- The docs repeatedly disagree with the code (cardinality tier thresholds and
  check order, "KS works without SciPy", "no deps beyond DuckDB and numpy",
  Spearman/mutual_info in target_analysis, categorical features with numeric
  targets, "Shapiro always samples", Python 3.10, shared-prefix caching). The
  old docs cannot be trusted as a spec; the code is the better spec, and defects
  are listed below.
- Good small ideas to keep: sampling clause builder with validation, the "sample
  is for exploration only" warnings recorded on the result,
  `PrimitiveResult.row_count` / `sampled` flags, ID / near-constant / encoder
  recommendation tiers, missingness patterns by `GROUP BY` of `IS NULL` bits,
  Jaccard co-missingness via `COUNT(*) FILTER`, target-leakage flag, imbalance
  verdicts, `lineage()` as a pure function of fitted state, `model_info`
  registry (static table).
- `__pycache__` in OLD/src/sqlearn/helpers holds compiled files only; ignored.

## Per-helper table

Legend for "Where computed": SQL = DuckDB aggregate/GROUP BY; Py = rows or
intermediate tables pulled into Python; Mixed = SQL for the bulk, Python for the
last step.

| Helper (file) | What it computes | Where | Statistical method / correctness | Deps beyond duckdb |
|---|---|---|---|---|
| `profile` (profile.py:L86-L119) | per-column nulls, distinct count; numeric min/max/mean/STDDEV_POP | SQL (2 queries, second only for row count: L112) | fine; alias unquoted (L128) | none (dataclass) |
| `analyze` (analyze.py:L179-L323) | basic: count, nulls, unique, mean, population std, min, max, MEDIAN, Q1/Q3 (QUANTILE_CONT), SKEWNESS, KURTOSIS; top-N values per categorical; `level="medium"` adds distribution; `"deep"` adds all primitives | SQL; top values one GROUP BY per categorical col (L401-L415) | DuckDB SKEWNESS/KURTOSIS are sample-adjusted, KURTOSIS is excess (inf from usage as excess in normality.py:L714-L735); `columns`, `sample` ignored for the basic part (docstring L208-L209) | none beyond sub-helpers |
| `distribution` (distribution.py:L160-L276) | percentiles (default 1,5,10,25,50,75,90,95,99), equal-width histogram via FLOOR bucket, 50-point CDF via APPROX_QUANTILE, skew, kurtosis, CV, Tukey fences; categorical: top-10, Shannon entropy in bits, cardinality ratio | SQL, ~3 queries per numeric col, 3 per categorical | `approximate=True` uses APPROX_QUANTILE so IQR and whiskers are approximate (L357, L419-L420); integer percentiles only; histogram edges interpolated as float literals into SQL (L523) | none |
| `normality_tests` (normality.py:L192-L294) | Jarque-Bera from SQL skew/kurt; KS, Shapiro-Wilk, Anderson-Darling, D'Agostino-Pearson, Lilliefors; consensus verdict; Bonferroni / BH-FDR across columns x tests | Mixed: skew/kurt in SQL (L408-L430); everything but JB pulls all non-null values with `fetchall` (L764-L779) | JB formula correct (L714-L760). KS wrongly uses N(0,1) after standardising by sample mean/std (L782-L831), p-values invalid (conservative). Anderson ignores `alpha` (fixed 5 % critical value, L968-L1020). Shapiro subsampled to 5000 (L907-L950). Verdict = majority of "passed" (L641-L673) | numpy, scipy (shapiro, anderson, normaltest, kstest, chi2), statsmodels (lilliefors, multipletests) |
| `missing_patterns` (missing.py:L122-L220) | per-col null count/%, top-K null-bit patterns, Jaccard co-missingness, CORR(is_null, target), mechanism hint, imputation recommendation | SQL: 1 aggregate, 1 GROUP BY, 1 big FILTER aggregate for pairs (L449-L512), 1 CORR aggregate (L287-L330) | patterns / Jaccard correct. Mechanism hint is thresholds on missing % and target correlation (L250-L265), not a test (docs admit "hints": missing.md:L92-L94). CORR needs numeric target | none |
| `outliers` (outliers.py:L150-L245) | z-score (population sigma), IQR/Tukey fences, MAD modified z (0.6745 constant), Mahalanobis with chi-square cut; `auto` picks zscore vs MAD from skew/kurt | Univariate: SQL stats then a second SQL scan (L419-L470). Mahalanobis: Py (all rows, numpy) (L614-L689) | formulas correct (MAD: Iglewicz-Hoaglin). Row ids unstable (see Defects). MAD=0 returns zero outliers (L564-L567) | numpy, scipy.stats.chi2 (Mahalanobis only) |
| `cardinality` (cardinality.py:L124-L203) | non-null count, COUNT DISTINCT, ratio, top-K with pct, dominant value, 8-tier class, encoder recommendation | SQL: 1 aggregate + 1 GROUP BY per column | tier logic L368-L423; `id_like` ignores column type (see Defects) | none |
| `target_analysis` (target.py:L101-L195) | target type (numeric if >20 distinct, L259), per-feature strength (Pearson for num/num, correlation ratio eta for num feature / categorical target, Cramér's V cat/cat), rank, leakage flag at 0.95, class balance + imbalance verdict | SQL for CORR and eta; Cramér's V contingency table in Py (L392-L450) | no p-values ever (`p_value=None`, L523); categorical features skipped for numeric targets (L278-L282) | none |
| `correlations` (correlations.py:L104-L188) | Pearson (CORR), Spearman (CORR of RANK), Kendall (pair counting), Cramér's V, eta | Mixed: Pearson SQL (one scan per pair, L207-L213); Spearman SQL view; Kendall SQL self-join O(n²) (L291-L305); Cramér's V Py | see Defects | none |
| `explore` (explore.py:L459-L556) | grid expansion over list-valued ctor params, k-fold loop, metrics rmse/mae/r2/accuracy/f1/custom, two-phase sample preview, ranking | SQL fold views; metrics in pure Python lists (L195-L275); target column fetched to Py per fold (L315-L326) | invalid design (see Defects) | none (no numpy in metrics) |
| `explain` (explain.py:L19-L72) | text narrative over `ExploreResult`: winner, margin, close contenders (1 %), fold-stability warning (std > 15 % of mean) | Py, text only | fine; population std (L190-L200). Doc says "within 5 %" (search.md:L185), code uses 1 % (explain.py:L127) | none |
| `lineage` (lineage.py:L84-L159) | trace a column through a fitted pipeline: action, learned params, rename/drop | no SQL, derived from fitted state | works by naming convention `f"{col}__"` prefix in `step._params` (L162-L174) | none |
| `model_info` (model_info.py:L135-L160) | static registry of ~20 model families: needs_scaling, handles_nulls, needs_encoding, notes | static dict | opinion table; sklearn-biased (e.g. "sklearn GBM needs encoding", L70) | none |
| `quick` (quick.py:L12-L57) | auto-pipeline: mean-impute + Scale numeric, mode-impute + OneHot categorical | SQL via backend describe | does not exclude the target column from steps (inf, L46-L54) | none |
| `peek` (peek.py:L18-L62) | first N rows of fitted-pipeline output (`LIMIT n`) | SQL | needs a fitted pipeline, yet quickstart calls `sq.peek("data.parquet")` (quickstart.rst:L174) | none |
| `attach` (attach.py:L12-L45) | `ATTACH '<uri>' AS name (READ_ONLY)` | SQL | uri and name interpolated unescaped (L38-L42) | none |
| `connect` / `connection_info` (connect.py:L36-L120) | swap the module-global DuckDB connection (memory/persistent/own), memory_limit regex, info dict | SQL | sets private `backend._CONNECTION` (L67-L77); `conn=` path does not close old connection | none |
| `concat` / `concat_query` (concat.py:L29-L75) | UNION ALL of sources, `align=True` fills missing columns with NULL; creates view `__concat_N__` | SQL, via sqlglot AST | file-source detection by `.parquet`/`.csv` suffix only (L125-L129) | sqlglot (runtime) |
| `merge` / `merge_query` (merge.py:L29-L95) | join (inner/left/right/outer/cross), `on` / `left_on,right_on`, suffix handling; creates view `__merge_N__` | SQL, via sqlglot AST | see Defects (right/outer key) | sqlglot (runtime) |
| `_sample` (_sample.py:L14-L78) | validates `sample=`; float -> `USING SAMPLE p PERCENT (BERNOULLI, seed)`, int -> `RESERVOIR (n ROWS) REPEATABLE seed` | SQL clause builder | fine; reservoir "repeatable" is only deterministic single-threaded in DuckDB (inf from DuckDB docs, not verified) | none |
| `_render` (_render.py:L17-L122) | sparkline, inline HTML bar, aligned text table | Py, pure | `sparkline` min-max scales (not zero-based); docstring says "scaled to max" (L20) | none |
| `_primitive_base` | see Summary | Py | `to_dict` via `dataclasses.asdict` (L56-L62): tuple keys in `co_missingness` are not JSON-serialisable (inf) | none |
| `sklearn_adapter` / `from_sklearn` | see scikit-learn bridge | | | numpy (adapter); no sklearn import |
| `__init__` (L1-L25) | exports analyze, attach, concat, correlations, lineage, merge, peek, profile only (other primitives imported lazily elsewhere) | | | |

## Computed outside SQL

Pulled into Python / numpy (breaks the "larger than memory" promise, and the old
docs claim otherwise: analysis.md:L27-L28 says "no round-trip through pandas"):

- `normality_tests`: KS, Anderson, D'Agostino, Lilliefors read every non-null
  value into a Python list then numpy (`_fetch_non_null_values`,
  normality.py:L764-L779). Shapiro is capped at 5000 rows (L907-L950). Only JB
  and skew/kurt are SQL.
- `outliers(method="mahalanobis")`: `fetchall()` of all rows x all columns,
  Python list comprehension to float array, `np.cov`, `np.linalg.inv` with
  `pinv` fallback, `np.einsum`, `scipy.stats.chi2.ppf` (outliers.py:L636-L689).
  The docs admit it (outliers.md:L171-L173). Can be done in SQL: covariance via
  COVAR_POP, small k x k inverse in Python, distance as a SQL expression. (inf:
  feasible)
- Univariate outliers: stats are SQL, but the flagged `(rid, value)` rows are
  fetched into Python (L463, L520, L579), so a loose threshold on a huge table
  returns millions of row ids into a tuple (`row_ids`).
- `correlations`: Cramér's V chi-square loops in Python over a GROUP BY table
  (correlations.py:L371-L403); Kendall is SQL but quadratic (L291-L305); Pearson
  issues one scan per pair (L207-L213) instead of one query for all pairs.
- `target_analysis._cramer_v`: Python chi-square over the GROUP BY table
  (target.py:L414-L450). Cardinality-product sized.
- `explore`: target column per fold fetched to Python lists; metrics are pure
  Python (explore.py:L315-L326, L195-L275).
- `explain`: Python only, but small.
- `analyze` top values, `cardinality` top-K, `distribution` categorical: SQL
  GROUP BY with LIMIT; only the top rows come back (fine).
- Mixed note: histogram `counts` are padded in Python from the GROUP BY
  (distribution.py:L530-L534) (fine, small).

## scikit-learn bridge

- `as_sklearn()` / `SklearnAdapter` (sklearn_adapter.py:L19-L106): a duck-typed
  wrapper (no sklearn import; "keeps the dependency optional", L22-L23).
  `fit(X, y)` calls
  `pipeline.learn(X, target=y if isinstance(y, str) else None)` (L49-L50);
  `transform` calls `apply(X, out="numpy")` (L68). So `y` as an array is
  silently dropped, `X` must be something the DuckDB source resolver accepts
  (path / DataFrame), and numpy output loses column names. `get_params` returns
  `{"pipeline": ...}` and `set_params` only sets `pipeline` (L84-L106): not a
  real BaseEstimator, so `sklearn.base.clone` and `GridSearchCV` param grids
  (inf) will not work as the quickstart claims (quickstart.rst:L196-L206). The
  quickstart passes an already-fitted pipeline then calls `fit` again.
- `from_sklearn()` (from_sklearn.py:L31-L82): reads `.steps` (duck-typed), maps
  `type(transformer).__name__` through a 16-entry dict (L11-L28) to a sqlearn
  class, instantiates with no arguments (`sq_cls()`, L78). Learned/constructor
  hyperparameters (`with_mean`, `strategy`, `n_bins`, `categories`) are
  discarded; unsupported steps raise ValueError (L72-L75). Two targets in the
  map were not exported by the 16-symbol API (api.rst:L4: Scale, MinMaxScale,
  Impute, OneHot, Ordinal only) so mapping would fail at `getattr(sqlearn, ...)`
  (inf, api.rst list L52-L74).
- Notebooks use scikit-learn only to fetch data:
  `sklearn.datasets.fetch_california_housing`
  (OLD:examples/v04/deep_analysis.ipynb, cell "Load a dataset";
  explore_and_explain.ipynb same). No scikit-learn model is ever fitted in v0.4.
- `explore.py` and `search.md:L205-L213` position `sq.explore()` as a
  GridSearchCV replacement, but it never fits a model (see Defects).
- `model_info.py` is a table of what scikit-learn-style models need; it has no
  scikit-learn dependency.
- For the new project (independent at runtime): drop `from_sklearn` and
  `as_sklearn` as runtime features. If an interop story is wanted later, keep it
  as an optional separate package or doc recipe, and a true bridge would need
  `get_params`/`set_params`/`clone` semantics (see "What the core must
  provide").

## Worth keeping for the exploration app

1. **Column profile card** = `analyze` basic + `distribution`: counts, null %,
   distinct, mean/std/min/max/quartiles/skew/kurtosis, percentile ladder,
   equal-width histogram (counts only, edges derivable), 50-point CDF, entropy,
   top-N. All SQL. OLD:src/sqlearn/helpers/analyze.py:L374-L398;
   distribution.py:L348-L376, L492-L535, L538-L557, L603-L613. Keep
   exact-vs-approximate toggle (`APPROX_QUANTILE` vs `QUANTILE_CONT`) as an app
   setting.
2. **Missingness view**: per-column %, UpSet-style top patterns via
   `GROUP BY (col IS NULL ...)`, Jaccard co-missingness via `COUNT(*) FILTER`,
   optional CORR(is_null, target) for a numeric target. missing.py:L393-L442,
   L449-L512. The 50-column cap rule (L445-L471) is a sensible UI guard. Drop
   the MCAR/MAR/MNAR labelling, or word as "correlated with target" only.
3. **Cardinality / ID / near-constant triage** with encoder suggestions
   (cardinality.py:L368-L440). Keep the idea, fix `id_like` for float columns
   and make the numeric exception explicit.
4. **Target relations panel**: eta, Cramér's V, Pearson, class balance with
   imbalance ratio buckets 1.5/3/10 (target.py:L494-L506), leakage flag. Add
   p-values or at least a bias-corrected Cramér's V; add categorical-feature vs
   numeric-target case.
5. **Outlier panel**: z-score / IQR / MAD are cheap SQL; keep the `auto` rule
   (|skew| <= 0.5 and kurtosis in [-1, 2] -> zscore else MAD,
   outliers.py:L273-L281), but return counts plus a SQL predicate (not row id
   lists); filter / flag in SQL.
6. **Normality**: JB is SQL-only and sufficient for a screening signal; use
   skew/kurt, a QQ-style quantile table (from the CDF points) rather than six
   tests with a "consensus vote". The doc's own advice at scale
   (normality.md:L96-L103) is right: p-values are meaningless at large n.
7. **Sampling UX**: the result carries `sampled`, `sample_size`, and the
   text/HTML banner "Computed on N-row sample - not for final decisions"
   (distribution.py:L128-L154). Keep this pattern; the sampling guide's list of
   what breaks (correlations, rare categories, class balance, outlier counts,
   temporal order) (sampling.md:L51-L67) is a good in-app help text. Add a
   stratified sample for rare classes (promised as future).
8. **Result rendering contract**: text + HTML + dict from one dataclass;
   dependency-free sparklines and HTML bars (_render.py). For an app, the JSON
   (`to_dict`) is the real interface; keep the library plotting-free
   (analysis.md:L142-L145).
9. **Pipeline-aware exploration**: `lineage(fitted, col)` (per-column trace
   through a fitted pipeline) and `peek` (LIMIT n of pipeline output) map
   directly onto a node-based editor's "inspect this node" action.
10. **Multi-source**: `attach`, `concat(align=True)`, `merge` (view-returning,
    `_query` variants that return the AST without executing). Good fit for a
    data-prep node in the editor; reimplement without sqlglot if the core avoids
    it.
11. **Static advice tables** (`model_info`, `_ENCODING_RECOMMENDATIONS`,
    `_recommendation`) as in-app tooltips; low cost.
12. **Notebooks** are good acceptance scenarios: California housing deep audit,
    synthetic MCAR/MAR/MNAR missingness dataset with MissingIndicator + Impute.
    OLD:examples/v04/deep_analysis.ipynb; missing_patterns.ipynb (cells "Build a
    synthetic dataset", "Build a pipeline that handles the missingness").

## What the core must provide for these

Inferred from the helpers' needs; tied to the part order in
docs/architecture/overview.md (not re-read here).

- **Data sources**: one `resolve_source` that turns a path
  (parquet/csv/glob/S3), table/view name, or DataFrame/Arrow into a safe SQL
  relation; quoting helpers for identifiers and string literals (the old code
  interpolates unescaped: attach.py:L38-L42, backend resolve_source
  `read_parquet('{data}')`, explore `HASH(...)`). Schema discovery returning
  column name -> type plus type families (numeric / categorical / temporal /
  boolean); the old `NUMERIC_TYPES` / `CATEGORICAL_TYPES` split ignored dates
  (target.py:L336-L337).
- **Safe aggregate builder**: a tiny API that takes (column, aggregate) pairs,
  aliases positionally (`c0_mean`), executes one query, and returns a dict keyed
  by (column, stat). Replaces the string-concatenated `f"{col}__stat"`
  convention used in 8 files.
- **Single connection / session object** (not a module global): the helpers poke
  `backend._conn` and `backend._CONNECTION` (e.g. analyze.py:L414,
  connect.py:L67-L77). A public `execute(sql) -> rows/arrow/relation` and
  `cursor()` are needed; the app needs several sessions and
  cancellation/timeouts (the old `timeout=` was never implemented, "Reserved" in
  8 docstrings).
- **Deterministic row identity**: outlier `row_ids` and `__sqlearn_rid__`
  (outliers.md:L108) need a stable row id. DuckDB `rowid` for tables, or an
  ordered `ROW_NUMBER() OVER (ORDER BY ...)` for views / files; the old
  `ROW_NUMBER() OVER ()` is unordered.
- **Sampling** primitive in core: validated `sample=`, seeded, correctly placed
  relative to `WHERE` (DuckDB rejects `USING SAMPLE ... WHERE` at the same
  level, as a comment in distribution.py:L514-L517 explains;
  normality.py:L773-L778 and `_fetch_shapiro_values` L938-L944 ignore that),
  plus stratified option.
- **Cancellable, bounded queries and progress**: needed for a GUI over big
  files.
- **Statistics kernels in SQL** the core should own: quantiles (exact +
  approximate), CORR/COVAR matrix in one pass, rank (average rank with ties and
  NULL handling) for Spearman, histogram/width_bucket, contingency table with
  chi-square and bias-corrected Cramér's V, group SS (eta), skewness/kurtosis
  with documented conventions (population vs sample). No scipy: chi-square
  survival and normal CDF/quantile can come from DuckDB (`erf`-based) or a tiny
  pure-Python function; Shapiro-Wilk would need to be dropped or implemented.
- **Result base class** with `to_dict()` that is JSON-safe (convert tuple keys),
  stable schema versioning, and an HTML/text renderer hook. Reuse the
  `PrimitiveResult` shape.
- **Fitted-state introspection** (`steps`, resolved columns, params keyed by
  column, drop / rename) so `lineage` and node-inspection do not depend on
  naming conventions (`f"{col}__"` prefix in lineage.py:L162-L174, `_mapping`
  attribute in L205-L208).
- **Estimator parameter protocol** (`get_params`/`set_params` or equivalent) if
  grid search or the sklearn-style API (ADR 0003) is kept; `explore` used
  `inspect.signature` + attribute lookups and `type(step)(**params)`
  (explore.py:L112-L137), which is fragile.
- **Metrics and cross-validation** in core only if a model-fitting story exists;
  the old metric set (rmse, mae, r2, accuracy, f1 binary) is trivial and
  SQL-expressible over a prediction column. Fold assignment must be a
  materialised, seeded column (see Defects).
- **Dialect / SQL export** is out of scope for these helpers but concat/merge
  assumed sqlglot; decide in core whether sqlglot is allowed (ADR 0004 allows
  only duckdb without a written reason).
- **Optional extras**: if scipy/statsmodels tests are kept, they belong in an
  optional package outside core, behind explicit ImportError with install hint
  (done well in normality.py:L344-L365).

## Defects

Numbered; severity H/M/L. Citations are to the old code.

Correctness (statistics)
1. H - KS normality test standardises with the sample mean/std then compares to
   N(0,1) (normality.py:L782-L831). Estimated parameters make the standard KS
   p-value invalid (too large); it should be Lilliefors. Doc even lists
   `lilliefors` as "KS with estimated mean/std" (normality.md:L17).
2. M - Spearman uses `RANK()` (min rank for ties) not average rank, and ranks
   are computed over all rows independently per column, including NULLs (NULLs
   sort last and receive ranks), so pairs with NULLs are corrupted
   (correlations.py:L240-L243). `n` is `COUNT(*)` (L252). Heavy ties (integers)
   give a biased coefficient.
3. M - Kendall is tau-a (concordant - discordant over all pairs, L313), ties are
   ignored in the denominator; O(n²) CROSS JOIN (L302), unusable beyond a few
   thousand rows; no n/nulls recorded (L315). Row order via
   `ROW_NUMBER() OVER ()` unordered (L285).
4. M - eta in `correlations` uses the grand mean over all rows where the numeric
   is non-null, but group means only over rows where the category is also
   non-null (correlations.py:L450-L475); inconsistent denominator when the
   category has NULLs. `target._correlation_ratio` handles it correctly via a
   filtered subquery (target.py:L356-L358).
5. M - Cramér's V has no bias correction and is computed over all observed
   levels; with small n and many levels it is inflated
   (correlations.py:L350-L403; target.py:L392-L450). Flat 0.95 leakage threshold
   on it will flag high-cardinality categoricals / IDs.
6. M - Missingness mechanism: labels MCAR/MAR/MNAR derived from missing % and
   correlation with the *target* only (missing.py:L250-L265). "MAR" is simply
   5-40 % missing with low target correlation; MNAR cannot be detected from
   observed data. Docs claim MAR is detected via co-missingness (missing.md:L89)
   but code does not use it. Also `CORR(CASE ... END, target)` requires a
   numeric target; categorical targets will error (inf).
7. M - `id_like` is assigned to any column with unique/non-null >= 0.95
   regardless of type (cardinality.py:L398-L399), so every continuous float
   feature (housing columns in the notebook) is reported "drop - likely
   identifier". The notebook text hides this: "treats them as continuous"
   (deep_analysis.ipynb, cardinality cell). The code contains a dead branch that
   does nothing for numerics (L405-L412, both paths return the same tier).
8. M - Docs vs code for cardinality: documented tiers <=20 / 21-100 / 101-1000
   and order near_constant before id_like (cardinality.md:L18-L22, L89-L98) vs
   code <=10 / <=50 / <=1000 and id_like before near_constant
   (cardinality.py:L417-L423, L396-L401).
9. L - Outlier MAD returns zero outliers when MAD = 0 (outliers.py:L564-L567);
   common for integer columns; should fall back to mean absolute deviation.
10. L - Outliers `auto` calls `distribution()` on the full data ignoring
    `sample`/`approximate` (outliers.py:L267) and uses kurtosis band [-1, 2];
    the distribution doc interprets `kurtosis > 3` as heavy-tailed
    (distribution.md:L72), but DuckDB kurtosis is already excess (so > 0 is
    heavy-tailed): inconsistent threshold.
11. L - JB uses DuckDB's sample-adjusted skew/kurtosis, so the statistic is
    slightly off vs scipy.jarque_bera (inf; magnitude negligible at large n).
12. L - Bonferroni divides alpha by number of (column x test) p-values, treating
    several tests of the same hypothesis as independent
    (normality.py:L493-L535); conservative, and the doc says "across columns"
    (normality.md:L136-L137). `_consensus_verdict` returns "normal" when no
    tests ran (L641-L673).
13. L - `target_analysis` treats a numeric target with <= 20 distinct values as
    classification (target.py:L259), so an integer count or rating target
    silently becomes classification; categorical features are ignored for
    numeric targets contrary to the docs table (target-analysis.md:L14-L19 vs
    target.py:L278-L282). `relation_type` documents spearman/mutual_info but
    they are never produced (target-analysis.md:L67; target.py:L289-L295).
14. L - `coefficient_of_variation` is `|std/mean|` with population std, and
    falsy-zero mean check (`if ... and mean`) (distribution.py:L418).

Correctness (engineering) 15. H - `explore()` has no model. `_score_fold` fits
the pipeline on the train fold, applies it to the test fold, and compares the
*transformed target column* with the raw target (explore.py:L432-L456).
Imputers/scalers rarely change the target, so scores are near-meaningless (rmse
of a z-scored target vs raw target mostly reflects scaling). The docs sell it as
k-fold model search / GridSearchCV replacement (search.md:L205-L217). 16. H -
Fold assignment is
`ROW_NUMBER() OVER (ORDER BY HASH(CAST(RANDOM() * seed AS BIGINT)))` inside a
`CREATE TEMP VIEW` (explore.py:L289-L296). A view is re-evaluated at each query,
`RANDOM()` is unseeded (no `setseed`), so the train query and test query see
different assignments: leakage and uneven folds. The docstring says
`HASH(rowid * seed)` (L278-L283) - mismatch. Also `seed=0` makes every row's
value 0. 17. H - `_score_fold` swallows all exceptions and sets
`y_pred = y_true` (explore.py:L447-L451): any failure scores perfectly. 18. M -
Row count mismatch is hidden by trimming (explore.py:L452-L456); the trimmed
pairs are no longer aligned if rows were filtered. 19. M - Cache key excludes
`columns` and list params (explore.py:L348-L374), so candidates differing only
by `columns` share one cached score; the docs' "shared-prefix caching"
(search.md:L18-L19, L291) is simply per-whole-config memoisation. 20. M -
Outlier `row_ids` come from `ROW_NUMBER() OVER ()` with no ORDER BY in separate
queries (outliers.py:L457, L514, L573, L642); on Parquet / multithreaded scans
the numbering is not guaranteed stable between queries, so unions across columns
(`all_outlier_rows`) and `__sqlearn_rid__ NOT IN` filters (outliers.md:L108, a
column that does not exist in the data - inf) are unreliable. With `sample=` the
ids are positions in the sample, not the table. 21. M - Aliases built from raw
column names: `COUNT(x) AS {col}__count` (analyze.py:L381, profile.py:L129,
distribution.py:L364, L375). Names with spaces or punctuation break;
cardinality/target use `_safe_alias` which maps distinct names to the same alias
(`a b` and `a_b`) (cardinality.py:L443-L451). Columns containing double quotes
are not escaped anywhere (`f'"{col}"'`). 22. M - SQL injection / quoting:
attach.py:L38-L42; read-source literal `read_parquet('{data}')` (backend
resolve_source, OLD:src/sqlearn/backend/duckdb.py:L154-L162); numbers
interpolated from computed floats (`{mu_f}`, `{low}`, may print `nan`/`inf` or
lose digits) (outliers.py:L460, L517, L576). 23. M - `USING SAMPLE` followed by
`WHERE` at the same query level is rejected by DuckDB (the comment in
distribution.py:L514-L517 and L575-L576 says so), yet
`normality._fetch_non_null_values` emits
`FROM {source} {sample_clause} WHERE ...` (normality.py:L773-L778) and
`_fetch_shapiro_values` (L946), as do the other `{source} {sample_clause} WHERE`
forms (inf: will error when `sample=` is set; not executed). 24. M - Sampling
re-draws the sample for each query (many queries per call); with BERNOULLI and a
fixed seed the draw is reproducible, but results from different queries in one
call (e.g. count vs top values) are not guaranteed to refer to the same rows if
the engine runs multi-threaded (inf). 25. M - `DistributionResult.row_count` and
`sample_size` both equal the sampled count (distribution.py:L274), so the true
table size is lost when sampling; `PrimitiveResult.row_count` doc says "total
row count" (_primitive_base.py:L25-L27). 26. M - `merge`: for `right`/`outer`
joins, key columns are taken from the *left* alias only (merge.py:L226-L237,
L241-L242), so right-only rows lose their key (NULL). A right column whose name
equals a left key but not a right key is silently dropped (L241-L242 with
`overlap` excluding keys, L223). `outer` join kind string `"full outer"` (L263)
relies on sqlglot accepting it (inf). Python 3.12 dedup not an issue. 27. L -
`concat(align=True)` unions without type reconciliation (concat.py:L164-L168):
DuckDB will cast or fail; no `UNION BY NAME`. Also file-source test is by suffix
`.parquet`/`.csv` only, so `.parquet.gz`, globs or `s3://` paths with other
suffixes become table names (concat.py:L125-L129 vs backend resolve). 28. L -
`peek` needs a fitted pipeline but the docs say `sq.peek("data.parquet")`
(quickstart.rst:L170-L175); `quick` fits `Scale` etc. on all numeric columns
including the target (quick.py:L46-L54, inf). 29. L - `connect(conn=...)` never
closes the previous connection; `connect()` with memory_limit applies after
replacing (connect.py:L66-L90); state kept in module global `_CONNECTION` (not
thread/session safe). 30. L - `SklearnAdapter` ignores array `y`, returns numpy
without feature names, does not implement `get_params(deep)` or
`__sklearn_clone__`, so `GridSearchCV` / `clone` will fail
(sklearn_adapter.py:L39-L106). 31. L - `from_sklearn` discards all
hyperparameters (from_sklearn.py:L78) and maps names to classes the 16-symbol
API does not export. 32. L - Sparkline docstring says "scaled to the max" but
scales min-to-max (_render.py:L20, L37-L46); first doctest output looks
inconsistent (inf). 33. L - `text_table` uses `zip(strict=False)` and header
centring; unicode width not handled (_render.py:L109-L120). 34. L -
`PrimitiveResult.to_dict` via `asdict` keeps non-string tuple keys
(`co_missingness`) and `inf` floats (imbalance_ratio=inf, target.py:L485) that
are not valid JSON.

Docs / claims 35. M - "no dependencies beyond DuckDB and numpy"
(analysis.md:L27-L28) vs reality: sqlglot is a runtime dependency
(OLD:pyproject.toml:L23-L27), numpy is core, scipy / statsmodels are optional
extras (pyproject L29-L31) and are *required* for Shapiro, Anderson, D'Agostino,
Lilliefors, KS (normality.py:L798-L799), Mahalanobis (outliers.py:L637), FDR.
The normality doc says KS and JB "work without SciPy" (normality.md:L28-L29),
but KS imports scipy (normality.py:L799). 36. L - quickstart says Python 3.10+
and "16 public symbols" (quickstart.rst:L16; api.rst:L4) but api.rst documents
none of the analysis helpers (only profile, peek, attach under "Helpers",
api.rst:L100-L104), nor correlations, lineage, merge, concat, quick, model_info,
explore, explain. 37. L - Normality doc: "Shapiro always samples to <= 5000"
(normality.md:L148) vs code only when n > 5000; sampling.md:L192 says it samples
"regardless of your sample= setting" (also only true above 5000). 38. L -
search.md: explain "close contenders within 5 %" (L185) vs code 1 %
(explain.py:L127); `f1` is "Macro F1" (search.md:L83) vs code binary F1 with 0/1
labels (explore.py:L252-L270); `ORDER BY RANDOM(seed)` described (L110) vs code.
39. L - outliers.md:L169-L170 says univariate methods are "single-pass
aggregates ... essentially free"; code does 2-3 aggregates plus a window scan
per column (outliers.py:L435-L463, L548-L579). 40. L - Many parameters accepted
but unused (`approximate` in cardinality, missing, normality, outliers, target;
`timeout` everywhere), documented as "Reserved".

## Files covered

Helpers (OLD:src/sqlearn/helpers/):
- [x] `__init__.py` - exports 10 names, others imported lazily by analyze
- [x] `_primitive_base.py` - PrimitiveResult ABC (text/html/dict)
- [x] `_render.py` - sparkline, html_bar, text_table
- [x] `_sample.py` - validate_sample_param, build_sample_clause (BERNOULLI /
      RESERVOIR)
- [x] `analyze.py` - basic per-column stats + level medium/deep wrapper
- [x] `attach.py` - ATTACH wrapper, unescaped SQL
- [x] `cardinality.py` - cardinality tiers + encoder recommendation
- [x] `concat.py` - UNION ALL view via sqlglot
- [x] `connect.py` - connection swap / memory_limit / info
- [x] `correlations.py` - Pearson / Spearman / Kendall / Cramér's V / eta
- [x] `distribution.py` - percentiles, histogram, CDF, entropy
- [x] `explain.py` - text narrative for ExploreResult
- [x] `explore.py` - grid + k-fold "pipeline search" (design invalid)
- [x] `from_sklearn.py` - sklearn Pipeline -> sqlearn Pipeline via name map
- [x] `lineage.py` - column trace through fitted pipeline
- [x] `merge.py` - join view via sqlglot
- [x] `missing.py` - missing patterns, Jaccard, mechanism hint
- [x] `model_info.py` - static preprocessing advice registry
- [x] `normality.py` - six normality tests + corrections + verdict
- [x] `outliers.py` - zscore / IQR / MAD / Mahalanobis
- [x] `peek.py` - LIMIT n of fitted pipeline output
- [x] `profile.py` - single-query profile
- [x] `quick.py` - auto pipeline builder
- [x] `sklearn_adapter.py` - duck-typed sklearn wrapper
- [x] `target.py` - target_analysis (relations, leakage, class balance)
- [x] `__pycache__/` - compiled artefacts only, not read

User guide (OLD:docs/user-guide/):
- [x] `analysis.md` - family overview, shared params, rendering surfaces
- [x] `cardinality.md` - cardinality chapter (tier thresholds differ from code)
- [x] `distribution.md` - distribution chapter + interpretation table
- [x] `missing.md` - missingness chapter (MCAR/MAR/MNAR "hints")
- [x] `normality.md` - normality chapter (dependency claims inaccurate)
- [x] `outliers.md` - outliers chapter (Mahalanobis in numpy, rid filter)
- [x] `sampling.md` - sampling limits, verification advice, HDD note
- [x] `search.md` - explore / explain chapter (overstates capabilities)
- [x] `target-analysis.md` - target analysis chapter (doc/code mismatch)

Examples (OLD:examples/v04/):
- [x] `deep_analysis.ipynb` - California housing,
      `analyze(level="deep", target=...)`; sklearn used only for dataset
- [x] `explore_and_explain.ipynb` - explore / explain / custom metric / sample
      preview on housing
- [x] `missing_patterns.ipynb` - synthetic MCAR/MAR/MNAR dataset,
      MissingIndicator + Impute pipeline

Docs:
- [x] `OLD:docs/api.rst` - Sphinx autodoc list of 16 symbols; no analysis
      helpers
- [x] `OLD:docs/quickstart.rst` - install, pipeline, SQL export, custom,
      profile, as_sklearn interop

Also read for context (outside batch, one-line each):
`OLD:src/sqlearn/backend/duckdb.py` (resolve_source, execute_aggregate L85-L92),
`OLD:pyproject.toml` (deps L23-L31).

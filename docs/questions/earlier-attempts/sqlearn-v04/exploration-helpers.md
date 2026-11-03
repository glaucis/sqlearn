---
type: question
tags: [earlier-attempts, data-exploration, statistics, applications]
summary: "Lessons from sqlearn v0.4's analysis helpers for the later data-exploration application, and what the library core must provide for it."
related: [docs/architecture/overview.md, docs/questions/earlier-attempts/sqlearn-v04/review.md, docs/questions/application-front-end.md]
---
# What do sqlearn v0.4's analysis helpers teach the exploration app?

sqlearn v0.4 (see [its review](review.md) for the source and
citation style) shipped nine analysis helpers: `profile`, `analyze`,
`distribution`, `normality_tests`, `missing_patterns`, `outliers`,
`cardinality`, `target_analysis` and `correlations`, plus `explore` and
`explain`. They belong to the later data-exploration application, not the
library core, but the core must provide some of what they need. Citations are
`OLD:src/sqlearn/helpers/…`. The old docs disagree with the code in many places
(tier thresholds, "KS works without SciPy", dependencies), so the code is the
better record.

## Worth keeping

- **Column card**: counts, NULL share, distinct, mean, std, quartiles,
  skewness, kurtosis, a percentile ladder, an equal-width histogram, a 50-point
  CDF and top values, all as DuckDB aggregates in one query
  (`distribution.py:L348-L376`). An exact or approximate switch
  (`QUANTILE_CONT` or `APPROX_QUANTILE`) as a setting.
- **Missingness view**: per-column share, top patterns by `GROUP BY` of the
  `IS NULL` bits, Jaccard co-missingness with `COUNT(*) FILTER`
  (`missing.py:L393-L512`), and a cap of 50 columns. Drop the MCAR/MAR/MNAR
  labels: they were thresholds on missing share and target correlation.
- **Cardinality triage**: ID-like, near-constant and encoder suggestions
  (`cardinality.py:L368-L440`), with `id_like` fixed (it fired on every
  continuous float column).
- **Target panel**: eta, Cramér's V (bias-corrected), Pearson, class balance
  with imbalance buckets, a leakage flag.
- **Outliers**: z-score, IQR and MAD in SQL, with the `auto` rule choosing by
  skewness and kurtosis (`outliers.py:L273-L281`). Return counts and a SQL
  predicate, not lists of row ids.
- **Normality**: Jarque-Bera and skewness/kurtosis in SQL as a screen; the
  old docs rightly note that p-values mean little at large n.
- **Sampling honesty**: every sampled result carries `sampled`, its size and a
  banner (`distribution.py:L128-L154`), and the guide lists what sampling
  breaks (rare categories, class balance, temporal order).
- **Result contract**: one frozen dataclass rendered as text, HTML and
  `to_dict()`, with no plotting dependency (`_primitive_base.py:L17-L62`). For
  an app the JSON is the interface.
- **Pipeline inspection**: `lineage(fitted, col)` and `peek` map onto a node
  editor's "inspect this node".
- **Acceptance scenarios**: the notebooks' California-housing audit and the
  synthetic missingness dataset (`OLD:examples/v04/`).

## What went wrong

- **Work pulled into Python**, against the larger-than-memory promise:
  - Five of six normality tests fetched every value into numpy
    (`normality.py:L764-L779`).
  - Mahalanobis fetched all rows (`outliers.py:L636-L689`). It could be done
    in SQL: a covariance matrix with `COVAR_POP` and a k×k inverse in Python.
  - Cramér's V ran its chi-square loop in Python.
  - Kendall was an O(n²) self-join.
  - Pearson ran one scan per pair rather than one query for all pairs.
- **Wrong statistics:**
  - KS against N(0,1) with estimated parameters, which needs Lilliefors.
  - Spearman via `RANK()`, which gives ties the minimum rank and ranks NULLs.
  - Kendall was tau-a.
- **`explore()` was not model selection.** It had no model and scored the
  transformed target against the raw one. Its folds came from unseeded
  `RANDOM()` inside a view, so they could differ between queries, and any
  exception set predictions equal to the truth (`explore.py:L278-L299`,
  `L432-L456`). It should not be ported.
- **scikit-learn bridge:** `as_sklearn()` dropped array `y` and faked
  `get_params`, so `clone` and grid search would fail (inference).
  `from_sklearn()` mapped class names and dropped every hyperparameter.
- **Engineering:**
  - Aliases built from raw column names broke on spaces or punctuation.
  - Paths were interpolated into SQL unescaped.
  - Outlier row ids came from `ROW_NUMBER() OVER ()` with no ordering.
  - `merge` lost the key for right-only rows.
- **Dependencies:** numpy and sqlglot at runtime, scipy and statsmodels as
  extras that most normality tests needed.

## What the library core must provide

These are inferred from the helpers' needs. Each is a candidate for the core
spec or for the part that builds the app.

- One source resolver (paths, globs, tables, data frames) with safe quoting of
  identifiers and literals, and schema discovery with type families that
  include dates and booleans.
- An aggregate-query builder: (column, statistic) pairs in, one query run,
  results keyed by (column, statistic), with no string-built aliases.
- A public session or connection object, not a module global, with
  cancellation and timeouts (the old `timeout=` was never implemented).
- Stable row identity and seeded, correctly placed sampling (DuckDB rejects
  `USING SAMPLE` with `WHERE` at the same level), with a stratified option.
- SQL kernels for quantiles, a correlation and covariance matrix in one pass,
  average ranks with ties, contingency tables, and documented skewness and
  kurtosis conventions, with no scipy.
- Fitted-state introspection (steps, resolved columns, learned values by
  column) so lineage does not depend on naming conventions.
- Fold assignment, if cross-validation comes, as a materialised, seeded column.

---
type: plan
tags: [exploration, eda, profiling, missing-values, correlations, plan]
summary: "Implementation plan for sq.explore (overview 3.6, the module): profile, histogram, top, missing and correlations, computed in DuckDB, returned as relations, validated against exact values with pandas and numpy beside sqlearn."
related: [docs/specs/library-exploration.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0016-validation-method.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Exploration module (`sq.explore`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** five functions, `sq.explore.profile`, `histogram`, `top`,
`missing` and `correlations`, that compute in DuckDB on any input `read`
takes and return a relation (or the form `out=` names).

**Architecture:** a new package `sqlearn.explore`. Each function reads its
input with `sqlearn._inputs.read`, chooses columns with the selectors, builds
its SQL over the source relation, runs it once and materialises the small
answer into a temporary table, which it returns as a relation through
`sqlearn._output.to_output`. Nothing is a step; nothing touches the learning
store or `sq.save`. Rows never reach Python: only the answer does.

**Tech Stack:** Python 3.12, DuckDB (runtime), uv, just, pytest; pandas,
numpy and mpmath as test and validation references.

**Spec:** `docs/specs/library-exploration.md` (approved 2026-11-20). Read it
beside this plan; section numbers below are the spec's.

## Global Constraints

- Every task runs through `just`; Python through `uv run`, never pip or a
  bare `python` (ADR 0001, 0008).
- The runtime dependencies stay `duckdb` and `numpy`; no other import in
  `src/sqlearn/explore/` (numpy only if a task needs it, none should).
- Computation is SQL in DuckDB; only answers reach Python (spec §3, ADR 0002).
- Statistics follow pandas: `std` with `ddof=1`, sample-adjusted skewness and
  excess kurtosis, quartiles by linear interpolation; NULL and NaN are both
  missing and left out of every statistic (spec §3).
- Exact by default; `exact=False` uses `approx_quantile` and
  `approx_count_distinct`, and the `exact` column says which. Never switched
  on sqlearn's own (ADR 0046).
- Every refusal has `Why:` and `Fix:` (ADR 0019, 0046), raised as
  `sqlearn.errors.SqlearnError`.
- British English in prose, American spelling in identifiers (ADR 0010).
- Commits: Conventional Commits, no scope but `hooks`, `site`, `deps`, header
  and body lines at most 72 characters, no AI attribution, the issue number
  in the header.
- Before every commit: `just fmt`, `just check`, `just test`, naming every
  failure; leave the docs tagger's frontmatter edits to unrelated files out
  of commits. Before calling the work done: `just verify`.
- TDD: watch each test fail for the right reason first; tests through the
  public functions, named in `GLOSSARY.md` terms.

## Review Focus

1. **Columns differing only by case** (`a`, `A`) and names that are SQL
   keywords or hold quotes (`select`, `it's`): every name goes through
   `sqlearn._expr.quote`, and both `a` and `A` get their own row (HANDOFF:
   never project `rel.columns` back by name). Test in Task 1.
2. **A name in `cols=` that is not a column**: `Selector.resolve` drops it
   silently, which here would hide a typo. Refused with a `Fix:` naming the
   columns. Test in Task 1.
3. **No rows** (an empty file, a filter giving none): `profile` gives every
   column with `rows` 0 and NULL statistics, `histogram` no bins, `top` and
   `missing` no rows, `correlations` NULL with `rows` 0; never a division
   error. Test in each function's task.
4. **NaN in a float column**, inserted into a DuckDB table (pandas hands NaN
   to DuckDB as NULL): counted as missing and left out of every statistic,
   histogram bin, rank and correlation; `top` counts it with the NULLs under
   `value` NULL. Test in Tasks 2, 4, 5, 7.
5. **The result outlives its input**: a profile of a pandas frame, kept and
   read after another `read` and after the frame is deleted, still holds its
   rows (the answer is materialised, not a view over the frame's
   registration, which is dropped later). Test in Task 1.

---

### Task 0: Branch, issue and the decision

- [ ] **Step 1:** `git switch -c exploration` from `main`.
- [ ] **Step 2:** Open the area's issue with `gh issue create` (title
  "Exploration module: sq.explore (3.6)", label `enhancement`, body linking
  the spec and ADR 0059), add it to the board as the github-pm skill says,
  and use its number (#74) in every commit header.
- [ ] **Step 3:** Write
      `docs/adr/0059-exploration-functions-run-now-and-return-relations.md` from
      spec §5: status accepted (2026-11-20), the three choices (run now, not
      steps; a relation, not a result class; pandas' conventions), the name
      `sq.explore`, and as a consequence that each answer is a small temporary
      table on the connection, kept for its life. Add it to `docs/adr/index.md`
      under "The API".
- [ ] **Step 4:** Commit the spec, this plan, the ADR and the index:
  `docs: specify the exploration module (#74)`.

### Task 1: The package, the shared reading, and `profile`'s counts

**Files:**
- Create: `src/sqlearn/explore/__init__.py`, `src/sqlearn/explore/_common.py`,
  `src/sqlearn/explore/profile.py`
- Modify: `src/sqlearn/__init__.py` (import `explore`, add to `__all__`)
- Test: `tests/src/sqlearn/explore/test_profile.py`,
  `tests/src/sqlearn/explore/test__common.py`

**Interfaces:**
- Produces, in `_common.py`:
  - `columns(source, cols, *, function)`, typed `(Source, Selector | str |
    Sequence[str] | None, *, str) -> list[str]`:
    every column when `cols` is None, else the resolved names in schema order; a
    plain name (or names) absent from the schema is refused: "`{function}` was
    given cols={name!r}, which is not a column. Fix: pass one of {names}."
    (names listed, at most 10, then "…").
  - `answer(sql: str) -> duckdb.DuckDBPyRelation`: runs
    `CREATE TEMP TABLE "__sqlearn_explore_{n}" AS {sql}` on
    `sqlearn._config.connection()` (n from a module `itertools.count`) and
    returns `con.table(...)`.
  - `missing_sql(name: str, dtype: DuckDBPyType) -> str`: the SQL that is
    true when the quoted column is NULL, or NaN for a float type.
- Produces: `sq.explore.profile(data, cols=None, *, exact=True, id_rows=20,
  high_cardinality=50, out=None)`; `data: object`, `exact: bool`, the two
  thresholds `int`, `out: str | Output | None`, returning `Any`.

- [ ] **Step 1: Write the failing tests** in `test_profile.py`:
  - `test_a_profile_has_one_row_per_column_in_input_order`: a frame with
    columns `b, a` gives `column` `["b", "a"]` and the spec §4.1 columns in
    the table's order.
  - `test_missing_counts_null_and_nan`: a DuckDB table of DOUBLE
    `[1.0, NULL, 'NaN', 4.0]` gives `rows` 4, `missing` 2,
    `missing_share` 0.5, `distinct` 2, `distinct_share` 1.0.
  - `test_columns_differing_only_by_case_each_get_a_row` and
    `test_keyword_and_quoted_names_are_profiled` (`select`, `it's`).
  - `test_a_name_that_is_not_a_column_is_refused`: `cols="nope"` raises
    `SqlearnError` with "Fix:" in the message.
  - `test_no_rows_gives_zero_rows_and_null_shares`.
  - `test_the_profile_outlives_its_frame`: profile a pandas frame, `del`
    it, call `sq.explore.profile` on another frame, then the first
    result's `fetchall()` still has its rows.
  - `test_out_hands_back_the_form_named`: `out="pandas"` gives a
    `pandas.DataFrame`.
  - `test_exact_false_says_so`: the `exact` column is False for every row.
  Run `uv run pytest tests/src/sqlearn/explore -q`; expected FAIL
  (`sqlearn` has no `explore`).
- [ ] **Step 2: Implement** `_common.py` and `profile` with every spec §4.1
      column. In this task the numeric, text and date statistics may be NULL
      placeholders typed as the table says (DOUBLE, BIGINT, VARCHAR); `notes` is
      an empty `VARCHAR[]`. The data is scanned once: every column's aggregates
      in one `SELECT` over the source (never a `UNION ALL` of one SELECT per
      column, which scans once per column), then that one result row turned into
      the long form, one row per column, by a `VALUES` list built from the
      fetched values. `distinct` is
      `count(DISTINCT x) FILTER (WHERE NOT missing)`, or `approx_count_distinct`
      when `exact=False`.
- [ ] **Step 3:** Run the tests; expected PASS. Run `just test`.
- [ ] **Step 4: Commit** `feat: profile a dataset's columns (#74)`.

### Task 2: `profile`'s statistics by type

**Files:**
- Modify: `src/sqlearn/explore/profile.py`
- Test: `tests/src/sqlearn/explore/test_profile.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_numeric_statistics_follow_pandas`: on
    `[1.0, 2.0, 2.0, 9.0, NULL]` each of `mean`, `std`, `min`, `q25`,
    `median`, `q75`, `max`, `skewness`, `kurtosis` equals pandas'
    `Series.describe()`, `.skew()`, `.kurt()` within 4 ULPs, and
    `zeros`, `negative`, `infinite` count 0, 0, 0.
  - `test_infinite_values_are_counted_and_left_out`: `[1.0, 'inf', 3.0]`
    gives `infinite` 1, `mean` 2.0, `max` 3.0.
  - `test_integers_and_decimals_are_numbers`: INTEGER and DECIMAL(10,2)
    columns get a `mean` (cast to DOUBLE).
  - `test_a_boolean_mean_is_its_share_true`: `[true, false, true, NULL]`
    gives `mean` 2/3 and `distinct` 2.
  - `test_text_gets_lengths_and_no_numbers`: `["a", "bcd"]` gives
    `min_length` 1, `max_length` 3, `mean` NULL.
  - `test_dates_get_first_and_last_as_text`.
  - `test_one_value_has_null_std_and_shape`: as pandas, `std`, `skewness`,
    `kurtosis` NULL for one non-missing value (pandas gives NaN).
  Run them; expected FAIL on the placeholders.
- [ ] **Step 2: Implement.** Numeric is `sqlearn._selectors._is_numeric` or
  BOOLEAN; infinite values are left out of every statistic as missing ones
  are (`isinf` on float types). `std` is `stddev_samp`, `skewness` and
  `kurtosis` DuckDB's (sample-adjusted, as pandas; checked in the spec),
  quartiles `quantile_cont(x, [0.25, 0.5, 0.75])` once per column, or
  `approx_quantile` when `exact=False`. Dates and timestamps are
  `DATE`, `TIMESTAMP*` and `TIME` types; `first`/`last` are `min`/`max`
  cast to VARCHAR (HANDOFF: zoned timestamps reach Python only as text).
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit** `feat: profile statistics by column type (#74)`.

### Task 3: `profile`'s notes

**Files:**
- Modify: `src/sqlearn/explore/profile.py`
- Test: `tests/src/sqlearn/explore/test_profile.py`

- [ ] **Step 1: Write the failing tests**, each at its boundary (spec §4.1.1):
  - `test_a_constant_column_is_noted`; `test_all_missing_is_noted_not_constant`.
  - `test_an_integer_key_is_id_like` (20 distinct rows) and
    `test_nineteen_rows_are_not_id_like`; `test_a_float_column_is_never_id_like`
    (20 distinct doubles).
  - `test_many_distinct_texts_are_high_cardinality` (51 distinct of 100
    rows) and `test_fifty_distinct_texts_are_not` (50 of 100);
    `test_a_text_key_is_id_like_not_high_cardinality`.
  - `test_the_thresholds_are_settings`: `id_rows=5`, `high_cardinality=3`
    move both boundaries; a non-integer or negative value is refused with a
    `Fix:`.
  - `test_notes_are_listed_in_one_order`: `["all-missing", "constant",
    "id-like", "high-cardinality"]` order when several apply.
- [ ] **Step 2: Implement** the notes in SQL over the counted row, as a
  `list_filter` of `CASE`s, so they never need the source again.
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit** `feat: note constant, id-like and wide columns (#74)`.

### Task 4: `histogram`

**Files:**
- Create: `src/sqlearn/explore/histogram.py`; export from `__init__.py`
- Test: `tests/src/sqlearn/explore/test_histogram.py`

**Interfaces:**
`sq.explore.histogram(data: object, cols=None, *, bins: int = 10, out=None) -> Any`;
columns `column` VARCHAR, `bin` INTEGER, `low`, `high` DOUBLE, `count` BIGINT.

- [ ] **Step 1: Write the failing tests:**
  - `test_bins_match_numpy`: on a random column of 1,000 doubles and
    `bins=7`, `low`/`high` equal `numpy.histogram`'s edges within 2 ULPs and
    `count` equals its counts exactly, the maximum in the last bin.
  - `test_only_numeric_columns_by_default` and
    `test_a_text_column_named_is_refused` (with `Fix:`).
  - `test_a_constant_column_has_one_bin` (`low` = `high`, all rows).
  - `test_missing_and_infinite_values_are_left_out`.
  - `test_bins_must_be_a_positive_integer`: 0, -1, 2.5, True refused.
  - `test_no_rows_gives_no_bins`.
- [ ] **Step 2: Implement:** one query for the extremes of every chosen
  column, then one query assigning each value
  `least(floor((x - min) / width), bins - 1)` and grouping by column and
  bin, with the empty bins filled from `range(bins)` so every bin appears.
  The edges are `min + k * (max - min) / bins` in DOUBLE, as numpy's
  `linspace` computes them; correct the formula if the first test says
  otherwise.
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit**
      `feat: equal-width histograms of numeric columns (#74)`.

### Task 5: `top`

**Files:**
- Create: `src/sqlearn/explore/top.py`; export
- Test: `tests/src/sqlearn/explore/test_top.py`

**Interfaces:**
`sq.explore.top(data: object, cols=None, *, k: int = 10, out=None) -> Any`;
columns `column`, `value` (VARCHAR), `count` BIGINT, `share` DOUBLE.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_commonest_values_match_value_counts`: against pandas'
    `value_counts(dropna=False)` on a text column, ties ordered by value.
  - `test_missing_values_are_one_null_row` (NULL and NaN together).
  - `test_k_caps_each_column` and `test_k_must_be_a_positive_integer`.
  - `test_numbers_are_shown_as_duckdb_writes_them` (`value` of `2.5` is
    `'2.5'`).
- [ ] **Step 2: Implement** with one `GROUP BY column, value` over an
  `UNPIVOT` of the chosen columns cast to VARCHAR (NaN mapped to NULL
  first), ranked with `row_number() OVER (PARTITION BY column ORDER BY
  count DESC, value)`. Measure one unpivot against one query per column on
  20 columns × 1M rows and keep the faster; note the numbers in the commit
  body.
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit** `feat: the commonest values of each column (#74)`.

### Task 6: `missing`

**Files:**
- Create: `src/sqlearn/explore/missing.py`; export
- Test: `tests/src/sqlearn/explore/test_missing.py`

**Interfaces:**
`sq.explore.missing(data, cols=None, *, patterns=10, out=None)`;
columns `missing` (VARCHAR[], in column order), `count` BIGINT, `share` DOUBLE.

- [ ] **Step 1: Write the failing tests:**
  - `test_patterns_match_a_pandas_group_by`: against
    `df.isna().value_counts()` on a frame with three columns and four
    patterns, the empty pattern `[]` among them.
  - `test_patterns_caps_the_rows` and its refusal of 0 or a non-integer.
  - `test_more_than_64_columns_is_refused` with "Fix:" naming `cols=`.
  - `test_nan_counts_as_missing`.
  - `test_no_rows_gives_no_patterns`.
- [ ] **Step 2: Implement** with one `GROUP BY` over the columns' missing
  flags (`missing_sql`), the list built from the flags in column order.
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit** `feat: the commonest patterns of missing values (#74)`.

### Task 7: `correlations`, Pearson

**Files:**
- Create: `src/sqlearn/explore/correlations.py`; export
- Test: `tests/src/sqlearn/explore/test_correlations.py`
- Create: `docs/benchmarks/explore-correlations.md`

**Interfaces:**
`sq.explore.correlations(data, cols=None, *, method="pearson", out=None)`;
columns `column_a`, `column_b` VARCHAR, `correlation` DOUBLE, `rows` BIGINT.

- [ ] **Step 1: Write the failing tests:**
  - `test_pearson_matches_pandas_pairwise`: four columns with missing values
    in different rows; each pair's `correlation` against
    `DataFrame.corr()` within 8 ULPs and `rows` against the pair's complete
    count; p(p−1)/2 rows, `a` before `b` in column order.
  - `test_a_constant_column_gives_null`; `test_nan_is_left_out_of_a_pair`.
  - `test_a_text_column_named_is_refused`; `test_method_must_be_known`
    (`"kendall"` refused, the `Fix:` naming `"pearson"` and `"spearman"`).
  - `test_fewer_than_two_columns_gives_no_pairs`.
- [ ] **Step 2: Implement** with `corr(a, b)` and
  `count(*) FILTER (WHERE a and b present)` per pair, NaN and infinity
  turned into NULL first. Pairs go in chunks of `_PAIRS_PER_QUERY`
  aggregates per statement, each answer appended to the result table.
- [ ] **Step 3: Measure** the chunk size: 1M rows of 50, 200 and 500 random
  doubles written as Parquet with `COPY`, one probe per subprocess, chunk
  sizes 250, 1,000 and 4,000, with `uptime` before and after; set
  `_PAIRS_PER_QUERY` to the fastest that stays within the default memory
  budget, and write the table in `docs/benchmarks/explore-correlations.md`
  (linked from `docs/benchmarks/index.md`).
- [ ] **Step 4:** Run the tests and `just test`; expected PASS.
- [ ] **Step 5: Commit** `feat: pairwise Pearson correlations (#74)`.

### Task 8: `correlations`, Spearman

**Files:**
- Modify: `src/sqlearn/explore/correlations.py`
- Test: `tests/src/sqlearn/explore/test_correlations.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_spearman_matches_pandas_with_ties`: integer columns full of ties,
    no missing values, against `DataFrame.corr(method="spearman")`.
  - `test_spearman_ranks_a_pair_on_its_complete_rows`: two columns missing
    in different rows, against pandas (which ranks each pair on its own
    complete rows).
- [ ] **Step 2: Implement.** Average rank:
  `rank() OVER (ORDER BY x) + (count(*) OVER (PARTITION BY x) - 1) / 2.0`.
  A column with no missing value is ranked once and its pairs with other
  such columns use Pearson on those ranks. A pair where either has missing
  values is ranked again over the pair's complete rows, in its own query;
  say in the docstring that sparse columns cost one pass per pair.
- [ ] **Step 3:** Run the tests and `just test`; expected PASS.
- [ ] **Step 4: Commit** `feat: Spearman correlations on average ranks (#74)`.

### Task 9: Validation

**Files:**
- Create: `validation/sqlearn/explore/__init__.py`,
  `validation/sqlearn/explore/validate_explore.py`
- Modify: `validation/__main__.py` (`RUNNERS`), `validation/tests.json`

- [ ] **Step 1:** Write the runner on the pattern of
  `validation/sqlearn/agg/validate_aggregates.py`, over
  `_cases.numbers()` and `_cases.labels()`: canonical values exact
  (`Fraction` for the mean, quartiles and extremes; mpmath at
  `_cases.DIGITS` for `std`, skewness, kurtosis and both correlations; plain
  equality for every count, histogram bin, top value and pattern). Beside
  sqlearn: pandas (`describe`, `skew`, `kurt`, `nunique`, `value_counts`,
  `isna().value_counts()`, `corr`) and numpy (`histogram`, `std(ddof=1)`).
- [ ] **Step 2:** Run it alone through
  `validation.__main__.main([module], ROOT)`; set each bound from the first
  measurement as the aggregates runner's comment says, and write the
  measurement in the bound's comment.
- [ ] **Step 3:** `just test`; commit
      `test: validate sq.explore against exact values (#74)` with
      `validation/tests.json`.

### Task 10: Larger than memory

- [ ] **Step 1:** Write 12.5M rows × 200 doubles as Parquet with `COPY`
  (as `docs/benchmarks/gram-streaming.md` did for PCA);
  run `profile` and `correlations` at `sq.set_config(memory="2GB")`, one
  probe per subprocess, recording `ru_maxrss` twice and `uptime` before and
  after.
- [ ] **Step 2:** Add the results to `docs/benchmarks/explore-correlations.md`.
  Any out-of-memory error must carry a `Fix:` (the `exact=False` one for a
  distinct count); if it does not, fix that first, test-first.
- [ ] **Step 3:** Commit `docs: profile data larger than memory (#74)`.

### Task 11: Documentation and the handoff

**Files:**
- Create: `docs/guide/exploring-data.md` (MyST, executed code cells, as
  `docs/guide/evaluating-a-model.md`)
- Modify: `docs/guide/index.md` (toctree), `docs/reference/index.md`
  (`sqlearn.explore` and its five functions), `GLOSSARY.md` (*profile*,
  *note*, *missing pattern*), `docs/architecture/overview.md` (3.6: the
  module's first spec, what is left), `CLAUDE.md` (the state line),
  `HANDOFF.md`

- [ ] **Step 1:** The guide: profile a dataset built in the page (never
  `devdata/`, ADR 0053), read each note and the step that answers it (spec
  §7), then histograms, top values, missing patterns and correlations.
- [ ] **Step 2:**
      `rm -rf docs/reference/generated docs/_build && just build-docs`; every
      docstring example runs.
- [ ] **Step 3:** `just verify`; name every failure, fix, rerun.
- [ ] **Step 4:** Commit `docs: guide and reference for sq.explore (#74)`,
  with `HANDOFF.md` moving the area to "Just finished".

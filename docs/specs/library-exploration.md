---
type: spec
tags: [exploration, eda, profiling, missing-values, correlations, cardinality]
summary: "Spec for the first exploratory data analysis module (overview 3.6): sq.explore functions that run now on a dataset inside DuckDB (profile, histogram, top values, missing patterns, correlations) and return relations, checked against pandas and numpy."
related: [docs/architecture/overview.md, docs/questions/earlier-attempts/sqlearn-v04/exploration-helpers.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md]
---
# Exploratory data analysis: the module (`sq.explore`)

The first piece of part 3.6 of [the overview](../architecture/overview.md):
the library module. The application that renders it comes later and is not
in this spec.

Status: approved by Tomas on 2026-11-20. Written from the agent's own calls
(Tomas asked to go ahead without the questions); each is marked *(call)* so
it can be overturned.

## 1. Purpose

Before a pipeline is built, someone looks at the data: what each column holds,
how much is missing, which columns move together, which are identifiers or
constants. Today that means loading the data into pandas, which fails on data
larger than memory, the case sqlearn exists for.

`sq.explore` answers those questions inside DuckDB, over the same inputs a
pipeline reads (files, globs, tables, relations, pandas frames), on data of any
size. What it returns is a DuckDB relation, the form sqlearn already hands back
from `apply` and `classification_report`. A user shows it in a notebook, a
program reads it, and the exploration application later renders it from the
same relations.

Who it is for, in order: a user in a notebook deciding which steps their data
needs; the documentation and the learning site, which show data before
preparing it; the exploration application.

## 2. What it looks like

```python
sq.explore.profile("data/sales/*.parquet").show()
# column   type     rows  missing  missing_share  distinct  mean  std  min  q25  median  q75  max  ...  notes
# price    DOUBLE   1e7   1204     0.00012        88213     ...                                         []
# id       BIGINT   1e7   0        0.0            1e7       ...                                         [id-like]
# region   VARCHAR  1e7   0        0.0            1         ...                                         [constant]

sq.explore.histogram(data, bins=20)  # column, bin, low, high, count
sq.explore.top(data, k=10)  # column, value, count, share
sq.explore.missing(data)  # the missing share and the commonest patterns
sq.explore.correlations(data)  # column_a, column_b, correlation, rows (Pearson)
sq.explore.correlations(data, method="spearman")
sq.explore.profile(data, cols=sq.cols.numeric(), out="pandas")
```

## 3. Rules

- **Computation is SQL in DuckDB** (ADR 0002). No function pulls rows into
  Python; only results the size of the answer reach it (a profile's rows, a
  histogram's bins).
- **Exact by default** *(call)*: quantiles with `quantile_cont`, distinct
  counts with `count(DISTINCT ...)`. `exact=False` switches to
  `approx_quantile` and `approx_count_distinct` on large data, and says so in
  the result (an `exact` column). sqlearn never switches on its own (ADR
  0046): when an exact count runs out of memory, the error's `Fix:` names
  `exact=False`.
- **No sampling in this spec** *(call)*: every row counts, so a result never
  needs a "sampled" banner. Sampling is a later idea (§8).
- **The functions run now** *(call)*: `sq.explore.profile(data)` computes and
  returns, like a metric. They are not steps and take no part in a pipeline,
  the learning store or `sq.save`.
- **Each returns a relation** *(call)*, in long (tidy) form, one row per
  column (or pair, bin, value), with `out=` as `apply` takes it
  (`"pandas"`, `"polars"`, `"numpy"`, `"arrow"`). No result class, no
  plotting library, no new runtime dependency.
- **Columns** are chosen with `cols=` as steps choose them (a name, a list, a
  selector); by default every column *(call)*.
- **Statistics follow pandas** *(call)*, the tool users compare against:
  `std` with one degree of freedom, sample-adjusted skewness and excess
  kurtosis (DuckDB's `skewness` and `kurtosis`, pandas' `skew` and `kurt`),
  quartiles interpolated linearly. Missing values (NULL, and NaN in a float
  column) are left out of every statistic and counted in `missing`.
- **British English in prose, American in identifiers** (ADR 0010); every
  refusal has a `Why:` and a `Fix:`.

## 4. The functions

### 4.1 `profile(data, cols=None, *, exact=True, out=None)`

One row per chosen column, in the input's column order. Columns of the
result:

| Column | For | Meaning |
|---|---|---|
| `column`, `type` | all | The name and DuckDB type |
| `rows` | all | Rows read |
| `missing`, `missing_share` | all | NULL (and NaN) count and share of `rows` |
| `distinct`, `distinct_share` | all | Distinct non-missing values, and their share of the non-missing rows |
| `mean`, `std`, `min`, `q25`, `median`, `q75`, `max` | numeric | As pandas' `describe` |
| `zeros`, `negative`, `infinite` | numeric | Counts; `zeros` and `negative` count finite values only (ruled during the build) |
| `skewness`, `kurtosis` | numeric | Sample-adjusted, as pandas |
| `min_length`, `max_length` | text | Characters |
| `first`, `last` | dates and timestamps | Earliest and latest, as text |
| `exact` | all | Whether quantiles and distinct counts are exact |
| `notes` | all | A list of text flags (§4.1.1) |

A statistic that does not apply to a column's type is NULL. Booleans count as
numbers for `mean` (the share true) and as categories for `distinct`.
*Ruled during the build: a boolean gets only `mean`, the share true; its other
numeric statistics are NULL.*

The statistics are computed in as few queries as the level planner allows
*(call: one aggregate query over all columns when it fits, as the steps' learn
statements do)*. *Ruled during the build, which departs from this: the scan
reads the data in blocks of 20 columns, a statement each, because DuckDB holds
a Parquet row group of every column a statement reads on each thread (issue
#68), and no statement over all 200 columns fit a 1 to 2 GB limit on 12.5
million rows. The exact quantiles and distinct counts keep every value, so
they run in groups of columns sized to the memory budget, a statement each
that reads only its group's columns; with `exact=False` they join the scan.
The mean is compensated (`favg`); the standard deviation, skewness and
kurtosis come from a second pass of compensated sums (`fsum`) of the
deviations about that mean, not from DuckDB's one-pass aggregates, which lose
precision when the values are far from zero.*

#### 4.1.1 Notes

Flags a user acts on, each with a rule a reader can check *(call: these four,
fixing v0.4's `id_like`, which fired on every continuous float)*:

- `constant`: one distinct non-missing value.
- `all-missing`: every row missing.
- `id-like`: an integer or text column whose distinct count equals its
  non-missing rows, with at least 20 rows. Never a float column.
- `high-cardinality`: a text column with more than 50 distinct values and
  more than half its rows distinct, not `id-like`.

The thresholds are settings of the function (`id_rows=20`,
`high_cardinality=50`) *(call)*.

### 4.2 `histogram(data, cols=None, *, bins=10, out=None)`

Equal-width bins between each numeric column's minimum and maximum, as
`numpy.histogram(values, bins)`: one row per column and bin, with `bin`
(0-based), `low`, `high`, `count`; the last bin includes its upper edge. A
constant column has one bin. Missing and infinite values are left out (their
counts are in `profile`). A non-numeric column in `cols` is refused; by
default only numeric columns are taken *(call)*. *Ruled during the build: a
range that cannot be cut into finite, increasing edges (numpy's "Too many bins
for data range", as from -1e308 to 1e308) gives the column one bin from its
minimum to its maximum; the extremes and the counts are read 20 columns a
statement, as `profile`'s scan.*

### 4.3 `top(data, cols=None, *, k=10, out=None)`

The `k` commonest values of each column: `column`, `value` (as text),
`count`, `share` (of all rows), ordered by count, then value. Missing values
appear as one row with `value` NULL when they are among the commonest, as
pandas' `value_counts(dropna=False)` *(call)*. *Ruled during the build: in a
float column -0.0 is counted as 0.0, as pandas does.*

### 4.4 `missing(data, cols=None, *, patterns=10, out=None)`

The commonest patterns of missing values across the chosen columns: one row
per pattern with `missing` (the list of columns missing in it), `count` and
`share`, ordered by count, and the pattern with nothing missing among them.
Built with one `GROUP BY` over the columns' missing flags. Past 64 columns
the pattern is refused with a `Fix:` to pass fewer `cols` *(call: patterns
over many columns are rarely read, and the key grows with the width)*. The
per-column shares are in `profile`.

### 4.5 `correlations(data, cols=None, *, method="pearson", out=None)`

Every pair of the chosen numeric columns: `column_a`, `column_b` (each
unordered pair once, `a` before `b` in column order), `correlation`, and
`rows`, the rows where both are present. Each pair uses the rows where both
are present, as pandas' `DataFrame.corr` *(call: pairwise, so one sparse
column does not empty the rest)*.

- `"pearson"`: DuckDB's `corr`.
- `"spearman"`: Pearson on average ranks (ties share the mean of their
  ranks), as pandas. v0.4 ranked with `RANK()`, which gives ties the lowest
  rank: that is the bug to avoid. *Ruled during the build: Spearman numbers
  the source once into a temporary copy of the chosen columns, ranks each
  complete column once from that copy, and ranks a pair touching a column
  with missing values over its own complete rows, in a statement that reads
  only its two columns.*

A column with no variance gives NULL for its pairs, as pandas gives NaN.
p(p−1)/2 pairs at 200 columns is about 20,000 aggregates, which ADR 0058
measured at 26 s in one statement and out of memory at 500 columns: the pairs
are computed in chunks so memory stays bounded
*(left to the builder: the chunk size, measured)*. *Ruled during the build: the
chunks are 20-column blocks of the columns, each statement pairing two blocks
and so reading only their columns (a chunk of pairs in order read nearly every
column); see the [benchmark](../benchmarks/explore-correlations.md).* Kendall is
not in this spec (§8).

## 5. Decisions to record

- **ADR 0059: exploration functions run now and return relations.** Why not
  steps (nothing is learned for later), why not a result class (the relation
  is sqlearn's existing hand-back, and the application reads the same thing),
  why pandas' conventions.
- The group's name, `sq.explore`, in that ADR *(call)*.

## 6. Tests and validation

- **Tests** (`tests/src/sqlearn/explore/`), named in `GLOSSARY.md` terms:
  each function's columns and order; each note's rule at its boundary; the
  pandas conventions on small hand-checked data; missing, NaN and infinite
  values; a column named as SQL keywords or differing only by case; every
  input form `read` takes; every `out=`; each refusal's `Why:` and `Fix:`.
- **Validation** (`validation/sqlearn/explore/`), as the other areas do (ADR
  0016), against pandas 2 and numpy on the validation's generated data: every
  statistic of `profile` against `describe`, `skew`, `kurt`, `nunique`,
  `isna`; `histogram` against `numpy.histogram`; `top` against
  `value_counts`; `missing` against a pandas group-by of `isna()`;
  `correlations` against `DataFrame.corr` for both methods, with missing
  values present. Bounds as ADR 0043 sets them for sums of doubles.
- **Larger than memory**, once: `profile` and `correlations` on data larger
  than the DuckDB memory limit, recorded with load average, as the PCA
  benchmark was.

## 7. Documentation

- A guide page, `docs/guide/exploring-data.md`: profiling a dataset before
  building a pipeline, reading each note, and which step answers it (a
  constant column → drop or `sq.select.variance`; missing values →
  `sq.impute`; high cardinality → `sq.encode.target`).
- Reference pages generated from the docstrings, each with an example.
- The overview's 3.6 updated: the module's first spec, and what is left.
- `GLOSSARY.md`: *profile*, *note*, *missing pattern*.

## 8. Not in this spec

Later pieces, each its own spec or issue: association with a target (eta,
Cramér's V, a leakage flag); outliers (z-score, IQR, MAD as counts and a SQL
predicate); normality screens; Kendall's tau; sampling for speed;
time-series views; the exploration application and its front end
([application-front-end.md](../questions/application-front-end.md),
[applications-home.md](../questions/applications-home.md)).

## 9. Left to the builder

- How the queries are batched (one per function or fewer), measured.
- The chunk size for `correlations`, measured at 50, 200 and 500 columns.
- How Spearman's average ranks are written so a pair with missing values
  ranks only its complete rows, as pandas does.
- Where the code lives: `src/sqlearn/explore/`, by the layout's rules.

## 10. Done when

- The five functions exist with tests, docstring examples and reference
  pages, and the guide page builds.
- Validation passes against pandas and numpy for every statistic.
- `profile` and `correlations` have run once on data larger than memory.
- `just verify` passes, and the overview and `HANDOFF.md` say what is next
  in 3.6.

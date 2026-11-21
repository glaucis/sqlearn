# Where sqlearn's heavy paths spend their time

sqlearn is to be ported to a C++ library
([issue #78](https://github.com/glaucis/sqlearn/issues/78)). This page
measures where today's Python and DuckDB sqlearn spends its time on six
heavy paths, so the port can be put in order. It measures and decides
nothing. It is an estimate: the machine was heavily loaded.

## What was measured

- **Data:** DuckDB generated it from a fixed seed and wrote it as Parquet
  with `COPY`: 1,000,000 rows of 50, 200 or 500 DOUBLE columns, no NULLs.
  The file is removed after the run.
- **Cases:** not every path at every width.
  - `pca`: `Pipeline([sq.decompose.pca()]).learn(path)`, at 50, 200, 500
    columns (a Gram learn, ADR 0058).
  - `spearman`: `sq.explore.correlations(path, method="spearman")`, at 50
    and 200. These numbers are taken before #75 changes its first scan, so
    they describe today's scan, not the planned one.
  - `scale` (`sq.scale.standard()`), `median` (`sq.impute.median()`),
    `variance` (`sq.select.variance()`), each learned in a pipeline, and
    `profile` (`sq.explore.profile(path)`), at 200 and 500.
- **Runs:** each case runs in a subprocess of its own, three times: twice
  for timing, once profiled. The profiled run sets DuckDB's JSON profiling,
  so every statement the call sends is caught with its time, its peak buffer
  memory and its operators. It also wraps the call in `cProfile`.
- **Columns of the tables:**
  - `s`: wall-clock seconds of the two timing runs.
  - `peak GB`: the process's peak resident memory in each timing run.
  - `DuckDB s`: the sum of the statements' times in the profiled run.
  - `Python s`: the profiled run's wall time less `DuckDB s`.
  - `statements`: how many statements the call sent.
  - `longest s`: the longest single statement.
  - `largest operators`: the three operators with the most time in the
    longest single statement, each summed over that statement's threads. For
    the one-statement paths it is the whole call; for the others the prose
    below gives sums over every statement, labelled as such.

`DuckDB s` and `Python s` come from the profiled run, which is slower than a
timing run (profiling and `cProfile` cost time, and the load changed between
runs), so `DuckDB s` can exceed the timing runs' `s`. Operator times are
summed across threads, so they exceed wall time too. Compare them with each
other, not with the clock.

Reproduce with `uv run python -m validation.benchmarks.engine_profile --json
PATH`; it took about 25 minutes here.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0, at its defaults: 8 threads, `memory_limit` 12.7 GiB |
| sqlearn | commit `e4fb71a` |
| Load | `uptime` before: load averages 10.51 13.17 14.18; after: 16.13 17.40 17.38 |

The machine has 8 cores and the load was 10 to 17 throughout, so every time
below is an estimate, and a rerun on a quiet machine may differ a good deal.
Every number on this page is measured, under that load.

## Results

All measured, 1,000,000 rows. Where two numbers are given, they are the two
timing runs. No probe failed.

### The Gram learn (`pca`)

| columns | s | peak GB | DuckDB s | Python s | statements | longest s | largest operators |
|---|---|---|---|---|---|---|---|
| 50 | 1.50 / 1.44 | 1.69 / 1.70 | 0.93 | 0.56 | 8 | 0.59 | BATCH_CREATE_TABLE_AS 0.33, TABLE_SCAN 0.23, PROJECTION 0.01 |
| 200 | 11.70 / 9.15 | 3.56 / 3.45 | 5.71 | 2.14 | 20 | 3.07 | BATCH_CREATE_TABLE_AS 1.64, TABLE_SCAN 1.30, PROJECTION 0.06 |
| 500 | 31.72 / 31.97 | 5.80 / 5.28 | 16.36 | 7.74 | 44 | 6.62 | TABLE_SCAN 26.88, UNGROUPED_AGGREGATE 7.66, PROJECTION 3.00 |

In the profiled run, the largest Python function by `cProfile`'s own time
(`tottime`) was `gram_matrix` (0.77 s at 50 columns, 5.01 s at 200, 10.69 s
at 500). That time includes work inside the DuckDB calls it makes, so it can
exceed `Python s`. Summed over every statement and thread, the largest
operators were TABLE_SCAN (0.63 s, 3.78 s, 29.63 s), UNGROUPED_AGGREGATE
(0.45 s, 2.56 s, 7.66 s) and BATCH_CREATE_TABLE_AS (0.33 s, 1.64 s, 3.62 s).

### Spearman (`sq.explore.correlations`), before #75

| columns | s | peak GB | DuckDB s | Python s | statements | longest s | largest operators |
|---|---|---|---|---|---|---|---|
| 50 | 10.41 / 11.32 | 2.32 / 2.34 | 12.86 | 0.35 | 63 | 2.29 | UNGROUPED_AGGREGATE 15.47, HASH_JOIN 0.10, TABLE_SCAN 0.03 |
| 200 | 143.89 / 108.75 | 4.93 / 4.87 | 113.09 | 3.58 | 269 | 3.60 | UNGROUPED_AGGREGATE 24.33, HASH_JOIN 0.36, TABLE_SCAN 0.12 |

Summed over all statements, the largest operators were UNGROUPED_AGGREGATE
(40.45 s at 50 columns, 645.66 s at 200), then WINDOW (8.12 s, 23.22 s). In
the profiled run `_rank_block` took 5.99 s of `cProfile`'s own time at 50
columns and 13.04 s at 200; that includes time inside the DuckDB calls it
makes, so it can exceed `Python s` (0.35 s, 3.58 s).

### The widest steps (`scale`, `median`, `variance`, `profile`)

| path | columns | s | peak GB | DuckDB s | Python s | statements | longest s | largest operators |
|---|---|---|---|---|---|---|---|---|
| scale | 200 | 4.22 / 3.23 | 3.20 / 4.85 | 2.94 | 0.97 | 1 | 2.94 | UNGROUPED_AGGREGATE 7.39, PROJECTION 5.80, CTE_SCAN 2.40 |
| median | 200 | 22.30 / 19.97 | 5.09 / 7.44 | 37.15 | 0.56 | 1 | 37.15 | WINDOW 156.55, CTE_SCAN 56.47, HASH_JOIN 16.74 |
| variance | 200 | 6.30 / 6.73 | 5.06 / 4.89 | 5.30 | 1.09 | 1 | 5.30 | UNGROUPED_AGGREGATE 14.58, PROJECTION 10.26, CTE 8.88 |
| profile | 200 | 12.15 / 11.11 | 2.37 / 2.35 | 15.68 | 1.28 | 23 | 2.12 | UNGROUPED_AGGREGATE 3.90, HASH_GROUP_BY 3.20, CTE 2.21 |
| scale | 500 | 14.15 / 13.43 | 6.00 / 6.09 | 11.44 | 2.68 | 1 | 11.44 | TABLE_SCAN 28.79, UNGROUPED_AGGREGATE 19.92, PROJECTION 17.01 |
| median | 500 | 190.71 / 184.23 | 8.66 / 8.20 | 216.29 | 1.31 | 1 | 216.29 | WINDOW 1108.31, CTE_SCAN 286.26, TABLE_SCAN 49.69 |
| variance | 500 | 25.79 / 15.05 | 5.49 / 6.16 | 11.96 | 1.38 | 1 | 11.96 | TABLE_SCAN 33.15, UNGROUPED_AGGREGATE 19.01, PROJECTION 16.59 |
| profile | 500 | 31.96 / 51.16 | 2.68 / 2.63 | 33.70 | 3.26 | 53 | 1.44 | HASH_GROUP_BY 3.04, UNGROUPED_AGGREGATE 2.47, CTE 2.19 |

Two more measured facts from the profiled runs. The `median` statement at 500
columns wrote a peak of 15.74 GB to DuckDB's temporary directory; no other
case wrote any. The peak buffer memory DuckDB reported for one statement was
13.53 GB for `median` at 200 columns and 15.12 GB at 500, against process
peaks of 5.09 to 8.66 GB in the timing runs.

## What it shows

Shares are `Python s` over the profiled run's wall time, and are estimates
under the load above.

- **Gram learn (`pca`).** Python's share was 37% at 50 columns, 27% at 200 and
  32% at 500. `gram_matrix` was the largest Python function at every width.
  Summed over every statement, TABLE_SCAN was the largest operator at every
  width (0.63 s, 3.78 s, 29.63 s), ahead of UNGROUPED_AGGREGATE, and it grew
  faster than the rest from 200 to 500 columns. Time grew from about 1.5 s to
  about 10 s to about 32 s as the columns went 50, 200, 500, and peak memory
  from 1.7 to 3.5 to 5.5 GB. The statements grew from 8 to 20 to 44.
- **Spearman.** Python's share was 3% at both widths: the time is in DuckDB.
  UNGROUPED_AGGREGATE dominated, with WINDOW next. The statements grew from
  63 to 269 and the time from about 11 s to about 126 s, 4 times the columns
  taking about 11 times as long. Peak memory was 2.3 and 4.9 GB. This is
  today's first scan, before #75.
- **`scale` and `variance`.** One statement each. Python's share was 25%
  and 19% (`scale`) and 17% and 10% (`variance`) at 200 and 500 columns.
  The operators were UNGROUPED_AGGREGATE and PROJECTION, with TABLE_SCAN
  the largest at 500. From 200 to 500 columns, `scale` took about 3.7 s to
  about 13.8 s; `variance` about 6.5 s to a spread of 15 to 26 s, too noisy
  at this load to give a ratio. Peak memory stayed between 3 and 6 GB.
- **`median`.** One statement, and the slowest path: about 21 s at 200
  columns and about 187 s at 500 (2.5 times the columns, about 9 times the
  time). Python's share was 1%. WINDOW dominated (156.55 s then 1108.31 s
  summed), with CTE_SCAN next. At 500 columns it spilled 15.74 GB to the
  temporary directory.
- **`profile`.** 23 statements at 200 columns and 53 at 500. Python's share
  was 8% and 9%. Summed over every statement, HASH_GROUP_BY (29.37 s)
  was ahead of UNGROUPED_AGGREGATE (27.01 s) and CTE (22.97 s) at 200 columns;
  at 500, UNGROUPED_AGGREGATE (57.94 s) was ahead of HASH_GROUP_BY (53.43 s)
  and CTE (38.72 s). No operator stood out. Time went from about
  11.6 s to between 32 s and 51 s (two runs far apart). Peak memory stayed
  at about 2.4 to 2.7 GB, the lowest of the wide paths, and did not grow
  with the columns.
- **Python against DuckDB overall.** Python's share was 1% to 17% for every path
  except the three `pca` widths (27% to 37%) and `scale` (19% and 25%). The
  Python time of the single-statement paths was almost all inside the call that
  submits the statement to DuckDB. The largest Python function by `cProfile`'s
  own time was `gram_matrix` for `pca` and `_rank_block` for Spearman; that time
  includes the DuckDB calls they make.
- **Failed probes:** none. All 13 cases ran to the end.

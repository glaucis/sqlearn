---
type: note
tags: [benchmarks, median, larger-than-memory, sort, sqlearn]
summary: "Measures the most rows the exact median (computed by sorting) learns under 32, 64 and 128 MB memory limits on one thread, with the time at each."
related: [index, standard-deviation, onehot-second-run]
---
# How far the exact median reaches

[Issue #27](https://github.com/glaucis/sqlearn/issues/27) asks how far beyond
DuckDB's memory limit the exact median learns. `sq.agg.median` is computed by
sorting ([ADR 0032](../adr/0032-the-median-is-exact-by-sorting.md)), and the
sort spills to disk, but it has a reach. This page states that reach. It
recommends nothing: whether to offer an approximate median is Tomas's call.

## What was measured

- **Step:** `sq.Pipeline([sq.impute.median("x")]).learn(path)`, which learns
  one column's exact median.
- **Data:** one DOUBLE column `x`, a tenth NULL, the rest spread evenly over
  900 to 1,100. DuckDB wrote it to a Parquet file from a `range()` query with a
  fixed seed (`SEED = 0`); the file is read from disk, not held in Python. The
  rows of a smaller count are the first rows of a larger one.
- **Limits:** `SET memory_limit` of 32, 64 and 128 MB, `SET threads = 1`, and
  `temp_directory` on disk.
- **Method:** each probe is one fresh subprocess, so an out-of-memory error
  cannot take the run down. For each limit the row count starts at 5,000,000
  and doubles until a probe fails, then is bisected until the failing count is
  within 10% of the passing one. The two boundary points are then run three
  times each.
- **Cap:** 640,000,000 rows (about 4 GB of Parquet). No limit reached it.
- **Failure:** the run recorded a failing probe only as a non-zero exit. One
  failing probe (32 MB, 8,750,000 rows) was run again by hand and raised
  DuckDB's `OutOfMemoryException` ("failed to pin block ... used"); the others
  were not inspected one by one.
- **Columns:** one median column was measured. The reach with several median
  columns in one step (which share one sort) is not measured.

Reproduce with `uv run python -m validation.benchmarks.median_reach`.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| sqlearn | 0.1.dev240+gb67f44666 |

## Results

| memory limit | largest passing rows | smallest failing rows | passing runs, s | failing probe, 3 runs |
|---|---|---|---|---|
| 32 MB | 8,125,000 | 8,750,000 | 2.0, 2.0, 2.0 | all failed |
| 64 MB | 32,500,000 | 35,000,000 | 7.7, 7.9, 7.6 | all failed |
| 128 MB | 110,000,000 | 120,000,000 | 39.1, 34.8, 29.8 | all failed |

Rows per MB of limit at the largest passing count: 0.25 million at 32 MB, 0.51
million at 64 MB, 0.86 million at 128 MB. The reach grows faster than the
limit: doubling the limit multiplied the passing rows by 4.0, then 3.4.

For scale, a row is one 8-byte DOUBLE (a tenth NULL), so 110,000,000 rows are
about 0.9 GB of values, about seven times a 128 MB limit; 32,500,000 rows are
about 4 times a 64 MB limit.

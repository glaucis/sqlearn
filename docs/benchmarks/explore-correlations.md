---
type: note
tags: [benchmarks, performance, exploration, correlations, memory, sqlearn]
summary: Times sq.explore.correlations on 1,000,000 rows of 200 and 500 columns in Parquet files with default row groups, at blocks of 20, 40 and 80 columns, and says why 20 was chosen.
related: [index, gram-batches, gram-streaming]
---
# How many columns one statement reads

`sq.explore.correlations` computes each pair as `corr(a, b)` plus
`regr_count(a, b)`. It cuts the columns into blocks of `_BLOCK_COLUMNS` and runs
one statement for each pair of blocks, which pairs the two blocks and so reads
only their columns ([issue #74](https://github.com/glaucis/sqlearn/issues/74),
spec §4.5). ADR 0058 measured all the pairs of XᵀX in one statement at 26 s for
200 columns and out of memory at 500. This page measures the block size. It is
an estimate: the machine was loaded.

## What was measured

- **Data:** random DOUBLE columns, 1,000,000 rows, no NULLs, written as
  Parquet with `COPY` and DuckDB's **default row groups** (122,880 rows):
  `w200.parquet` (1.6 GB) and `w500.parquet` (4.0 GB).
- **Probe:** `sq.explore.correlations(path)` in a fresh process, the result
  counted; one run per cell, not a median. Blocks of 20, 40 and 80 columns. A
  run was to be stopped at 900 s; none was.
- **Memory:** `ru_maxrss` of the probe, read twice a second apart (the two
  reads were equal every time). The default budget gives DuckDB 6.4 GB on
  this machine (half of 80% of 16 GiB).

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| Load | `uptime` before: 2.49 4.79 9.60; after: 19.74 16.17 15.56 |

## Results

Seconds (peak memory in GB), on the default-row-group files above.

| columns (pairs) | block 20 | block 40 | block 80 |
|---|---|---|---|
| 200 (19,900) in `w200.parquet` | 48.3 (1.50) | 46.5 (3.33) | 47.8 (5.98) |
| 500 (124,750) in `w500.parquet` | 367.9 (1.64) | 338.6 (3.41) | 341.7 (5.98) |

## The choice

`_BLOCK_COLUMNS = 20`. The time barely moves with the block (block 20 is 4 %
slower than the fastest at 200 columns and 9 % at 500, inside what the load
changed between runs), but the peak memory follows the block: each thread
holds a row group of the columns its statement reads, so 80 columns reach the
6.4 GB limit and 40 hold 3.4 GB, more than a machine with 8 GB of memory
gives DuckDB. 20 holds 1.6 GB on a file with default row groups, and the
500-column file that could not be scanned at all with the first design now
runs. A statement of two blocks of 20 holds at most 400 aggregates.

## What was tried first

The first version cut the pairs in order into statements of 250, 1,000 and
4,000 pairs. Every statement then read nearly every column (column 0 pairs
with the 499 after it), so a chunk bounded the aggregates, not the scan.
Measured on 1,000,000 rows, 500 columns:

- In `w500.parquet` (default row groups): out of memory within 3 seconds at
  1,000 and 4,000 pairs, and at 250 pairs the run was stopped at 600 s. A bare
  `SELECT` of 249 `corr`s also ran out of memory. Each of 8
  threads held a row group of all 500 columns, about 490 MB.
- In a copy written with `ROW_GROUP_SIZE 10000`: 612 s, 361 s and 332 s at
  250, 1,000 and 4,000 pairs, with peaks of 3.98, 3.96 and 5.19 GB. In the
  default-row-group file of 200 columns, 65.2 s, 50.9 s and 49.8 s with peaks
  of 3.86, 4.38 and 5.45 GB. The load average was about 13 to 89 and the
  machine never quiet.
- Counting a pair's rows with `count(*) FILTER (WHERE a IS NOT NULL AND b IS
  NOT NULL)` instead of `regr_count(a, b)` took 9.6 s against 0.6 s for 250
  pairs at 50 columns (a default file).

---
type: note
tags: [benchmarks, performance, exploration, correlations, memory, sqlearn]
summary: Times sq.explore.correlations on 1,000,000 rows of 200 and 500 columns in Parquet files with default row groups, at blocks of 20, 40 and 80 columns, says why 20 was chosen, then measures Spearman on ranks written once, with and without missing values and under a small memory budget.
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

## Spearman

`method="spearman"` correlates average ranks: `(rank() OVER w + count(*)
OVER w) / 2`, with `w` ordered by the column. It reads the data once, into
a temporary table of the chosen columns, cleaned and numbered by row
(`row_number() OVER ()`, as the Gram step's learn numbers its rows). Each
column with no missing value is ranked once from that table, the row number
and its values only, into a table of its own. A block's ranks are then
joined on the row number into one table, and each tile joins two blocks'
tables and runs the same `corr` and `regr_count` as Pearson, at the same
block of 20. A pair touching a column with missing values is ranked over
its own complete rows from the numbered table, in a statement that reads
only its two columns.

- **Data:** `w200.parquet` above, and `w200m.parquet`, a copy written with
  `COPY` in which every fourth column (50 of 200) has 5 % of its values
  NULL at random.
- **Probe:** `sq.explore.correlations(path, method="spearman")` in a fresh
  process, the result counted, one run each. Runs were to be stopped at
  1,200 s. `ru_maxrss` was read twice a second apart, and the two reads were
  equal every time.

### Results

| run | seconds | peak memory (GB) | `uptime` before; after |
|---|---|---|---|
| `w200.parquet`, no missing values | 88.1 | 4.99 | 4.50 4.85 6.92; 11.04 6.87 7.48 |
| `w200m.parquet`, 50 sparse columns | 763.2 | 4.17 | 11.04 6.87 7.48; 17.66 12.86 10.33 |
| `w200.parquet`, `sq.set_config(memory="1GB")` | refused after 1.8 | 0.63 | 17.66 12.86 10.33; 16.73 12.74 10.30 |
| `w200.parquet`, `memory_limit` 1 GB on 2 threads | 206.1 | 1.75 | 12.86 12.13 10.14; 10.11 10.46 9.77 |

- **Without missing values** the time is about 1.8 times Pearson's 48.3
  s: 200 sorts of two columns, then the tiles' joins.
- **With 50 sparse columns** the 8,725 pairs that touch one dominate: two
  sorts of the pair's rows each, about 0.08 s a pair under this load. The
  cost follows the number of sparse columns times the number of columns;
  `cols=` narrows it.
- **Under a small budget**, `memory="1GB"` gives sqlearn's connection a
  `memory_limit` of 500 MB. The first scan, which reads every chosen column, ran
  out of memory at once: each of 8 threads holds a 197 MB row group. DuckDB
  refused, and sqlearn's message names the row groups, fewer columns, more
  memory and fewer threads; the process was not killed. On a connection given
  `SET memory_limit = '1GB'` and `SET threads = 2`, the same call completed in
  206.1 s at a 1.75 GB peak. The numbered copy and the ranks, about 3.2 GB
  together (estimated from 8 bytes a value, not measured on disk), cannot
  all have been in memory, so DuckDB wrote them to its temporary directory.
- The peaks are resident memory, the numbered copy and the blocks' ranks
  included. These are temporary tables in DuckDB's buffer pool, written to
  its temporary directory when they pass `memory_limit`: for an in-memory
  connection such as sqlearn's own, `.tmp` in the current directory by
  default (DuckDB's `temp_directory` setting).

### What was tried first

The first version ranked inside each tile statement: one window for each
column the tile read. DuckDB runs each window as its own operator and
carries every column the statement reads through each of them, so a tile's
time and memory grew faster than its width. Statements reading 4, 10 and 20
columns took 0.37 s, 1.09 s and 3.52 s and peaked at 0.49, 2.15 and 7.04 GB,
and a 40-column tile took 33 to 50 s alone. Each column was also ranked
again in every tile that read it, about 8,000 sorts at 200 columns where
200 do. On `w200.parquet` it took 484.1 s at 7.79 GB with blocks of 10 and
540.5 s at 2.66 GB with blocks of 5, and the run with 50 sparse columns was
stopped at 900 s.

To line the ranks up, `POSITIONAL JOIN` was measured against joins on the
row number for 40 columns. Its tile took 4.08 s at 1.51 GB, against 2.15 s
at 2.48 GB for the join. The join was taken: it is faster, and it does not
depend on the tables keeping their insertion order, which a connection can
turn off with `preserve_insertion_order`.

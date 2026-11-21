---
type: note
tags: [benchmarks, performance, exploration, correlations, memory, sqlearn]
summary: Times sq.explore.correlations on 1,000,000 rows of 50, 200 and 500 columns at chunk sizes of 250, 1,000 and 4,000 pairs per statement, and says why 1,000 was chosen.
related: [index, gram-batches, gram-streaming]
---
# How many pairs one statement computes

`sq.explore.correlations` computes each pair as `corr(a, b)` plus
`regr_count(a, b)` and runs the pairs in statements of `_PAIRS_PER_QUERY`
pairs each, every statement scanning the data once
([issue #74](https://github.com/glaucis/sqlearn/issues/74), spec §4.5).
ADR 0058 measured all the pairs of XᵀX in one statement at 26 s for 200
columns and out of memory at 500. This page measures the chunk size. It is an
estimate: the machine was loaded.

## What was measured

- **Data:** random DOUBLE columns, 1,000,000 rows, written as Parquet with
  `COPY`, no NULLs.
- **Probe:** `sq.explore.correlations(path)` in a fresh process, the result
  counted; one run per cell, not a median. Chunk sizes 250, 1,000 and 4,000
  pairs. A run was stopped at 600 s.
- **Memory:** `ru_maxrss` of the probe, read twice a second apart (the two
  reads were equal every time). The default budget gives DuckDB 6.4 GB on
  this machine (half of 80% of 16 GiB).
- **A finding about the files:** the 500-column file written with DuckDB's
  default row groups (122,880 rows, so 490 MB a group per thread) could not be
  scanned at all within 6.4 GB: a bare `SELECT` of 249 `corr`s ran out of
  memory in two seconds, whatever the chunk. The 500-column rows below are
  from a file written with `ROW_GROUP_SIZE 10000`; that scan took 0.9 s for
  249 pairs and 2.3 GB. Wide Parquet files with large row groups need that
  fixing in the file, not in sqlearn.
- **Why `regr_count`:** the first version counted the pair's rows with
  `count(*) FILTER (WHERE a IS NOT NULL AND b IS NOT NULL)`; at 50 columns and
  250 pairs that took 9.6 s against 0.6 s with `regr_count(a, b)`, which counts
  the rows where both are present.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| Load | `uptime` before the 50 and 200 column runs: 89.45 39.06 18.76; before the 500-column runs: 13.09 20.40 18.30; after them: 22.78 17.50 16.76. The machine was never quiet. |

## Results

Seconds (peak memory in GB), 1,000,000 rows.

| columns (pairs) | 250 | 1,000 | 4,000 |
|---|---|---|---|
| 50 (1,225) | 3.2 (1.25) | 2.9 (1.56) | 3.0 (1.71) |
| 200 (19,900) | 65.2 (3.86) | 50.9 (4.38) | 49.8 (5.45) |
| 500 (124,750) | 611.7 (3.98) | 361.2 (3.96) | 331.8 (5.19) |

The 500-column chunk of 250 ran just over the 600 s cut-off in the first
attempt (it was stopped), and finished in 612 s in the rerun with a 900 s
limit.

## The choice

`_PAIRS_PER_QUERY = 1000`. Below it, more statements mean more scans of the
data: 250 is 25 % slower at 200 columns and 70 % slower at 500. Above it,
4,000 gains 2 % and 8 % but holds 1 GB more, and at 200 columns its peak
(5.45 GB) is within a GB of DuckDB's 6.4 GB limit. 1,000 stays well inside
the default budget at every width measured and is within 10 % of the fastest.
Cost grows with the pairs (about 17 times from 50 to 200 columns for 16
times the pairs, 7 times from 200 to 500 for 6.3 times), so 500 columns takes
about six minutes on a loaded machine.

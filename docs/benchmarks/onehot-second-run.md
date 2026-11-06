---
type: note
tags: [benchmarks, performance, onehot, sqlearn]
summary: "Measures the time and the reads of OneHot's second run in the slice's preparation, with and without OneHot."
related: [index]
---
# OneHot's second run

[Issue #22](https://github.com/glaucis/sqlearn/issues/22) asks whether OneHot
should write one list column inside a run, so that learning it needs no second
run. This page states what the second run costs today. It recommends nothing:
the decision is Tomas's.

## What was measured

The core's slice preparation, `[sq.impute.median(), sq.encode.onehot("city"),
sq.scale.standard()]`, learns in two runs, because OneHot's columns cannot be
named before its categories are learned. The same preparation without OneHot,
`[sq.impute.median(), sq.scale.standard()]`, learns in one. Each was learned
from scratch (the step store cleared before every repetition) and then applied
to the same file, written out as Parquet.

- **Data:** generated from a fixed seed (`SEED = 0`) into a temporary
  directory: `age` and `income` (a tenth missing), `city` (3 values) and
  `plan` (3 values), at 1,000, 100,000 and 10,000,000 rows. The largest is
  29.7 MB as Parquet and about 400 MB in DuckDB's memory.
- **Times:** wall clock, the median of five repetitions, learn and apply timed
  separately. Each pipeline first runs once, discarded, to warm the file cache
  and the connection; the repetitions then alternate which pipeline goes first,
  so neither always takes the first read of the file.
- **Reads:** `io.total_bytes_read` from DuckDB's JSON profiling of every
  statement the pipeline ran, learn statements and apply statement separately.
  Under a memory limit this includes what DuckDB reads back from its spill
  files, so it is larger than the file.
- **Memory limit:** `SET memory_limit` on the largest size, with DuckDB's
  default threads (8) and with `SET threads = 1`, the setting the core's
  larger-than-memory test uses. A limit that fails is recorded as failed; the
  script prints a limit at which both pipelines run out of memory as one row,
  and the page shows it the same way.
- **Runs:** `len(pipe.runs_)` after `learn`; the script asserts that apply was
  one run.

The machine details come from `sysctl` and are macOS-only; on other systems
the script prints "unknown" for them.

Reproduce with `uv run python -m validation.benchmarks.onehot_runs`.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| sqlearn | 0.1.dev148+g2fb5c46d8 |

## Results

No memory limit:

| rows | pipeline | learn runs | learn s | apply s | total s | learn MB read | apply MB read |
|---|---|---|---|---|---|---|---|
| 1,000 | with OneHot | 2 | 0.031 | 0.005 | 0.036 | 0.02 | 0.01 |
| 1,000 | without OneHot | 1 | 0.020 | 0.003 | 0.023 | 0.01 | 0.01 |
| 100,000 | with OneHot | 2 | 0.054 | 0.012 | 0.066 | 0.57 | 0.31 |
| 100,000 | without OneHot | 1 | 0.027 | 0.008 | 0.035 | 0.26 | 0.31 |
| 10,000,000 | with OneHot | 2 | 0.754 | 0.148 | 0.906 | 52.99 | 29.04 |
| 10,000,000 | without OneHot | 1 | 0.572 | 0.114 | 0.687 | 23.94 | 29.04 |

10,000,000 rows under a memory limit (the data is about 400 MB in memory, so 512
MB is above it, the rest below):

| memory limit | threads | pipeline | learn runs | learn s | apply s | total s | learn MB read | apply MB read |
|---|---|---|---|---|---|---|---|---|
| 512 MB | 8 | with OneHot | 2 | 1.070 | 0.187 | 1.280 | 345.83 | 29.04 |
| 512 MB | 8 | without OneHot | 1 | 0.831 | 0.131 | 0.966 | 292.64 | 29.04 |
| 256 MB | 8 | with OneHot | 2 | 1.306 | 0.297 | 1.611 | 445.94 | 29.04 |
| 256 MB | 8 | without OneHot | 1 | 1.063 | 0.182 | 1.245 | 428.86 | 29.04 |
| 128 MB | 8 | both | | out of memory | | | | |
| 96 MB | 8 | both | | out of memory | | | | |
| 64 MB | 8 | both | | out of memory | | | | |
| 512 MB | 1 | with OneHot | 2 | 4.705 | 0.666 | 5.371 | 372.47 | 29.04 |
| 512 MB | 1 | without OneHot | 1 | 3.499 | 0.480 | 3.979 | 338.85 | 29.04 |
| 256 MB | 1 | with OneHot | 2 | 5.513 | 0.664 | 6.182 | 420.97 | 29.04 |
| 256 MB | 1 | without OneHot | 1 | 3.883 | 0.480 | 4.362 | 386.03 | 29.04 |
| 128 MB | 1 | with OneHot | 2 | 5.742 | 0.685 | 6.419 | 403.21 | 29.04 |
| 128 MB | 1 | without OneHot | 1 | 4.459 | 0.487 | 4.946 | 385.47 | 29.04 |
| 96 MB | 1 | with OneHot | 2 | 5.778 | 0.671 | 6.449 | 412.48 | 29.04 |
| 96 MB | 1 | without OneHot | 1 | 4.543 | 0.488 | 5.031 | 389.31 | 29.04 |
| 64 MB | 1 | with OneHot | 2 | 5.908 | 0.673 | 6.583 | 418.42 | 29.04 |
| 64 MB | 1 | without OneHot | 1 | 4.593 | 0.489 | 5.082 | 390.62 | 29.04 |

The MB-read columns of the two tables are not comparable: without a limit they
count file reads only; under a limit they also count what DuckDB reads back from
its spill files (295 to 472 MB against a 29.7 MB file).

With eight threads the lowest limit that passes, of those tried, is 256 MB; at
128 MB and below both pipelines run out of memory. With one thread the lowest
limit tried, 64 MB, passes for both.

At 10,000,000 rows and no limit, the second run adds 0.182 s to learning
(0.754 s against 0.572 s) and 29.05 MB to the bytes read while learning (52.99
MB against 23.94 MB). Applying is the same one run in both.

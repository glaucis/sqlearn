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
  separately.
- **Reads:** `io.total_bytes_read` from DuckDB's JSON profiling of every
  statement the pipeline ran, learn statements and apply statement separately.
  Under a memory limit this includes what DuckDB reads back from its spill
  files, so it is larger than the file.
- **Memory limit:** `SET memory_limit` on the largest size, with DuckDB's
  default threads (8) and with `SET threads = 1`, the setting the core's
  larger-than-memory test uses. A limit that fails is recorded as failed.
- **Runs:** `len(pipe.runs_)` after `learn`; apply was one run in every case.

Reproduce with `uv run python -m validation.benchmarks.onehot_runs`.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| sqlearn | 0.1.dev147+gb63381617 |

## Results

No memory limit:

| rows | pipeline | learn runs | learn s | apply s | total s | learn MB read | apply MB read |
|---|---|---|---|---|---|---|---|
| 1,000 | with OneHot | 2 | 0.032 | 0.005 | 0.037 | 0.02 | 0.01 |
| 1,000 | without OneHot | 1 | 0.020 | 0.003 | 0.023 | 0.01 | 0.01 |
| 100,000 | with OneHot | 2 | 0.055 | 0.012 | 0.067 | 0.57 | 0.31 |
| 100,000 | without OneHot | 1 | 0.028 | 0.008 | 0.036 | 0.26 | 0.31 |
| 10,000,000 | with OneHot | 2 | 0.774 | 0.156 | 0.939 | 52.99 | 29.04 |
| 10,000,000 | without OneHot | 1 | 0.597 | 0.121 | 0.717 | 23.94 | 29.04 |

10,000,000 rows under a memory limit (the data is about 400 MB in memory):

| memory limit | threads | pipeline | learn runs | learn s | apply s | total s | learn MB read | apply MB read |
|---|---|---|---|---|---|---|---|---|
| 512 MB | 8 | with OneHot | 2 | 1.108 | 0.201 | 1.310 | 410.85 | 29.04 |
| 512 MB | 8 | without OneHot | 1 | 0.863 | 0.145 | 1.012 | 295.23 | 29.04 |
| 256 MB | 8 | with OneHot | 2 | 1.330 | 0.305 | 1.628 | 471.76 | 29.04 |
| 256 MB | 8 | without OneHot | 1 | 1.088 | 0.188 | 1.275 | 422.90 | 29.04 |
| 128 MB | 8 | both | | out of memory | | | | |
| 96 MB | 8 | both | | out of memory | | | | |
| 64 MB | 8 | both | | out of memory | | | | |
| 512 MB | 1 | with OneHot | 2 | 4.716 | 0.665 | 5.377 | 368.18 | 29.04 |
| 512 MB | 1 | without OneHot | 1 | 3.521 | 0.479 | 3.999 | 344.97 | 29.04 |
| 256 MB | 1 | with OneHot | 2 | 5.509 | 0.662 | 6.173 | 395.90 | 29.04 |
| 256 MB | 1 | without OneHot | 1 | 3.881 | 0.480 | 4.366 | 381.05 | 29.04 |
| 128 MB | 1 | with OneHot | 2 | 5.711 | 0.670 | 6.381 | 414.19 | 29.04 |
| 128 MB | 1 | without OneHot | 1 | 4.509 | 0.488 | 4.997 | 384.65 | 29.04 |
| 96 MB | 1 | with OneHot | 2 | 5.794 | 0.672 | 6.464 | 416.35 | 29.04 |
| 96 MB | 1 | without OneHot | 1 | 4.544 | 0.487 | 5.032 | 384.13 | 29.04 |
| 64 MB | 1 | with OneHot | 2 | 5.842 | 0.671 | 6.516 | 417.69 | 29.04 |
| 64 MB | 1 | without OneHot | 1 | 4.630 | 0.486 | 5.120 | 386.82 | 29.04 |

With eight threads the lowest limit that passes, of those tried, is 256 MB; at
128 MB and below both pipelines run out of memory. With one thread the lowest
limit tried, 64 MB, passes for both.

At 10,000,000 rows and no limit, the second run adds 0.177 s to learning
(0.774 s against 0.597 s) and 29.05 MB to the bytes read while learning (52.99
MB against 23.94 MB). Applying is the same one run in both.

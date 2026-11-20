---
type: note
tags: [benchmarks, performance, gram, pca, memory, sqlearn]
summary: Learns PCA on 12,500,000 rows of 200 columns, 20 GB as doubles, at a 2 GB DuckDB limit, with the peak memory, the time, and the agreement with DuckDB's covar_pop.
related: [index, gram-batches]
---
# PCA on data larger than memory

A Gram step (ADR 0058) learns from XᵀX of its centred columns, which numpy
sums from batches DuckDB streams, so the data need not fit in memory
([issue #66](https://github.com/glaucis/sqlearn/issues/66), spec §3 rule 3).
This page records how far that reaches on one machine. It is an estimate: the
machine was heavily loaded.

## What was measured

- **Data:** DuckDB generated it from a fixed seed (`SEED = 0`) and wrote it as
  Parquet with `COPY`: 12,500,000 rows of 200 DOUBLE columns, mixed from 11
  latent factors plus noise so that the components are defined. 20.0 GB as
  doubles; the Parquet file is 20.0 GB too (the values do not compress), more
  than the machine's 16 GiB of RAM. Row groups of 20,000 rows (see below).
- **Limit:** `SET memory_limit = '2GB'` on the connection, default threads
  (8), the spill directory on the same disk.
- **Probes**, each in a subprocess of its own so that its peak is its own:
  - `learn`: `sq.Pipeline([sq.decompose.pca()]).learn(path)`, the whole
    learn;
  - `gram`: `gram_matrix` alone, with the means found first;
  - `covar`: DuckDB's own `covar_pop` of every pair of columns (20,100
    aggregates, in groups of 2,000), the matrix the others are compared to.
- **Peak:** `resource.getrusage(RUSAGE_SELF).ru_maxrss` at the end of the
  probe, **bytes on macOS** (kilobytes on Linux; the script converts). The
  baseline is the same reading after the imports, before any data.

Reproduce with `uv run python -m validation.benchmarks.gram_reach [rows
columns]`; it takes about 15 minutes and needs about 20 GB of free disk, which
it frees after.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| Load | `uptime` before: load averages 6.88 8.26 9.22; after: 60.73 59.88 36.79 |

The machine was not quiet: the load was about 7 to 22 when the run began and
rose to about 60 by its end, from other work. The times are estimates and
could be much shorter on a quiet machine; the peaks and the agreement do not
depend on the load.

## Results

| probe | seconds | peak GB | baseline GB | peak less baseline GB |
|---|---|---|---|---|
| learn | 144.5 | 2.99 | 0.05 | 2.94 |
| gram | 130.2 | 2.23 | 0.05 | 2.18 |
| covar | 445.7 | 2.00 | 0.05 | 1.95 |

(GB here are 10⁹ bytes.) The learn took about 2.4 minutes and peaked at
2.99 GB, for data of 20 GB.

Agreement with `covar_pop` (the matrix from DuckDB, with no numpy):

| | value |
|---|---|
| Gram matrix over rows, against `covar_pop`: largest difference over the largest `covar_pop` | 2.6e-14 |
| learn's explained variances, against the eigenvalues of `covar_pop`: largest relative difference | 9.7e-10 |
| learn's components, against its eigenvectors, signs aligned: largest difference | 1.9e-9 |

The first line is the one that measures the streaming; the other two include
the eigenvalue solve, whose error grows as the gap between neighbouring
eigenvalues narrows (not measured here).

## Peak memory against the model

`check_fits` models the numpy side of a learn as 4 copies of the p-by-p matrix
plus 3 copies of a batch (`_COPIES`, `_BATCH_COPIES` of `sqlearn._gram`). At
200 columns the matrices are 1.3 MB and a batch is 100 MB, so the model adds
about 0.3 GB to DuckDB's 2 GB and the baseline: about 2.35 GB.

- The measured peak of the learn, 2.99 GB, is about 0.64 GB over that. The
  `gram` probe alone, 2.23 GB, is about 0.12 GB under it. So the numpy side of
  the Gram (the 3 batch copies) fits the model, and the 3-copy factor holds.
- What the model does not count is in the learn but not in `gram_matrix`
  alone: the extra 0.76 GB of the learn over the `gram` probe. The probe
  counts and averages in two statements, where the learn runs one learn
  statement over the file on 8 threads, and DuckDB's `memory_limit` does not
  cover everything that process holds (Parquet buffers, the thread stacks).
  This run does not say which; it is recorded, not explained.
- `covar` alone peaks at 2.00 GB: DuckDB stayed at its limit when it ran
  alone.

## Two things found on the way

- **The Parquet row group matters.** The first attempt wrote the file with
  DuckDB's default row group of 122,880 rows. At 200 columns a row group is
  about 200 MB as doubles, and 8 threads each reading one did not fit the 2 GB
  limit: the learn failed with DuckDB's out-of-memory error, and its `Fix:`
  named `SET threads = 1`. The same happened on a 2,000,000-row file. With
  20,000-row groups (about 32 MB) the learn fits at 8 threads. This is the
  reading of the file, not the Gram step, and the spec's 2 GB measurement did
  not record its row group.
- **The slow test needs one thread at 256 MB.** `test_pca_large.py` learns
  2,000,000 rows of 50 columns (800 MB) at `memory_limit = '256MB'`; at 8
  threads it fails the same way, at `SET threads = 1` it passes, as the
  core's other slow tests do.

## What it shows

- A learn of 20 GB of doubles finished within a 2 GB DuckDB limit, on a
  machine with less RAM than the data, in about 2.4 minutes under load.
- Its peak was 3.0 GB, in line with the 3.0 GB of spec §6.
- The Gram matrix agrees with DuckDB's `covar_pop` to 3e-14.

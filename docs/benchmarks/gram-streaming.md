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
could be much shorter on a quiet machine. The agreement does not depend on the
load; the peaks may, a little, since thread timing changes what is resident at
once. Each probe ran once.

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

- The measured peak of the learn, 2.99 GB, is about 0.64 GB (27%) over that.
  **The excess is not the Gram step's**
  ([issue #67](https://github.com/glaucis/sqlearn/issues/67)): it is DuckDB
  binding PCA's apply SQL, which the learn builds once the matrix is known (to
  name its output columns). That SQL holds p² constants (each component a sum
  of p weighted inputs), and DuckDB's parser and binder hold memory for it
  outside its `memory_limit`. See below.
- The `gram` probe, 2.23 GB, is under the model. That does not confirm the
  3-copy factor: the `covar` probe peaked at only 2.00 GB, so DuckDB did not
  necessarily reach its limit in the `gram` run, and the probe does not
  isolate the batch copies from DuckDB's share.
- The learn peaked 0.76 GB above the `gram` probe, and both run on the
  default 8 threads: the `gram` probe binds no apply SQL (see below).
- `covar` alone peaks at 2.00 GB.

## Where the excess comes from

Measured for [issue #67](https://github.com/glaucis/sqlearn/issues/67) on a
smaller file of the same shape: 3,000,000 rows of 200 columns (4.8 GB of
Parquet, 20,000-row groups), the same 2 GB limit and 8 threads. A probe
recorded the peak at the start and end of `gram_matrix`, and every 0.2 to 0.5
seconds the process's resident memory, DuckDB's own count of its memory
(`duckdb_memory()`) and the line the learn was running. The machine was
heavily loaded (load averages about 30 to 55); each run ran once.

| run | peak at the matrix's start GB | at its end GB | at the learn's end GB |
|---|---|---|---|
| learn, first | 1.50 | 2.52 | 3.51 |
| learn, second | 1.44 | 2.27 | 2.27 |
| `gram` probe | 1.13 | 1.49 | 1.49 |

- While the matrix streams, DuckDB's count stays at its 2 GB limit and
  resident memory is between 0.8 and 2.4 GB: the stream is within the model.
- After it, DuckDB's count reads 0, and resident memory rose by about 1.1 GB
  while the learn built PCA's apply expressions and DuckDB parsed and bound
  them (`prepare_script_parsed`, `bind`). In the first run this came on top of
  memory not yet handed back from the stream, so the peak rose to 3.51 GB; in
  the second resident memory had fallen to 0.86 GB first, and the peak did not
  rise. Where the peak lands is timing; that the learn holds the bound SQL is
  not.
- On 500 rows, where the stream holds almost nothing, the learn's peak above
  the 0.11 GB baseline after the imports is 0.12, 0.34, 1.17 and 2.03 GB at
  50, 100, 200 and 300 columns: it grows about as p², as the SQL's constants
  do.

`check_fits` models the Gram stream, which the measurement bears out, so it
does not count this. What binding PCA's apply costs at many columns, and how a
cheaper form of the SQL reduces it, is
[issue #73](https://github.com/glaucis/sqlearn/issues/73), below.

## The matrix form (#73)

Since #73 the apply SQL holds the centred row as one list and the kept weights
once, as one `DOUBLE[][]` literal; each output is `list_dot_product` of the
list with its row of the matrix. The same probe before and after: a 500-row
table (1,500 rows at 1,000 columns, so every component is kept), all
components, 8 threads, resident memory above the baseline after the imports,
load average about 3:

| columns | form | learn's peak, GB | after `apply` too, GB | learn, s | apply, s |
|---|---|---|---|---|---|
| 200 | sums of products (before) | 1.11 | 1.98 | 2.1 | 4.5 |
| 200 | matrix | 0.36 | 0.37 | 1.0 | 1.0 |
| 300 | sums of products (before) | 2.14 | 3.46 | 4.4 | 9.9 |
| 300 | matrix | 0.71 | 0.74 | 2.1 | 2.2 |
| 1,000 | matrix | 4.6 | 4.7 to 5.0 | 22 | 26 |

The 200- and 300-column rows were each run twice, and agree within 0.01 GB.
The old form at 1,000 columns was not run: growing as p² from 300 columns, it
would need about 24 GB, over this machine's memory. The matrix form still
grows as p², since every weight is in the SQL; at 1,000 columns it binds 4.6
GB outside `memory_limit`, against 2.75 GB for the same query in plain DuckDB
(#73), the rest being sqlearn building and holding the expression.

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
- Its peak was 2.99 GB, against 3.0 GB measured for the spec, but 0.64 GB over
  what `check_fits`' model gives (2.35 GB). The stream keeps within the model;
  the excess is DuckDB binding PCA's apply SQL after it, outside its
  `memory_limit`, and grows about as p² (issue #67); the matrix form of #73
  makes it about a third, measured on 500 rows above.
- It learns within the limit only if one row group of every column, for each
  thread, fits in it. With DuckDB's default Parquet row groups the learn
  raised an out-of-memory error at 8 threads (200 columns at 2 GB; 50 columns
  at 256 MB); this benchmark avoids it with 20,000-row groups at the default 8
  threads, and the slow test with one thread. Since
  [issue #68](https://github.com/glaucis/sqlearn/issues/68) the error names
  the row group and the fix of smaller ones.
- The Gram matrix agrees with DuckDB's `covar_pop` to 3e-14.

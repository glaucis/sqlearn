---
type: note
tags: [benchmarks, datasets, generators, threads, parquet, sqlearn]
summary: "Measures the sq.datasets generators on 1, 2, 4 and 8 threads, with tickets and with parallel=False, plus the cost at 100 rows and an ordered Parquet export, on a machine that was not quiet."
related: [index, median-reach]
---
# Generators on many threads

[Issue #46](https://github.com/glaucis/sqlearn/issues/46) makes the four
`sq.datasets` generators use every thread DuckDB is given. They number their
rows from work tickets in `meta_sqlearn`
([ADR 0052](../adr/0052-meta-sqlearn.md)); `parallel=False` numbers them with
`range()` on one thread, as before. This page states what that gained and
cost. It recommends nothing.

**The machine was not quiet.** Other work shared it throughout, and the load
average at the start of a probe ran from about 4 to about 35. The first two
rounds of the sum probes ran at 4 to 14; the third round, and every small and
export probe, ran at 10 to 35. The page does not claim a quiet-machine
measurement. The fastest of three runs is the fairest figure here, because
load only slows a run. The small-size cost and the export were measured under
the heaviest load, so read them as rough.

## What was measured

- **Sum:** `sq.datasets.blobs(rows=20_000_000, n_features=20)` with every
  column summed in one query, so DuckDB reads every column. Memory limit
  2 GB, threads 1, 2, 4 and 8.
- **Small:** `sq.datasets.blobs(rows=100).fetchall()` (build and fetch) on 8
  threads: the first call in the process, then the median of the next 30.
- **Export:** `COPY (...) TO 'out.parquet' (FORMAT parquet)` of
  `blobs(rows=20_000_000, n_features=3)`, 8 threads, memory limit 150 MB, with
  the peak size of the temporary folder sampled every 50 ms.
- **Method:** each probe is one fresh process at `nice 10`, run one at a time.
  Sum probes ran in three rounds; in each round every thread count ran
  `parallel=False` and then the default. Small and export probes ran after
  them (the export three times each, alternating). The load average is
  recorded before and after each probe.
- **Not measured:** other generators than `blobs`, other row counts, and the
  limit under which tickets run out of memory.

The probe scripts are not kept in the repository.

## Environment

| | |
|---|---|
| CPU | 8 cores: 4 performance and 4 efficiency |
| RAM | 16 GB |
| DuckDB | 2.0.0 |
| Load average | about 4 to about 35 at the start of a probe |

## Results: 20 million rows, 20 features, summed

Seconds, fastest of three runs / median of three, 2 GB limit.

| Threads | `parallel=False` | Default (tickets) |
|---|---|---|
| 1 | 23.61 / 24.55 | 24.03 / 24.33 |
| 2 | 23.74 / 24.18 | 16.12 / 18.59 |
| 4 | 23.55 / 24.31 | 10.86 / 11.60 |
| 8 | 23.74 / 26.91 | 8.83 / 9.64 |

- `parallel=False` stays at about 24 s at every thread count: `range()` runs
  on one thread.
- On 1 thread the two are the same within the spread of the runs.
- On 8 threads the default is about 2.7 times faster by the fastest runs
  (23.74 s against 8.83 s) and about 2.8 times by the medians (26.91 s against
  9.64 s). The third round, the loaded one, gave 46.69 s against 16.62 s.
  The machine has 4 efficiency cores, so 8 threads do not give 8 times.
- The third round was slower in nearly every cell, by a factor of up to 2
  (`parallel=False` on 4 threads: 47.37 s against 23.55 s fastest), which is
  why the medians sit above the fastest runs.

## Results: 100 rows

Build and fetch, 8 threads, median of 30 calls after the first, measured at a
load average of about 35.

| | first call | median after |
|---|---|---|
| `parallel=False` | 15.46 ms | 10.31 ms |
| Default (tickets) | 51.88 ms | 24.11 ms |

A small relation costs about 14 ms more by default, and the first call about
36 ms more, under that load. This is the heaviest-load measurement on the
page, so it may overstate the cost; it was run once.

## Results: ordered Parquet export

20 million rows, 3 features, 8 threads, 150 MB limit, three runs each.

| | time, s | peak temporary disk | file |
|---|---|---|---|
| `parallel=False` | 4.26 to 4.58 | 0 MB | 485 MB |
| Default (tickets) | 4.84 to 5.99 | about 627 to 630 MB | 485 MB |

Exporting gained no speed, and the default used temporary disk larger than
the file it wrote (about 630 MB against 485 MB), because rows finished early
wait for their turn and overflow to DuckDB's temporary folder
([ADR 0052](../adr/0052-meta-sqlearn.md)). The load ran from about 33 down to
about 21 over these runs.

## Reading it

Under a load that never fell below about 4, the default used the threads it
was given and about 2.7 times less time on 8 of them (fastest of three), cost
about 14 ms more on a 100-row relation, and wrote more temporary disk than
file in an ordered export. Whether a quiet-machine run would move these
figures is not known; it can be repeated if wanted.

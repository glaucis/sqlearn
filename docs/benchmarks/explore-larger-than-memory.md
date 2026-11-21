---
type: note
tags: [benchmarks, performance, exploration, profile, correlations, memory, sqlearn]
summary: Runs sq.explore.profile and correlations on 12,500,000 rows of 200 doubles, a 20 GB Parquet file on a 16 GiB machine, under memory budgets of 2 GB and 4 GB, with the time, peak memory and load of each, which probes completed and which were refused with a Fix, and what failed first.
related: [index, gram-streaming, explore-correlations]
---
# Exploring data larger than memory

`sq.explore.profile` and `sq.explore.correlations` are meant to run on data that
does not fit in memory
([issue #74](https://github.com/glaucis/sqlearn/issues/74), spec §6). This page
records what reached on one machine, and what did not. It is an estimate: the
machine was shared with heavy unrelated work.

## What was measured

- **Data:** 12,500,000 rows of 200 random DOUBLE columns written as Parquet
  with `COPY` and DuckDB's default row groups of 122,880 rows: 20.0 GB (the
  values do not compress), more than the machine's 16 GiB of RAM.
- **Budget:** `sq.set_config(memory=X)` gives DuckDB half of `X` as its
  `memory_limit`: `"4GB"` gave 2 GB (shown by DuckDB as 1.8 GiB) and `"2GB"`
  gave 1 GB (953.6 MiB). Default threads (8).
- **Probes**, one subprocess each so that its peak is its own: `profile`
  (exact, the default), `profile` with `exact=False`, `correlations` (Pearson)
  and `correlations` with `method="spearman"`, each over the file's path, the
  result counted.
- **Peak:** `resource.getrusage(RUSAGE_SELF).ru_maxrss` at the end of the
  probe, read twice a second apart (the two reads were equal every time),
  in GB of 10⁹ bytes.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| Load | see each table: the machine was shared with a Rust build and a virtual machine |

The load average was 2.56 3.85 4.95 when the first round began and between 26
and 145 while its probes ran, which affects the times a great deal and the
peaks a little. Each probe ran once. The times are estimates and could be much
shorter on a quiet machine.

## Results

### The profile

The final code, on the file above.

| probe | `memory=` | result | seconds | peak GB | `uptime` load before; after |
|---|---|---|---|---|---|
| `profile`, exact | `"4GB"` | 200 rows | 103.1 | 2.51 | 5.45; 10.92 |
| `profile`, exact | `"2GB"` | 200 rows | 114.9 | 1.52 | 10.92; 32.65 |
| `profile`, `exact=False` | `"4GB"` | 200 rows | 59.3 | 0.97 | 27.19; 35.93 |
| `profile`, `exact=False` | `"2GB"` | 200 rows | 53.6 | 0.85 | 53.07; 45.64 |

The exact times are from a second round, on a quieter machine. The first round
took 128.4 s at 2.12 GB for `"4GB"` and 196.5 s at 1.23 GB for `"2GB"`, with
load averages of 9.27 to 27.19 and 35.93 to 53.07, so the two rounds' times do
not compare as a change of code. The `exact=False` rows are from the first
round and were not run again after the second.

The exact profile reads each column twice: the scan in blocks of 20 columns,
then the exact distinct counts and quartiles in groups of columns sized to the
memory limit (4 columns a group at `"4GB"` here and 2 at `"2GB"`), a
statement each that reads only its group, and that holds the deviations for the
standard deviation, skewness and kurtosis. `exact=False` takes its estimates
inside the scan and reads each number twice (the deviations follow in blocks of
20), any other column once.

### Correlations

| probe | `memory=` | result | seconds | peak GB |
|---|---|---|---|---|
| Pearson | `"4GB"` | 19,900 pairs | 642.8 | 1.75 |
| Pearson | `"2GB"` | refused with a `Fix:` | 7.3 | 1.26 |
| Spearman | `"4GB"` | refused with a `Fix:` | 146.5 | 2.07 |
| Spearman | `"2GB"` | refused with a `Fix:` | 36.3 | 1.26 |

These probes were in the first round, at load averages of 26 to 145 while they
ran (their own readings were not recorded). Pearson's 19,900 pairs were
computed as 55 statements, each pairing two blocks of 20 columns.

Spearman was refused at both budgets, and the process was not killed by the
operating system. Its first scan, which numbers the source into a temporary
copy, is one statement that reads every chosen column, so each of 8 threads
holds a row group of all 200: 197 MB each. That did not fit a 2 GB limit
(after 146.5 s at `"4GB"`) nor a 1 GB one (after 36.3 s).
sqlearn's message says why and names the fixes: fewer `cols=`, more memory with
`sq.set_config(memory=...)`, fewer threads, or a file with smaller row groups.
Pearson's memory follows its block of columns, so it fit at `"4GB"`; at `"2GB"`
it was refused after 7.3 s.

## What was tried first

The first probes, on the code as built before this round, failed in two ways.

- **A raw `OutOfMemoryException`.** `profile` exact at `"2GB"` and `"4GB"` ran
  out of memory after 1.1 s and 1.4 s, peaks of 1.08 and 1.78 GB, and DuckDB's
  own exception reached the user with no `Fix:`. Its statements were not
  wrapped; they are now, with the fixes named (and `exact=False` first when
  the profile is exact).
- **The operating system killed the process.** `profile` with `exact=False` at
  `"2GB"` was killed (exit 137) three times in about 10 seconds. The cause was
  not the load: it was DuckDB's `FILTER` clause. Each filtered aggregate in an
  ungrouped aggregate gets its own copy of the statement's input chunk, so a
  statement's memory grows with aggregates times input columns, outside
  `memory_limit`. Measured on 1,000,000 rows of 200 columns, one thread, a 4
  GB limit:

  | columns | `FILTER`: peak GB, seconds | `CASE`: peak GB, seconds |
  |---|---|---|
  | 10 | 0.27, 1.1 | 0.14, 0.3 |
  | 20 | 0.72, 4.4 | 0.21, 0.7 |
  | 40 | 2.08, 14.9 | 0.25, 1.4 |
  | 200 | killed (8 threads, 1 GB limit) | 0.58, 8.8 |

  Leaving values out with `CASE` (an aggregate passes over NULL) is linear in
  both, and the estimates then cost no more than a plain `sum` of the same
  columns (2.63 against 2.69 GB over all 200 columns on 8 threads). No
  `FILTER` remains in `profile`.
- **One scan over all 200 columns did not fit either.** Even with `CASE`, a
  statement that reads every column was refused under a 1 to 2 GB limit on
  this file: a plain `sum` of the 200 columns at a 1 GB limit failed to
  allocate 187.5 MiB, one row group of 200 doubles. So the scan is cut into
  blocks of 20 columns, each column still read once. On this file, 8 threads: at
  a 1 GB limit 20 columns peaked at 0.66 GB, 40 at 1.09 GB and 80 ran out of
  memory; at 1.8 GiB, 80 fit (1.86 GB) and 200 ran out.
- **The exact aggregates hold every value.** A `count(DISTINCT)` and an exact
  quantile keep every value and do not spill. At a 2 GB limit on 8 threads
  `count(DISTINCT)` alone peaked at 0.42, 1.19 and 2.17 GB for 1, 4 and 8
  columns (about 20 bytes a value), `quantile_cont` alone at 0.35, 0.82 and
  1.33 GB (about 11 bytes a value). Groups of 2 and 4 columns profiled all 200
  columns and a group of 6 was refused, so the group size is the columns that
  `memory_limit` holds at about 32 bytes a row, from 1 to 20. That was measured
  on doubles: long text in a distinct count may take more, and the error's fix
  then leads with `exact=False`.

## What this shows and does not

- A profile of 20 GB completed under both budgets, exact in 103 to 115 s on
  the quieter run and `exact=False` in 54 to 59 s, at peaks below 2.6 GB.
- Pearson completed at `"4GB"` and was refused at `"2GB"`. Spearman was
  refused at both, and a fix for it is to number the source in column groups
  as Pearson's blocks are bounded (not done).
- Nothing here says how the times scale on a quiet machine, a faster disk or a
  file with smaller row groups, none of which was run.

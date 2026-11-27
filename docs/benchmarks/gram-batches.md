---
type: note
tags: [benchmarks, performance, gram, pca, batches, sqlearn]
summary: Times three ways to cut the batches of a Gram learn on 1,000,000 rows of 50, 200 and 500 columns, and the temporary-table way on 1,000,000 and 4,000,000 rows.
related: [docs/benchmarks/index.md, docs/benchmarks/standard-deviation.md]
---
# How the batches of a Gram learn are cut

A Gram step (ADR 0058) learns from XᵀX of its centred columns, which numpy
sums from batches DuckDB hands over
([issue #66](https://github.com/glaucis/sqlearn/issues/66)). This page times
the ways to cut those batches that need only duckdb and numpy, and says which
one `gram_matrix` uses. It is an estimate: the machine was loaded.

## What was measured

- **Data:** DuckDB generated it from a fixed seed (`SEED = 0`) and wrote it
  as Parquet with `COPY`: spread DOUBLE columns, no NULLs.
- **Ways:**
  - `table`: the centred rows numbered with `row_number() OVER ()` into a
    temporary table, fetched by row range with `fetchnumpy`
    (`gram_matrix`);
  - `fetchmany`: one streaming result of the centred rows, read with
    `fetchmany` into `numpy.array`;
  - `file`: the Parquet file read again for each batch, by
    `file_row_number` range, centred on the fly. It applies only when the
    step's input is one Parquet file, not after an earlier step's SQL.
- **Batches:** `batch_rows` of 100 MB of float64 values (250,000 rows at 50
  columns, 62,500 at 200, 25,000 at 500). One probe per subprocess; one run
  each, not a median.
- **Searched for:** a streaming fetch returning numpy without pandas or
  pyarrow, in DuckDB Python's documentation (context7) and in the installed
  package. Found: `fetchnumpy` (the whole result at once), `fetchmany`
  (Python tuples), `fetch_df_chunk` (pandas), and `to_arrow_reader` /
  `fetch_record_batch` (pyarrow, which sqlearn does not depend on). None
  streams numpy arrays. The ways above are all there are.

Reproduce with `uv run python -m validation.benchmarks.gram_batches`; it
takes about four minutes.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| Load | `uptime` before: load averages 4.07 6.80 6.10; after: 5.92 6.48 6.06 |

## Results

Seconds, 1,000,000 rows. Every way's matrix has the same trace, to the last
digit or the last but one.

| columns | table | fetchmany | file |
|---|---|---|---|
| 50 | 1.24 | 2.81 | 0.62 |
| 200 | 4.21 | 11.45 | 3.13 |
| 500 | 13.63 | 33.04 | 18.14 |

How the `table` way grows with the rows, at 50 columns (a second run of the
1,000,000-row case: 1.17 s):

| rows | table | file |
|---|---|---|
| 1,000,000 | 1.17 | 0.63 |
| 4,000,000 | 4.72 | 2.84 |

Four times the rows took four times as long (4.03), so the row-range filter
shows no growth beyond the rows. The check is limited: at 250,000 rows a
batch, 4,000,000 rows are 16 batches, and a cost of rows times batches would
show only with many more.

## What it shows

- `fetchmany` is the slowest way at every width, 2 to 3 times the `table`
  way: it builds Python tuples.
- `file` is faster at 50 and 200 columns and slower at 500, where the
  centring in SQL and the matrix product weigh more than the reading. It is
  not faster at every width, and it applies to one kind of source.
- `table` stays the way: it works for any query, it is correct at every
  width, and its time follows the rows.

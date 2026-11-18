---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [datasets, threads, parallel, iris, wine, breast-cancer, blobs, regression, classification, customers, seed, parquet, larger-than-memory]
summary: "What sq.datasets gives: three small bundled datasets and four generators written in SQL (blobs, regression, classification, customers), the seed that repeats them, why each is a relation that is a query, how they use many threads and when to pass parallel=False, writing one to Parquet, and generating more rows than memory holds."
related: [docs/specs/library-datasets.md, docs/adr/0045-datasets-are-relations-built-in-sql.md, docs/adr/0006-local-and-offline.md, docs/adr/0043-repeatable-within-rounding.md]
---

# Datasets

`sq.datasets` gives sqlearn data to learn from: three small classic datasets
that ship in the package, and four generators that build rows in SQL from a
seed. Nothing is downloaded, and every function returns a DuckDB relation
whose last column is `target`.

```{code-cell} python
import sqlearn as sq

sq.datasets.iris().limit(3)
```

## What each function gives

| function | rows | columns |
|---|---|---|
| `iris()` | 150 | 4 measurements, `target` (3 classes) |
| `wine()` | 178 | 13 chemical measurements, `target` (3 classes) |
| `breast_cancer()` | 569 | 30 measurements, `target` (2 classes) |
| `blobs(rows, n_features, centers, ...)` | `rows` | `x0`, `x1`, ..., `target` (the centre) |
| `regression(rows, n_features, ...)` | `rows` | `x0`, `x1`, ..., `target` (a number) |
| `classification(rows, n_features, ...)` | `rows` | `x0`, `x1`, ..., `target` (the class) |
| `customers(rows)` | `rows` | `age`, `income`, `city`, `plan`, `target` |

The bundled three are the rows of scikit-learn's `load_iris`, `load_wine` and
`load_breast_cancer`, with the same column names and values. The generators
keep scikit-learn's setting names (`n_features`, `centers`, `cluster_std`,
`n_informative`, `noise`, `flip_y`, ...), with two departures: `rows=` for
`n_samples` and `seed=` for `random_state`.

`customers` is sqlearn's own, with what scikit-learn's generators lack: gaps
and text. A tenth of `age` and a twentieth of `income` are missing, `city` and
`plan` are text, and `target` says whether the customer churned.

```{code-cell} python
sq.datasets.customers(rows=5, seed=0)
```

## The seed

Every random value is a pure function of the seed, the row and the column, so
the same seed gives the same rows, whatever the number of threads. The default
seed is 0; pass another for another sample. A class derived from a normal by a
threshold (`customers`' target) can differ across platforms on the rare row that
lies on the threshold, since normals agree only within rounding there.

```{code-cell} python
a = sq.datasets.blobs(rows=3, seed=1).fetchall()
b = sq.datasets.blobs(rows=3, seed=1).fetchall()
c = sq.datasets.blobs(rows=3, seed=2).fetchall()
a == b, a == c
```

The numbers are sqlearn's own, not scikit-learn's: the same settings give the
same kind of data, not the same values. On one machine the rows repeat bit for
bit. Across machines the uniform numbers are identical, and the normal ones
agree within rounding, because the maths library behind `ln` and `cos` is not
promised to round alike everywhere
([ADR 0043](../adr/0043-repeatable-within-rounding.md)).

## A relation is a query

A generated relation computes no data row when you create it. Each use
computes its rows again, and they are the same rows. So a relation of a
billion rows is created at once, and its first rows come back at once:

```{code-cell} python
huge = sq.datasets.regression(rows=10**9, n_features=5, n_informative=2)
huge.limit(2)
```

A slice of a relation is the same rows as in the whole: the first 1,000 rows
of a million-row relation equal a 1,000-row one.

## Row order

The rows of a generator come in row order while DuckDB's
`preserve_insertion_order` is on (its default). To have the order whatever the
setting, pass `ordered=True`: the relation sorts by the row number. That costs
a sort, and the relation is no longer lazy: it reads every row to sort them,
so a `limit` no longer stops early.

## Threads

The four generators number their rows from small work tickets in a table, so
that DuckDB can share the work between all the threads it is given. The rows
and their order are the same as on one thread. The first call on a connection
makes the table of tickets in `meta_sqlearn`, an in-memory database that
sqlearn attaches beside yours. You will see it in `SHOW DATABASES`. The table
holds about 8 MiB of memory for up to 8 threads, and about 1 MiB per thread
above that. More threads add a larger table and the earlier ones stay, until
the connection closes: 8.25 MiB for 8 threads came to 74 MiB in all once a
table for 64 was added. sqlearn writes nothing to your own database, and your
transactions are left alone.

```{code-cell} python
sq.datasets.blobs(rows=5, seed=1).fetchall() == sq.datasets.blobs(
    rows=5, seed=1, parallel=False
).fetchall()
```

Pass `parallel=False` to number the rows with DuckDB's `range` on one thread
instead, with no `meta_sqlearn`. Do that when:

- You write an ordered export under a memory limit. Rows finished early must
  wait for their turn, and then overflow to DuckDB's temporary folder: `.tmp`
  in the current directory for an in-memory database, `<file>.tmp` beside a
  file database. It must be writable, and its size can exceed the file you
  write: 20 million rows of 3 features on 8 threads under a 150 MB limit held
  about 630 MB at peak for a 485 MB file, and ran no faster (4.84 to 5.99 s,
  against 4.26 to 4.58 s from `range`, which used none). The machine was not
  quiet; see
  [the benchmark](../benchmarks/generators-on-many-threads.md).
- You keep a view in a database file, or run the SQL elsewhere. The view over
  tickets names `meta_sqlearn`, which is gone after reopening the file.

If another database already goes by the name `meta_sqlearn`, in capitals or
not (DuckDB ignores case in database names), sqlearn does not touch it. The
generators then run on one thread, give the same rows, and warn. They do the
same when DuckDB cannot make the table, or when your open transaction began
before there was one; each warning's `Fix:` line says what to do.

## Writing one to Parquet

To keep rows, or to hand them to something that wants a file, write the
relation with DuckDB:

```{code-cell} python
import tempfile
from pathlib import Path

folder = Path(tempfile.mkdtemp())
sq.datasets.customers(rows=1_000, seed=0).to_parquet(str(folder / "customers.parquet"))
sq.Pipeline([sq.impute.median()]).learn(str(folder / "customers.parquet"))
```

## Larger than memory

Because the rows are computed, not stored, a pipeline can learn from more
rows than memory holds, with no file to download or write. DuckDB streams the
rows through the pipeline's query:

```python
big = sq.datasets.customers(rows=10**7)
pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard()]).learn(big)
```

The library's tests run this on 10 million rows under a 64 MB memory limit.
The median is exact, so it sorts the column; on a single thread 10 million
rows fit in 64 MB, and more threads need more memory
(`docs/benchmarks/median-reach.md` has the numbers). Steps that make one pass,
such as `sq.scale.standard()` alone, need little.

## Bad settings

A setting that cannot work is refused with a `SqlearnError` that says what was
wrong, why, and the fix: `rows=0`, a `noise` below 0. scikit-learn raises
`ValueError` in these cases. An explicit `n_informative` above `n_features` in
`regression` is clipped, with a warning.

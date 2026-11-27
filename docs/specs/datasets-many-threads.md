---
type: spec
tags: [datasets, generators, threads, parallelism, duckdb, attach]
summary: "Spec for running the sq.datasets generators on every core (#46): row numbers come from small work tickets in meta_sqlearn, an in-memory database sqlearn attaches beside the user's, so DuckDB shares the work between threads while the rows, their order and the laziness stay as they are."
related: [docs/adr/0045-datasets-are-relations-built-in-sql.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0043-repeatable-within-rounding.md, docs/specs/library-datasets.md]
---
# Generators on many threads

Issue #46. Status: approach chosen by Tomas on 2026-11-18 (an attached
in-memory database, `meta_sqlearn`), after the measurements in §2.

## 1. Intent

`sq.datasets.blobs`, `regression`, `classification` and `customers` compute
each row from `(seed, row number)`, so any core could compute any row. Today
one core computes them all. Tomas overturned ruling R3 of the datasets build
(generators run on one thread): they should use every core.

Who uses it: anyone generating a large dataset, and the docs, examples,
validation and benchmarks that do.

```python
rel = sq.datasets.blobs(rows=20_000_000, n_features=20)
rel.df()  # the same rows as today, computed on every core
```

The one addition to the API is a setting on those four generators,
`parallel=True`. `parallel=False` gives today's SQL (§5).

## 2. What happens today, and what was measured

`random_columns` (`src/sqlearn/datasets/_random.py`) starts from
`FROM range(rows)`. DuckDB runs `range` on one thread, and everything computed
from it stays there. DuckDB shares work between threads when it scans stored
data split into parts: a table's row groups of 122,880 rows, or a Parquet
file's row groups.

All measurements are from 2026-11-18 on an 8-core laptop (4 performance, 4
efficiency cores), DuckDB 2.0.0, at a load average of 3 to 7, so they are not
quiet-machine figures. Probes were throwaway scripts.

| Row source, 20M rows of 20 normals, summed | 1 thread | 8 threads | Verdict |
|---|---|---|---|
| `range(N)`, today | 22.1 s | 22.4 s | the reference |
| Scanned tickets (bundled files), expanded by `unnest` | 21.7 s | 7.5 s | same rows, same order |
| Lateral `range` per ticket | 22.6 s | 23.3 s | rejected: out of order, and `LIMIT 3` on 10¹² rows passed 60 s |

A `MATERIALIZED` CTE of tickets (4M rows) stayed on one thread (4.6 s, 4.3 s).

With the design of §5, tickets in an attached in-memory table:

| Check | Result |
|---|---|
| Ticket table of 8 row groups | 8.2 MiB, made in 3 to 18 ms |
| 4M rows of 8 normals, `range` | 1.75 s on 1 thread, 1.76 s on 4 |
| The same, tickets | 1.80 s on 1 thread, 0.88 s on 4 |
| Sum of 2 normals, 100 rows | 5.9 ms with `range` and with tickets |
| The same, 10,000 rows | 6.1 ms, 6.8 ms |
| The same, 100,000 rows | 12.2 ms, 16.5 ms |
| The same, 1,000,000 rows | 76.6 ms, 38.3 ms |
| `LIMIT 3` of 10¹² rows | 5 ms, 34 ms |
| `LIMIT 3` of 2⁶² rows | 4 ms, 140 ms |
| Rows and order against `range` at 1, 7, 4,095, 4,097, 983,039, 983,041 and 3,000,001 rows | identical |

Where the table can live, on a persistent database, 2M rows, 8 normals:

| | Schema in the user's database | Temporary table | Attached in-memory database |
|---|---|---|---|
| 1 and 4 threads | 0.87 s, 0.43 s | 0.86 s, 0.42 s | 0.87 s, 0.42 s |
| Grows the user's file | yes, 262 KB | no | no |
| Stays after closing | yes | no | no |
| Read-only database | refused | works | works |
| Seen from a cursor | not tested | no | yes |
| User's `ROLLBACK` removes it | yes | yes | no, when made on a cursor |

An attached in-memory database overflows to disk like any other in DuckDB. 40M
rows (about 640 MB) under a 300 MB limit: 280 MB of memory, 366 MB in the
temporary folder, gone on closing. The folder is `.tmp` in the current
directory for an in-memory main database and `<file>.tmp` beside a file
database, read-only ones included. If it cannot be created, a query that must
overflow fails. After `kill -9` its files stay.

Transactions, on a persistent database:

| Case | Result |
|---|---|
| Tickets made on the user's connection after `BEGIN`, no write yet | **the user's next `INSERT` fails**: one transaction writes one database |
| Tickets made on the connection after a write | refused |
| Tickets made on a `cursor()`, before or after the user's write | works; the user's writes, `COMMIT` and `ROLLBACK` are untouched; the tickets stay and are readable inside the transaction |
| Table replaced on a cursor while the user's transaction has already read it | **the transaction keeps seeing the old table** |

Two costs of tickets, found by the review of this spec. An ordered export must
hold finished blocks until their turn comes, and under a memory limit they
overflow to disk. `COPY ... TO parquet`, 4 normals, 4 threads, 150 MB limit,
load average 8 to 9:

| Rows | Source | Time | Peak temporary disk | File |
|---|---|---|---|---|
| 5M | `range` | 1.2 s | 0 MB | 180 MB |
| 5M | tickets | 1.2 s | 4 MB | 180 MB |
| 20M | `range` | 5.1 s | 0 MB | 720 MB |
| 20M | tickets | 5.8 s | 433 MB | 720 MB |
| 20M | tickets, `preserve_insertion_order=false` | 2.1 s | 0 MB | 720 MB |

With the temporary folder turned off, 8M row numbers on 4 threads exported under
`range` at 30 MB and 60 MB limits, and ran out of memory with tickets. Fetching
in batches did not suffer: the first 102,400 of 20M rows came back in order in
0.03 s from either source.

A view saved in a database file over ticket SQL fails after reopening
(`meta_sqlearn.tickets_8 does not exist`); one over `range` keeps working. The
same holds for the SQL text run elsewhere.

## 3. Goals, non-goals, anti-goals

Goals:

- The four generators use every thread DuckDB is given.
- **Same rows:** bit for bit the rows of today on one machine.
- **Same order:** row-number order while `preserve_insertion_order` is on.
  `ordered=True` keeps its meaning.
- **Lazy:** creating a relation computes no data row, at any `rows` up to
  `2**63 - 1`, and `limit` stops early.
- **One thread still works**, at about today's speed.
- Works on in-memory, persistent and read-only databases, and inside a user's
  open transaction.
- **A way back:** `parallel=False` gives today's self-contained SQL.

Non-goals:

- Moving other tables sqlearn creates into `meta_sqlearn`. It can hold more
  later; each such move is its own decision.
- Keeping anything between runs. Nothing here needs a `.sqlearn` folder.
- Changing the random numbers, the columns or any existing setting of a
  generator.
- A public setting for the number of tickets.
- Bounding the temporary disk of an ordered export under the default. It is
  accepted and documented; `parallel=False` avoids it.

Anti-goals, which make the work a failure even if it is faster:

- A missing, repeated or reordered row, in any case, silently.
- Anything written to the user's database or changed in their transaction.
- Changing the user's DuckDB settings (`threads`, `temp_directory`,
  `preserve_insertion_order`).
- A cost at small sizes that a user would notice.

## 4. Approaches

| Approach | For | Against | Outcome |
|---|---|---|---|
| **Attached in-memory database** | same connection and speed; user's file untouched; read-only works; seen from cursors; goes away by itself | the name can be taken; 8 MiB of memory per connection | **chosen by Tomas** |
| Small files in the package | nothing created at run time | a path into the installed package in the SQL | my first recommendation, dropped for the above |
| Schema in the user's database | one place, Tomas's first idea | changes the user's file, fails on read-only, removed by `ROLLBACK` | rejected by the measurements of §2 |
| `.sqlearn/meta.duckdb` in the project | visible on disk | a second program is locked out (`Could not set lock`); a library cannot know the project root; leaves files | not needed: DuckDB already overflows to its temporary folder |
| Temporary table | no file, no name in the catalog | not seen from cursors, which sqlearn's streaming uses | rejected |
| `preserve_insertion_order=false` | fast | gives up the order and changes a user's setting | rejected |

## 5. Design

### Terms

A **work ticket** is one row of a ticket table: a number that stands for one
block of row numbers. Add the term to `GLOSSARY.md`, and `meta_sqlearn`.

### The `parallel` setting

`blobs`, `regression`, `classification` and `customers` take `parallel=True`,
last, after `ordered`, chosen by Tomas on 2026-11-18. It is refused unless a
bool, as `ordered` is.

| Call | Threads | Row source | `meta_sqlearn` |
|---|---|---|---|
| `parallel=True` (default) | all DuckDB is allowed | tickets | used |
| `parallel=False` | one | `range(rows)`, today's SQL | neither attached nor read |

The rows are the same either way. `parallel=False` is for an ordered export
that should use no extra temporary disk, and for SQL that must outlive the
connection: a saved view, or the text run elsewhere. `ordered=True` works with
both values.

### `meta_sqlearn`

- An in-memory database attached under the name `meta_sqlearn`, on sqlearn's
  connection (`connection()`), the first time a generator needs it:
  `ATTACH ':memory:' AS meta_sqlearn (READ_WRITE)`. `READ_WRITE` is required on
  a read-only main database.
- **Every write goes through a `cursor()` of that connection**, closed
  afterwards. A write on the connection itself would join the user's
  transaction and break it (§2). sqlearn never executes or fetches on the
  user's connection for this either: that would discard a result the user has
  begun to read. It checks, attaches and creates through a cursor.
- It goes away when the connection closes. sqlearn never drops it or its
  tables while the connection lives: relations already made read them.

### Ticket tables

- `meta_sqlearn.main.tickets_<groups>`, named in three parts because a
  two-part name is ambiguous when the user has a schema called `meta_sqlearn`.
  One `BIGINT` column `ticket`, holding `0` to `groups * 122880 - 1` in order,
  made `ORDER BY range`.
- `groups` is `max(8, threads)`, reading DuckDB's `threads` setting when the
  generator is called.
- **A ticket table is never changed or replaced.** A larger thread count makes
  a new, larger table. This is what keeps a transaction safe: replacing a table
  would leave a running transaction seeing the old rows while new SQL counted
  on the new ones, and rows would go missing without an error.
- A generator finds which ticket tables **the user's connection** can see by
  binding a query against each (listed on a cursor, never executed on the
  connection), after creating any it wants, and uses the largest it sees. A
  transaction that cannot see the new table uses a smaller one, on fewer
  threads, with the same rows.
- Creating ticket tables is safe when two Python threads call generators at
  once (one lock). Generators on one shared connection called at the same time
  remain refused by DuckDB's Python connection ("connection is busy"), as they
  are today and with `parallel=False` too.

### The row source

`random_columns` keeps its behaviour by default and takes the row source as a
new optional argument, because tests, validation and its doctest run its SQL on
connections with no `meta_sqlearn`. The generators pass the ticket source.

For `rows` = N and T tickets in the table:

1. `used = min(T, N)` tickets, each standing for `size = ceil(N / used)` rows.
2. Read `WHERE ticket < used`. Row groups past `used` are skipped, so small
   datasets stay cheap.
3. Widen each ticket into blocks by repeated `unnest(range(...))`, at most
   4,096 children per step, as many steps as `size` needs, so no list is ever
   large, then unnest the block into row numbers.
4. Compute start and end in `HUGEINT`, clamp the end to N, and cast to `BIGINT`
   for `range`: at `2**63 - 1` rows the sums overflow `BIGINT`.

The column it gives is `range`, as today, so the rest of `random_columns` does
not change. Sketch (the last block of a step ends where its parent does, so
a width that is not a multiple of the child width repeats no row):

```sql
SELECT unnest(range(least(a, N)::BIGINT, least(a + w, N)::BIGINT)) AS range
FROM (
  SELECT s AS a, least(child::HUGEINT, e - s) AS w
  FROM (
    SELECT unnest(range(least(a, N)::BIGINT, least(a + w, N)::BIGINT, child))
             ::HUGEINT AS s,
           a + w AS e
    FROM (
      SELECT ticket::HUGEINT * size AS a, size::HUGEINT AS w
      FROM meta_sqlearn.tickets_8
      WHERE ticket < used
    )
  )
)
```

### When it cannot be used

With `parallel=True`, the generator falls back to `FROM range(rows)`: **the same
rows, on one thread**, with a `SqlearnWarning` in the house form (ADR 0046),
whose `Fix:` gives the remedy for the case and also names `parallel=False` for
silencing it. A generator never
fails for this reason.

| Case | What happens |
|---|---|
| A database named `meta_sqlearn`, in any case, exists and is not sqlearn's | fall back, warn; `Fix:` detach or rename that database. sqlearn does not write to it |
| Attaching or creating fails for another reason | fall back, warn, with the first line of DuckDB's message; `Fix:` free memory or allow a temporary folder |
| The user's connection sees no ticket table (its transaction began before any was made) | fall back, warn; `Fix:` end the transaction |
| The user detached `meta_sqlearn` after a relation was made | that relation fails on reading, as any relation whose table is gone; the next generator call attaches it again |

DuckDB ignores case in database names. A database counts as sqlearn's when it
is named exactly `meta_sqlearn`, is in memory (no path), holds no view,
sequence, macro, type or schema of its own, and every table in it is
`tickets_<groups>` with one `BIGINT` column `ticket`, `groups * 122880` rows,
and no row where `ticket IS DISTINCT FROM rowid`. An empty in-memory database
of that name counts as sqlearn's. The check runs on a cursor and sees committed
state only.

## 6. Tests

Named in `GLOSSARY.md` terms, through `sq.datasets` wherever possible, each
watched failing first.

- Each generator gives the rows of the `range` source, in order, bit for bit, on
  1, 2 and 8 threads, at sizes around every boundary: 1, the fan-out 4,096 and
  its neighbours, one row group, the table's size and its neighbours.
- At `rows=2**63 - 1`: creating is immediate, `limit` returns rows 0, 1, 2, and
  the source's last row number is `2**63 - 2`, with no gap or repeat at the
  edges of the last blocks.
- The work is shared: a plan or a timing comparison of two thread counts in one
  test, never an absolute time (see `HANDOFF.md`).
- A relation of 10⁹ rows is created at once, and `limit` returns at once.
- On a persistent database the file's tables, and its size after `CHECKPOINT`,
  are unchanged; after reopening nothing of sqlearn's is there.
- On a read-only database the generators work.
- In the user's transaction, before and after a write: the generator works, the
  user's next write works, `COMMIT` and `ROLLBACK` do what they should, and the
  tickets remain.
- Thread count raised during a transaction that has read `meta_sqlearn`: a new
  relation has every row, in order.
- Two Python threads calling generators at once on a new connection: the
  ticket table is made once and no call fails for it.
- A foreign `meta_sqlearn`, in memory and as a file: right rows, one warning,
  nothing written to it.
- Streaming to a model through a cursor (`feed="stream"`) reads a generated
  relation.
- A pipeline learned from a generated relation saves, loads and applies.
- `limit`, `ordered=True` and `preserve_insertion_order=false` keep their
  behaviour, with `parallel` true and false.
- `parallel=False` gives the same rows as the default, its SQL does not name
  `meta_sqlearn`, the database is not attached by it, and a view over it works
  after the database file is reopened.
- A `parallel` that is not a bool is refused in the house form.
- An ordered export under a memory limit succeeds by using the temporary folder,
  and with `parallel=False` uses none.

The existing thread-count tests whose docstring says `range()` cannot fail yet
are updated. Validation of the distributions stays as it is.

## 7. Documents

- New ADR: `meta_sqlearn`, what it is for and the rules of §5. It says that any
  later table placed there follows them.
- ADR 0045 amended: generators run on every thread; "creating it reads and
  writes nothing" becomes "no data row", since the first generator call on a
  connection makes the small ticket table.
- `docs/specs/library-datasets.md` and `docs/guide/datasets.md`: the same two
  points, what a user sees (`meta_sqlearn` in `SHOW DATABASES`, about 8 MiB of
  memory up to 8 threads and about 1 MiB per thread above), and when to pass
  `parallel=False`: the temporary disk of an ordered export (needing a writable
  temporary folder), and views or SQL that must outlive the connection. The
  generators' docstrings describe the setting.
- `docs/benchmarks/`: the measurements of §8 on a page of their own.
- `HANDOFF.md`: #46 moved to "Just finished", and the traps saying `range()`
  and generators run on one thread kept only where still true.

## 8. Done when

- The goals of §3 hold, by the tests of §6.
- Today's source and the new one are measured on a quiet machine, at 1, 2, 4 and
  8 threads, with `uptime` before and after, under a memory limit that keeps the
  laptop responsive. **Tomas is asked before that run**, which needs all 8
  threads. No speed-up figure is promised in advance: this machine has 4
  performance and 4 efficiency cores.
  Measured on 2026-11-18, not on a quiet machine (load average about 4 to
  about 35): see
  [the benchmark](../benchmarks/generators-on-many-threads.md).
- `just verify` passes, and #46 is closed with the results.

## 9. Left to the builder

- Module and function names; the source would suit a small private module in
  `src/sqlearn/datasets/`.
- The wording of the warnings, in the house form.
- How the shape and contents of a ticket table are checked, as long as a foreign
  table is never taken for one.
- How the work sharing is shown in a test.

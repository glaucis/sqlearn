---
type: adr
tags: [datasets, generators, threads, parallelism, duckdb, attach, meta-sqlearn, work-tickets]
summary: "Records that sqlearn's own tables live in meta_sqlearn, an in-memory database it attaches beside the user's, written only through a cursor, with immutable ticket tables that give the dataset generators row numbers DuckDB can share between threads; a database of that name that is not sqlearn's makes the generators fall back to range with a warning, and parallel=False gives the old SQL."
related: [docs/specs/datasets-many-threads.md, docs/adr/0045-datasets-are-relations-built-in-sql.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0043-repeatable-within-rounding.md, docs/adr/0002-sql-on-duckdb-execution-engine.md]
---
# 0052: sqlearn's own tables live in `meta_sqlearn`

Status: accepted (2026-11-18); moved out of the package with the generators
by [ADR 0053](0053-sqlearn-ships-no-datasets.md). Issue #46,
[spec](../specs/datasets-many-threads.md). Amends
[ADR 0045](0045-datasets-are-relations-built-in-sql.md).

## Context

The generators of `sq.datasets` compute each row from `(seed, row number)`, so
any core could compute any row, but they started from `FROM range(rows)`, and
DuckDB runs `range` on one thread. DuckDB shares work between threads when it
scans stored data split into parts: the 122,880-row row groups of a table.

Measured on 2026-11-18 on an 8-core laptop, DuckDB 2.0.0, at a load average of
3 to 7: 20 million rows of 20 normals, summed, took 22.1 s on one thread and
22.4 s on eight from `range`; from scanned tickets expanded by `unnest`, 21.7 s
and 7.5 s, with the same rows in the same order. A lateral `range` per ticket
was out of order and not lazy. So row numbers must come from a stored table.
That table has to live somewhere, and where it lives matters (spec section 2):

- In a schema of the user's database it grows their file, stays after closing,
  is refused on a read-only database, and is removed by their `ROLLBACK`.
- On the user's connection, any write after `BEGIN` makes their next
  `INSERT` fail: one transaction writes one database.

## Decision

- **`meta_sqlearn`** is an in-memory database that sqlearn attaches on its
  connection the first time a generator needs it
  (`ATTACH ':memory:' AS meta_sqlearn (READ_WRITE)`; `READ_WRITE` is needed on
  a read-only main database). It goes away when the connection closes, and
  sqlearn never drops it or its tables while the connection lives.
- **Every write goes through a `cursor()`** of sqlearn's connection, closed
  afterwards. sqlearn never executes or fetches on the user's connection for
  this, because that would end a result the user has begun to read. It checks,
  attaches and creates through a cursor, and finds what the user's connection
  can see only by binding a query against each table.
- **Ticket tables** are `meta_sqlearn.main.tickets_<groups>`, named in three
  parts, because a two-part name is ambiguous when the user has a schema called
  `meta_sqlearn`. Each has one `BIGINT` column `ticket` holding `0` to
  `groups * 122880 - 1`, made `ORDER BY range`. `groups` is
  `max(8, threads)`, read when the generator is called.
- **A ticket table is never changed or replaced.** A larger thread count makes
  a new, larger table. Replacing one would leave a running transaction seeing
  the old rows while new SQL counted on the new ones, and rows would go
  missing without an error. A generator uses the largest table the user's
  connection sees; a transaction that cannot see a newer table uses a smaller
  one, on fewer threads, with the same rows.
- **Ownership.** DuckDB ignores case in database names, so `META_SQLEARN`
  takes the name too. A database counts as sqlearn's only if it is named
  exactly `meta_sqlearn`, is in memory, holds no view, sequence, macro, type
  or schema of its own, and every table in it is `tickets_<groups>` with one
  `BIGINT` column `ticket`, `groups * 122880` rows, and no row where
  `ticket IS DISTINCT FROM rowid`. An empty in-memory database of that name
  counts as sqlearn's. sqlearn writes nothing to any other. The check runs on
  a cursor, so it sees committed state only.
- **Fallback.** When tickets cannot be used (the name is taken by another
  database, attaching or creating fails, or the user's connection sees no
  ticket table because its transaction began before any), the generator reads
  `range(rows)`: the same rows, on one thread, with a `SqlearnWarning` in the
  house form ([ADR 0046](0046-sqlearn-warns-the-user-chooses.md)). Its `Fix:`
  gives the remedy for the cause (detach or rename the other database; free
  memory or allow a temporary folder; end the transaction) and always offers
  `parallel=False`. A generator never fails for this reason.
- **`parallel=False`**, a last setting of `blobs`, `regression`,
  `classification` and `customers`, gives today's SQL: `range(rows)`, one
  thread, and `meta_sqlearn` neither attached nor named. The rows are the same.
- Creating ticket tables is safe under concurrent calls from several Python
  threads (one lock). DuckDB's Python connection refuses simultaneous calls on
  one connection ("connection is busy"), `parallel=False` included; that is as
  it was and is not changed here.
- **Any later table sqlearn places in `meta_sqlearn` follows these rules**:
  in memory, written through a cursor, never replaced, checked before it is
  trusted, and a fallback with a warning when it cannot be used. Each such
  move is its own decision.

## Considered

- **Small files in the package:** nothing created at run time, but a path into
  the installed package in the SQL. Dropped for the attached database.
- **A schema in the user's database:** rejected by the measurements above.
- **`.sqlearn/meta.duckdb` in the project:** a second program is locked out, a
  library cannot know the project root, and files are left behind; DuckDB
  already overflows to its own temporary folder.
- **A temporary table:** not seen from cursors, which sqlearn's streaming uses.
- **`preserve_insertion_order=false`:** gives up the order and changes a
  user's setting.

## Consequences

- The first generator call on a connection makes a ticket table: `meta_sqlearn`
  shows in `SHOW DATABASES`, and memory is held for the life of the connection:
  about 8 MiB for up to 8 threads, about 1 MiB per thread above that, and
  earlier tables stay (a table of 8 row groups was 8.25 MiB, made in 3 to
  18 ms; adding one of 64 brought the total to 74 MiB). So
  [ADR 0045](0045-datasets-are-relations-built-in-sql.md)'s "reads and writes
  nothing" becomes "computes no data row".
- An ordered export must hold finished blocks until their turn. Under a memory
  limit they overflow to DuckDB's temporary folder (`.tmp` in the current
  directory for an in-memory main database, `<file>.tmp` beside a file
  database), which must be writable. `COPY ... TO parquet`, 4 normals, 4
  threads, 150 MB limit, load average 8 to 9, 20M rows: 433 MB peak temporary
  disk from tickets, none from `range`. With the temporary folder turned off,
  8M row numbers on 4 threads exported under `range` at 30 MB and 60 MB limits
  and ran out of memory with tickets. `parallel=False` avoids both.
- A view saved in a database file over ticket SQL fails after reopening
  (`meta_sqlearn.tickets_8 does not exist`); the same holds for the SQL text
  run elsewhere. Views and SQL that must outlive the connection need
  `parallel=False`.
- Where a stored scan can be shared, 4M rows of 8 normals took 1.75 s on one
  thread and 1.76 s on four from `range`, and 1.80 s and 0.88 s from tickets.
  At 100 rows to 100,000 rows the difference is a few milliseconds; at 10 to
  the 12th rows `limit 3` took 5 ms from `range` and 34 ms from tickets.
  The final measurement is on
  [its own page](../benchmarks/generators-on-many-threads.md), on a machine
  that was not quiet (load average about 4 to about 35): 20M rows of 20
  features summed took 23.74 s with `parallel=False` and 8.83 s with tickets
  on 8 threads (fastest of three, about 2.7 times), and the two were the same
  on 1 thread. A 100-row relation cost 24.11 ms against 10.31 ms, and an
  ordered export gained no speed and held about 630 MB of temporary disk
  against a 485 MB file.

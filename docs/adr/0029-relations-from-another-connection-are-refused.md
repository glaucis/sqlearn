---
type: adr
tags: [inputs, relations, connection, duckdb, store]
summary: "Records that a DuckDB relation is read through a temporary view on sqlearn's connection, and that a relation belonging to another connection is refused rather than re-run there."
related: [docs/adr/archived/0021-inputs-and-how-the-store-knows-them.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md]
---
# 0029: Relations from another connection are refused

Status: accepted (2026-11-05). Made during the core build, reviewed after it.

## Context

sqlearn runs every query on one connection: the one given with
`sq.set_config(connection=con)`, else its own in-memory one. A DuckDB relation
belongs to the connection that made it. The first build re-ran a relation's
SQL text on sqlearn's connection, which silently learned from the wrong data
when both connections had a table of the same name:

```python
con = duckdb.connect("shop.db")
pipe.learn(con.sql("FROM customers"))  # sqlearn's connection has its own "customers"
```

## Decision

- A relation is registered as a temporary, uniquely named view on sqlearn's
  connection (`con.register`), and the pipeline reads that view. Nothing is
  written to the user's database, and a read-only database works. The view is
  dropped when sqlearn is done with it.
- A relation of another connection cannot be registered there, so it is
  refused with a message naming the fix: `sq.set_config(connection=con)`, or
  pass a table name, a file or a pandas frame.
- The store key of a relation holds the connection as well as its SQL text
  ([ADR 0021](archived/0021-inputs-and-how-the-store-knows-them.md)).

## Consequences

- Relations built on a frame found by name (`duckdb.sql("FROM df")`) work: the
  view keeps the frame's scan alive.
- A relation from `con.cursor()` is refused too: its view is not visible on
  `con`. Supporting a second connection would need queries to run on it,
  which is not planned.

---
type: guide
tags: [inputs, learned-state, store, cache, tables, relations, keep-prepared, search]
summary: "How sqlearn notices that the data passed to learn or train has changed, and the one change it does not notice: a table or relation edited in place with the same row count; and how a search keeps prepared folds in a DuckDB file across sessions (keep_prepared)."
related: [docs/adr/0014-learning-store.md, docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/specs/library-core.md]
---

# Inputs and the learning store

sqlearn keeps what each step learned in a store while the program runs, so
learning the same pipeline again on the same data learns nothing
([ADR 0014](../adr/0014-learning-store.md)). Before it reuses an entry, it
checks that the data has not changed, as cheaply as is safe for each kind of
input ([ADR 0021](../adr/0021-inputs-and-how-the-store-knows-them.md)):

| input | a change is noticed in |
|---|---|
| file or glob | the paths, sizes and modification times |
| DuckDB table | the connection, the name, the row count, the column names and types |
| DuckDB relation | the connection, the SQL text, the row count, the column names and types |
| pandas DataFrame | every value and the row order, the column names and types |

## What is not noticed: a table changed in place

A table or a relation is not read whole to decide whether it changed: that
would cost a pass over data that may be larger than memory. So a change that
keeps the row count and the columns is not noticed. After an `UPDATE`, or a
`DELETE` followed by as many `INSERT`s, `learn` and `train` find the old
values in the store and learn nothing:

```python
pipe.learn("customers")
con.execute("UPDATE customers SET age = age + 1")
pipe.learn("customers")  # same rows, same columns: the old values are used
```

The remedy is to pass the changed data so that it is seen as new: under a new
name (`CREATE TABLE customers_2 AS ...`), or as a file or a pandas DataFrame,
whose changes are always noticed. Or clear the store, which forgets every
learned value:

```python
pipe.learn("customers")
con.execute("UPDATE customers SET age = age + 1")
sq.store.clear()  # forget every learned value
pipe.learn("customers")  # learns again
```

Size limits for the store wait for
[issue #23](https://github.com/glaucis/sqlearn/issues/23).

The steps that learn from the data ([imputing](imputing.md),
[scaling](scaling.md), [encoding](encoding.md), [binning](binning.md) and the
spline in [making features](making-features.md)) use the store like any other:
learning again on unchanged data learns nothing.

## Prepared folds kept across sessions: `keep_prepared`

The store lives only while the program runs. A search can also keep each
fold's prepared rows in a DuckDB file, so a second search tomorrow, in a new
process, on the same data, steps and folds prepares nothing:

```python
search = sq.search(
    pipe, params={"model__C": [0.1, 1.0]}, keep_prepared="project.duckdb"
)
search.train("customers.parquet", target="churned")
search.transforms_  # 5: each fold prepared once and written to the file
# tomorrow, in a new session:
search = sq.search(pipe, params={"model__C": [10.0]}, keep_prepared="project.duckdb")
search.train("customers.parquet", target="churned")
search.transforms_  # 0: every fold read back from the file
```

The tables sit in the file's schema `sqlearn_prepared`, one per fold and
preparation, with an `_index` listing them. The file is attached only while
`train` runs, so another process can open it afterwards. A table's name
carries a key that is the same in every process, so a stale table is never
read:

| part of the key | known by |
|---|---|
| file or glob | the absolute paths, sizes and modification times |
| pandas DataFrame | every value and the row order, the column names and types |
| table in a DuckDB database file | the file, the table's name, its row count and columns |
| the target | its name |
| each step | its name, its class's module and name, and its settings |
| the folds | the scheme and its settings, and the fold |
| the versions | sqlearn's and DuckDB's |

A relation, or a table of an in-memory database, is known only to the
process that made it, and is refused with `keep_prepared`. A step's settings
are keyed by their content: plain values (numbers, text, `None`, and lists,
tuples, dicts and sets of them), module-level functions by their dotted name,
steps, sqlearn's selectors and aggregates, and numpy arrays by their bytes.
Any other setting (a lambda, a function defined inside another, a
`functools.partial`, a pandas object) is refused, since nothing names it the
same way in the next session and its `repr` may hide a difference.

What the key cannot see:

- a table of a database file edited in place that keeps its row count and
  columns (an `UPDATE`, or as many rows deleted as inserted), as for the
  store above;
- a change to the **code** of a step of your own (or of a function it takes)
  that keeps its class name and settings;
- a change to sqlearn's own code in an editable or git install, where its
  version does not change when its code does.

After any of these, remove what the file keeps:

```python
sq.store.prepared("project.duckdb")  # one row per kept table
sq.store.clear(prepared="project.duckdb")  # drop every kept table
```

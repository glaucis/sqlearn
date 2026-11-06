---
type: guide
tags: [inputs, learned-state, store, cache, tables, relations]
summary: "How sqlearn notices that the data passed to learn or train has changed, and the one change it does not notice: a table or relation edited in place with the same row count."
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

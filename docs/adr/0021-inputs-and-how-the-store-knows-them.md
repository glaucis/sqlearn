---
type: adr
tags: [inputs, learned-state, cache, fingerprint, pandas, polars, memory]
summary: "Records that sqlearn accepts any input DuckDB reads, and how the learning store recognises each kind: file and table metadata, the object for immutable tables, a content fingerprint for pandas and numpy."
related: [docs/adr/0014-learning-store.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0019-custom-steps-and-failure-feedback.md]
---
# 0021: Inputs, and how the store recognises them

Status: accepted (2026-11-04). Extends the data part of the store's key in
[ADR 0014](0014-learning-store.md), which covers files and tables only.

## Context

The learning store reuses a step's learned values when the data, the fold and
the steps up to that step all match (ADR 0014). Users work in notebooks: they
change a step and re-run a cell, and expect only the changed step and those
after it to learn again. They also change data in cells
(`df["age"] = df["age"].clip(0, 100)`); with the same steps, a store that did
not notice would reuse a median learned before the change, silently.

Checked on DuckDB 2.0.0: a relation from `read_csv` keeps no data and reads
the file again on every query; `CREATE TABLE ... AS` keeps its own copy. A
pandas DataFrame changes in place; Polars and Arrow tables never do. Hashing
every value of a pandas DataFrame of 10 numeric columns took 0.007 s at a
million rows and 0.117 s at ten million, against 0.195 s and 1.722 s for one
learn query (median, mean and spread of each column): about 5% of one learn.
scikit-learn caches nothing by default; its opt-in `Pipeline(memory=...)`
hashes the whole input on every call.

## Decision

`learn`, `train` and a search accept anything DuckDB reads: files (Parquet, CSV,
JSON, globs such as `data/*.csv`), DuckDB tables and relations, and pandas,
Polars and Arrow tables in memory. DuckDB reads the in-memory ones itself, so
sqlearn still depends only on `duckdb`
([ADR 0005](0005-runtime-dependencies.md)).

The store recognises each kind as cheaply as is safe:

| input | recognised by | cost |
|---|---|---|
| file | path, size, modification time | free |
| DuckDB table | connection, name, row count | free |
| Polars, Arrow | the object itself (immutable) | free |
| pandas, numpy | a fingerprint of the values and their row order | about 5% of one learn |

The fingerprint is a hash computed by DuckDB, once per call to `learn`,
`train` or a search, never once per fold. It covers row order because folds
are tied to rows.

The store never keeps the user's data alive: it holds an immutable table only
through a weak reference, and falls back to the fingerprint where a weak
reference is not possible. Nothing watches the data in the background; the key
is compared only when a call is made.

## Consequences

- In a notebook, re-running a cell learns only what changed: a step's setting
  relearns that step and those after it; an edited DataFrame relearns
  everything that read it.
- The store holds keys, learned values and SQL text, never data: kilobytes per
  step. A size limit, removal of old entries and a `sq.store.clear()` wait
  until measurement asks for them
  ([issue #23](https://github.com/glaucis/sqlearn/issues/23)); the slice's
  tests report the store's size.

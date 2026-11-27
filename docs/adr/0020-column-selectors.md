---
type: adr
tags: [columns, selectors, api, polars, schema]
summary: "Records how steps choose columns: by name or by kind with Polars-style selectors that combine, resolved in Python from the schema and fixed at learn."
related: [docs/adr/archived/0018-runs-follow-the-chains-between-steps.md, docs/adr/archived/0014-learning-store.md, docs/adr/0003-scikit-learn-style-api.md]
---
# 0020: Column selectors

Status: accepted (2026-11-04). Amended by
[ADR 0034](0034-a-grouped-api.md): `sq.numeric()` and `sq.string()` are now
`sq.cols.numeric()` and `sq.cols.string()`. Amended by
[ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md): the Python
bindings hold no logic, so selectors are resolved in the C++ library, not in
Python.

## Context

Steps work on some columns. Users name them (`cols=["age", "x"]`) or choose them
by kind, as scikit-learn's `make_column_selector` and Polars' selectors allow.
sqlearn must know which columns a step reads before it builds the query, to plan
the runs ([ADR 0018](archived/0018-runs-follow-the-chains-between-steps.md)).

Checked on DuckDB 2.0.0: `COLUMNS(* EXCLUDE (id))` and
`COLUMNS(lambda c: c LIKE 'a%')` select by name, but nothing selects by type.
A relation's names and types (`rel.columns`, `rel.types`) come without reading
a row.

## Decision

- `cols=` takes names or a selector. The first selectors are by kind, starting
  with `sq.numeric()` and `sq.string()`; more kinds (dates, booleans, name
  patterns) are added later without touching the run logic, and users will be
  able to write their own.
- Selectors combine with Polars' operators: `|` (or), `&` (and), `-` (except),
  `~` (not). `sq.numeric() - sq.cols("id")` is "all numeric columns but `id`".
  The interface is copied from Polars, not invented.
- A selector is resolved in Python against the schema **at that point in the
  pipeline**, then the SQL gets plain names. After `OneHot(cols=["city"])`,
  `sq.numeric()` includes the new `city_*` columns (so that step waits for
  OneHot), and `sq.string()` no longer includes `city` (so it does not).
- Selectors are fixed at `learn`: the names they matched go into the learning
  store ([ADR 0014](archived/0014-learning-store.md)), so `apply` on other data
  uses the training columns, as scikit-learn's selector does.

## Consequences

- The list of columns a step touches can be shown to the user, and later in the
  node editor.
- A dynamic step declares the types of the columns it will create, so selectors
  can be resolved before its names are known (ADR 0018).

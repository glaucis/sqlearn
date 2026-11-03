---
type: question
tags: [multi-engine, sql, sqlglot, duckdb, transpilation]
summary: "Open question on whether sqlearn should support engines beyond DuckDB, and how to represent generated SQL to allow that."
mdindex: [type=1f5087, tags=0837e6, summary=88d806, related=da8f4c]
related: [docs/questions/multi-engine-support.md, earlier-attempts/README.md, sql_learn_test]
---
# Should sqlearn run on engines other than DuckDB?

Future work, not planned yet. The idea is to let users pick an engine
(Postgres and others) and transpile the generated SQL for it, possibly with
sqlglot.

Open points:

- Generate DuckDB SQL and transpile it, or build a sqlglot expression tree from
  the start and render it for each dialect?
- Which steps depend on DuckDB-only functions, and what replaces them on other
  engines?
- How do we test that results match across engines?

Choosing the internal SQL representation early affects how hard this is later,
so settle it before the first transformers are built.

## What the earlier attempts show

Evidence from the ten earlier attempts ([the map](earlier-attempts/README.md));
the decision is still open.

- **sqlglot was used by most attempts and cost more than it gave:** version
  pins after a release produced 292 type errors, relaxed type checking, AST
  nodes shared and corrupted, a dialect that changed NULL ordering.
  `sql_learn_test` rejected it as a validator, and the later restarts used
  plain SQL.
- **Transpiling is syntax, not meaning.** Two repositories wrote this down:
  `STDDEV` is the sample form in DuckDB and the population form in MySQL; the
  war room's portable rewrites of Median, Quantile, Corr and Std gave wrong
  answers on DuckDB when NULLs were present or values were large.
- **No attempt ever ran on a second engine.** "Dialect tests" parsed SQL,
  two of them against mocks. The only designs were native SQL per engine
  (the war room, five engines, with a rule refusing names whose meaning
  differs) and other sources reached through DuckDB `ATTACH` (April's
  federated spec).
- **DuckDB-only functions the attempts relied on:** `HISTOGRAM`,
  `USING SAMPLE` and `TABLESAMPLE … REPEATABLE`, `QUANTILE_CONT`, `MODE …
  ORDER BY`, `IGNORE NULLS`, `list_indexof`, `duckdb_keywords()`. DuckDB has no
  `erf` and no normal quantile.
- **Implication for the representation (inference):** a small representation
  of the core's own (expressions per column, a source, references to learned
  values) gives composition and quoting without sqlglot's costs, and could be
  rendered to another engine later; whether that engine's results match is a
  parity test per engine, not a translation.

---
type: question
tags: [multi-engine, duckdb, sqlglot, transpilation, dialects, sql]
summary: "Open question on whether sqlearn should support engines other than DuckDB, and how to translate or render generated SQL for them."
mdindex: [type=1f5087, tags=0f9a93, summary=104304, related=d7196c]
related: [docs/adr/0015-duckdb-expressions-no-sqlglot.md, ADR 0015, docs/questions/earlier-attempts/README.md, sql_learn_test, "April's federated spec"]
---
# Should sqlearn run on engines other than DuckDB?

Future work, not planned yet, and planned only if users ask for other engines.
[ADR 0015](../adr/0015-duckdb-expressions-no-sqlglot.md) settles the present:
steps build DuckDB expression objects, sqlearn's compositor assembles one query,
no sqlglot, DuckDB only. The compositor is where a translator or a second
renderer would plug in. The idea is to let users pick an engine (Postgres and
others) and translate the generated SQL for it.

Open points:

- Generate DuckDB SQL and transpile it, or build a sqlglot expression tree from
  the start and render it for each dialect?
- Which steps depend on DuckDB-only functions, and what replaces them on other
  engines?
- How do we test that results match across engines?

The internal representation is now chosen (ADR 0015); the points above stay
open until other engines are requested.

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

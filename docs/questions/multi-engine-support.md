---
type: question
tags: [multi-engine, sql, dialects, sqlglot, duckdb]
summary: "Open question on whether sqlearn should support engines beyond DuckDB, such as Postgres, via SQL transpilation with sqlglot."
mdindex: [type=1f5087, tags=07fb85, summary=947f3c]
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

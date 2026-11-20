---
type: adr
tags: [dependencies, runtime, packaging, duckdb, licensing]
summary: "Decision record limiting sqlearn to one runtime dependency (duckdb), with each dependency justified and permissively licensed."
related: [docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0004-apache-2-licence.md]
mdindex: [type=0fc814, tags=1c2c56, summary=176b39, related=40db02]
---
# 0005: One runtime dependency, each one justified

Status: accepted (2026-11-03, from the earlier attempt's blueprint); amended by
[ADR 0057](0057-numpy-is-a-runtime-dependency.md) (2026-11-20): numpy is a
runtime dependency too.

## Context

What `pip install sqlearn` or `conda install sqlearn` pulls in is what every
user lives with. The point of sqlearn is to work without the NumPy-based stack
([ADR 0002](0002-sql-on-duckdb-execution-engine.md)).

## Decision

- The installed package depends on `duckdb` and nothing NumPy-shaped, and on
  as little else as possible.
- Every runtime dependency is justified in writing, as a comment beside it in
  `pyproject.toml`, and is permissively licensed
  ([ADR 0004](0004-apache-2-licence.md)).
- The tools used to build, test, validate, benchmark and document the project
  are free to use anything, numpy and scikit-learn included, in dependency
  groups that are never published.

## Consequences

- Tests may compare against scikit-learn or numpy; the library may not import
  them.
- Adding a runtime dependency is a decision with a written reason, reviewed
  like an API change.

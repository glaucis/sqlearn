---
type: adr
tags: [dependencies, runtime, packaging, licensing, duckdb]
summary: "Decision record on runtime dependencies (`duckdb`, and `numpy` since ADR 0057), each justified in writing and permissively licensed; originally limited to duckdb alone."
related: [docs/adr/0057-numpy-is-a-runtime-dependency.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0004-apache-2-licence.md, ADR 0057, ADR 0061, ADR 0002, ADR 0004]
mdindex: [type=0fc814, tags=76357a, related=cb184f]
---
# 0005: Runtime dependencies, each one justified

Status: accepted (2026-11-03, from the earlier attempt's blueprint); amended by
[ADR 0057](0057-numpy-is-a-runtime-dependency.md) (2026-11-20): numpy is a
runtime dependency too. Amended by
[ADR 0061](0061-sqlearn-ships-its-own-duckdb-build.md) (2026-11-21): sqlearn's
own DuckDB build replaces `duckdb` from PyPI.

## Context

What `pip install sqlearn` or `conda install sqlearn` pulls in is what every
user lives with. The point of sqlearn is to work without the NumPy-based stack
([ADR 0002](0002-sql-on-duckdb-execution-engine.md)).

## Decision

- The installed package depends on `duckdb` and, since
  [ADR 0057](0057-numpy-is-a-runtime-dependency.md), `numpy`, and on as
  little else as possible. Nothing else NumPy-shaped (pandas, pyarrow) is a
  dependency.
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

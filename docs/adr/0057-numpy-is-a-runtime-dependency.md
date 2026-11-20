---
type: adr
tags: [dependencies, runtime, numpy, linear-algebra, packaging]
summary: "Records that numpy joins duckdb as a runtime dependency, for the small matrices steps learn from (eigenvectors, solves), which DuckDB cannot compute; amends ADR 0005."
related: [docs/adr/0005-runtime-dependencies.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/specs/library-decomposition.md]
---
# 0057: numpy is a runtime dependency

Status: accepted (2026-11-20), with the
[decomposition spec](../specs/library-decomposition.md). Chosen by Tomas on
2026-11-20. Amends [ADR 0005](0005-runtime-dependencies.md).

## Context

ADR 0005 kept the package to `duckdb` and "nothing NumPy-shaped". PCA, and
later linear and ridge regression, learn from a small matrix: the p × p
covariance or XᵀX of p columns. SQL computes the parts of that matrix, but
DuckDB has no function for its eigenvectors or for solving it.

Measured on 2026-11-20 (load average about 32, so estimates), solving a
p × p system:

| Columns | Pure Python | numpy |
|---|---|---|
| 10 | 0.07 ms | 0.09 ms |
| 50 | 1.3 ms | 1.3 ms |
| 200 | 75 ms | 2.3 ms |
| 500 | 1.75 s | 4 ms |

Pure Python is fine to about 100 columns and too slow beyond. No lighter
library is faster: numpy calls LAPACK and has no dependency of its own;
scipy, jax, torch and numba are heavier; Polars and pyarrow have no linear
algebra.

## Decision

- **numpy is a runtime dependency**, beside `duckdb`. Its licence is BSD-3,
  permissive as ADR 0004 asks. Its reason is written beside it in
  `pyproject.toml`.
- **It is required, not optional:** one code path, one set of results to
  validate.
- **What computes stays the same otherwise:** passes over the data are SQL
  in DuckDB; numpy works on what SQL hands it (ADR 0058 says how).

## Consequences

- ADR 0005's "nothing NumPy-shaped" no longer holds; its other rules do:
  every further dependency needs a written reason and a permissive licence.
- Most users already have numpy through their model library, so the
  install grows little for them.
- The library may import numpy; scikit-learn stays a test-only reference.

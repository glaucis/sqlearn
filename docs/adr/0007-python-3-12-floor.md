---
type: adr
tags: [python, versions, support-policy, packaging, test-matrix]
summary: "Sets Python 3.12 as the minimum supported version, with a test matrix of 3.12-3.14 and a four-year support policy."
mdindex: [type=0fc814, tags=9b061b, summary=5a5131]
---
# 0007: Python 3.12 as the floor

Status: accepted (decided 2026-10-01 in the earlier attempt; carried over
2026-11-03)

## Context

The supported Python versions decide who can install sqlearn and what language
features it can use.

## Decision

`requires-python = ">=3.12"`, and `.python-version` holds `3.12`, so daily
work runs on the floor. The test matrix is 3.12, 3.13 and 3.14.

Support policy:

> sqlearn supports a Python version from the day Python releases it and
> DuckDB publishes wheels for it, until four years after its release or until
> DuckDB stops publishing wheels for it, whichever comes first.

## Consequences

- Four years is what the scientific-Python projects do, though SPEC 0 says
  three; 3.12 is what the enterprise long-term-support distributions ship.
- Because daily work runs on the floor, what passes at commit time runs on
  every supported version; `just verify` runs the newer ones.
- A version joins or leaves the matrix in the `justfile` and the
  `pyproject.toml` classifiers in one commit.

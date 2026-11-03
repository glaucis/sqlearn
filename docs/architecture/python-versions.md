---
type: architecture
tags: [python, versions, support-policy, duckdb, matrix]
summary: "Defines sqlearn's Python version support policy, the floor of 3.12, and where supported versions are declared and tested."
related: [docs/adr/0007-python-3-12-floor.md, pyproject.toml, justfile, ".python-version"]
mdindex: [type=4ca303, tags=2d7385, summary=6a2b30, related=910dcd]
---
# Python versions

The support policy:

> sqlearn supports a Python version from the day Python releases it and
> DuckDB publishes wheels for it, until four years after its release or until
> DuckDB stops publishing wheels for it, whichever comes first. Today that is
> Python 3.12, 3.13 and 3.14; 3.15 joins when DuckDB publishes wheels for it.

## Why

- **Four years.** That is what the scientific-Python projects do, though SPEC 0
  says three.
- **3.12 as the floor.** It is what the enterprise long-term-support
  distributions ship ([ADR 0007](../adr/0007-python-3-12-floor.md)).
- **Daily work on the floor.** `.python-version` holds `3.12`, so `.venv` runs
  on the floor and what passes at commit time runs on every supported version.
  The matrix at `just verify` covers the newer ones.

## Where the versions are written

`requires-python = ">=3.12"` in `pyproject.toml` sets the floor. The matrix,
3.12, 3.13 and 3.14, lives in two places: the `matrix` variable of the
`justfile` and the classifiers in `pyproject.toml`. A version joins or leaves
both in one commit.

`just test-python-versions` runs the tests, the slow tier included, on each
version in an environment of its own, `.venvs/py<version>`, and `.venv` stays
on 3.12. uv fetches an interpreter it lacks on first use.

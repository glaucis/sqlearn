---
type: adr
tags: [python, packaging, uv, tooling, dependencies]
summary: "ADR 0001 records the decision to use uv for Python dependencies, virtual environments, locking, and running commands in sqlearn."
mdindex: [type=0fc814, tags=dea084, summary=b9dba2]
---
# 0001: uv for Python packaging

Status: accepted (2026-11-03)

## Context

sqlearn is a Python library. It needs one tool for dependencies, virtual
environments, locking, and running commands.

## Decision

Use uv. Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
Commands run through `uv run` (for example `uv run pytest`). Packages are added
with `uv add`, not pip.

## Consequences

- `uv.lock` is committed.
- Instructions and scripts use `uv run …`, never a bare `python` or `pip`.

---
type: adr
tags: [sqlearn, cpp-rewrite, repository-layout, python-migration, validation]
summary: "Moves the old Python sqlearn library, its tests, runners and docs into old_python/ as reference only, amending ADRs 0070 and 0053."
related: [docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/adr/0053-sqlearn-ships-no-datasets.md, docs/architecture/layout.md]
mdindex: [type=0fc814, tags=3b976a, summary=5cc881, related=6bb78c]
---
# 0073: The old Python moves to `old_python/`

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27. Amends
[ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md) and
[ADR 0053](0053-sqlearn-ships-no-datasets.md).

## Context

sqlearn is rebuilt from scratch in C++ (ADR 0070). The Python library was
frozen, and its tests and the 24 validation runners stayed active until each
group's merge deleted its part. Every real change to the C++ reran all of
them, since they load the one binary: the validation took about 47 minutes,
and nothing in the Python had changed.

## Decision

- **Everything of the old Python moves to `old_python/`** at the root, each
  tree under its old path: the library (`src/sqlearn/` but the bindings),
  its tests (`tests/src/`), the validation runners and benchmark scripts,
  `devdata/` and its tests, the examples, and the guide, lessons and API
  reference.
- **Nothing under `old_python/` is run, imported or checked.** It is
  reference only, and each piece is deleted when what replaces it lands.
- **What stays active** is the C++ engine, its bindings (`src/sqlearn/`:
  `version()`, `errors` and the engine's functions) and the tooling. The
  package's API returns as the C++ brings it.
- **The rebuild starts from scratch:** C++ where it can, Python only where
  C++ cannot. A group's tests and validation runners are written for its
  C++, not carried over, and a group merges when they pass: the old Python
  never runs, so no group is benchmarked against it.

This replaces ADR 0070's rules that a group's Python and its tests are
deleted in that group's merge and that its benchmark is not slower than
that Python, and ADR 0053's `devdata/` at the root, which
is now `old_python/devdata/`.

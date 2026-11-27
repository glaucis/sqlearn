---
type: adr
tags: [migration, port, rewrite, tests, bindings, api, architecture-decision]
summary: "Records that sqlearn is rewritten in C++ group by group rather than ported under its Python tests: the Python library is frozen and each group's Python and its tests are deleted once the C++ passes the validation and is not slower, and the sq. API may be improved freely before 1.0."
related: [docs/adr/0067-how-computation-moves-to-the-engine.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0016-validation-method.md, docs/adr/0003-scikit-learn-style-api.md, docs/specs/native-engine.md, docs/architecture/engine-inventory.md]
---
# 0070: sqlearn is rewritten in C++

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27: he is happy
to rewrite the whole library in C++, make new bindings and remove all the
Python that is not needed, and left the rules to the agent. Supersedes
[ADR 0067](0067-how-computation-moves-to-the-engine.md).

## Context

[ADR 0067](0067-how-computation-moves-to-the-engine.md) ported the library
under its Python: each piece of C++ had to pass the Python package's tests
unchanged, a test of the public API could change only with an ADR, each test
of a Python internal was rewritten before that internal was deleted, and
files saved before the port had to load after it. The Python stayed as the
contract and the reference.

The validation ([ADR 0016](0016-validation-method.md)) already judges
correctness without the Python library: it compares sqlearn with exact
values and with scikit-learn. Nothing is released and sqlearn has no users,
so no one depends on today's API, its tests or its saved files. Keeping them
fixed made the C++ copy the Python's shape and doubled the work on its tests.

## Decision

- **The whole library is rewritten in C++**, one group of the
  [inventory](../architecture/engine-inventory.md) at a time, in its order.
  A group is designed for C++, not translated line by line from the Python.
  At the end no library logic is left in Python, only the nanobind bindings
  ([ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md)) and the seam
  for users' own steps written in Python.
- **The Python library is frozen:** no new features in it, and fixes only
  where a bug blocks the work. New library areas wait for the C++.
- **A group's gate:** its C++ tests pass (the C++ test framework, the
  sanitizers and fuzzing of [ADR 0065](0065-safety-rules-for-the-cpp.md)),
  every validation runner it touches passes
  ([ADR 0016](0016-validation-method.md)), and its benchmark, on the same data
  and machine with the load recorded, is not slower than the Python it
  replaces (a difference within the run-to-run spread of two runs counts as
  not slower). Then, in the same merge, its Python is deleted with every test
  of it.
- **Tests:** behaviour inside the library is tested in C++; behaviour seen
  through `sq.` is tested in Python against the bindings. A Python test is
  kept, changed or deleted on its merits, with no ADR. Tests of a deleted
  Python internal are deleted, not rewritten.
- **The `sq.` API may be improved freely before `1.0.0`:** a name, argument or
  behaviour changes in the commit that needs it, recorded in the public API's
  snapshot (`tests/public_api.txt`), the docs and the changelog. Departing
  from scikit-learn's conventions still needs an ADR
  ([ADR 0003](0003-scikit-learn-style-api.md)).
- **Saving:** files saved before the rewrite need not load after it (nothing
  is released). `sq.load`'s security rules hold in C++: a static class lookup,
  and values reach exact arithmetic only as plain numbers. The saving group
  gets a whole-branch security review of its own.
- **`main` stays green:** a merge leaves every check passing, with the
  Python still waiting and the C++ already merged working together.
- **What stays Python:** the bindings, the seam for users' steps, and the
  development tools, none of which ship: the validation (scikit-learn is
  Python), the benchmarks, `devdata/` and the checks.
- **Measure honestly,** by HANDOFF's rules: `uptime` before and after, one
  probe per subprocess, large data written as Parquet with `COPY`, peak
  memory read twice.

## Considered

- Keeping ADR 0067: the Python tests as a fixed contract. It keeps a second
  copy of every behaviour, and its tests, alive until the end.
- Deleting the Python library first and writing the C++ from nothing: `main`
  would not work for months, and the validation could not run.

## Consequences

- Phases 2 to 4 of the native engine spec (§4) are done when each group's
  gate passes and its Python is gone, not when the old tests pass unchanged.
- Each group's spec designs its C++ and its `sq.` API, and lists the Python
  tests it deletes and the tests it adds.
- The public API's snapshot still fails on any change of a name or signature
  until the change is accepted in the same commit, so no change is silent.
- The Python test suite shrinks group by group; how the checks select it is
  redrawn once its new shape is known, not before.

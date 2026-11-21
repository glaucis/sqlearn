---
type: adr
tags: [migration, phases, tests, main-green, native-engine, architecture-decision]
summary: "Records how computation moves to the native engine: piece by piece with main green, the Python API and its tests as the contract, measured honestly, the migration before any new library area."
related: [docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0016-validation-method.md, docs/adr/0058-a-gram-step-builds-xtx-in-numpy.md, docs/specs/native-engine.md]
---
# 0067: The library is ported to C++ piece by piece

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.8, §4). Revised before
merging (2026-11-21), with the spec's revision: the whole library is ported,
not only its computation.

## Context

sqlearn's Python API has a contract already: about 3,190 tests and the
validation runners ([ADR 0016](0016-validation-method.md)). A port of the
library to C++ can be checked against that contract, as Polars' Python tests
run against its Rust.

Tomas's order of work (2026-11-21): the port comes first, planned from start
to end over sqlearn's whole current state, and done piece by piece with
`main` green. New library areas wait until it is done.

## Decision

- **The whole library is ported to C++, piece by piece, with `main` green**
  (Tomas chose this over bindings at the end, 2026-11-21). From Phase 1 the
  Python package calls the C++ for each piece already ported and today's Python
  for each piece still waiting; at the end no logic is left in Python, only the
  bindings ([ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md)). Each
  phase has its own spec, plan and branch in a worktree, and Tomas merges it;
  `just verify` passes on `main` after every merge.
- **The Python API and its tests are the contract:** the tests and the
  validation runners, run against the C++ through the bindings at every
  step. A piece is ported when its C++ version passes the same tests
  unchanged and its benchmark is not slower; only then is its Python
  deleted. A test of the public API changes only with an ADR saying why the
  behaviour changes.
- **Tests of internals** (the agent's call): 69 of the 96 test files import a
  private module, and the validation runners reach into some
  (`learned_from_gram`). The bindings keep no copies of private modules for
  them. When a piece is ported, each test of its internals is rewritten
  against the public API where the behaviour is public, or becomes a C++ test
  where it is not; the phase's spec lists them, and no ADR is needed, since
  no public behaviour changes. The gate "the same tests unchanged" applies to
  the public API's tests and the validation runners' verdicts.
- **A piece is one group of the inventory, not a module** (the agent's
  call). Inside a group's branch the code may be slower for a while, as
  Python and C++ call each other; the group merges only when its benchmark,
  run on the same data and machine with the load recorded, is not slower than
  before the group. A difference within the run-to-run spread of two runs
  counts as not slower.
- **Saving keeps its behaviour exactly:** files saved before the port load
  after it, and `sq.load`'s security rules hold in C++ (a static class
  lookup; values reach exact arithmetic only as plain numbers). The saving
  group gets a whole-branch security review of its own, as #55 and #65 did.
- **The order comes from the inventory:** what the rest depends on, and what
  the profiling shows costs most.
- **What stays Python:** in the library, only the bindings. The development
  tools stay Python too: the tests, the validation that compares sqlearn with
  scikit-learn (itself Python), the benchmarks and `devdata/`. None of them
  ship. Users' own steps stay Python too, through the seam
  [ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md) records.
- **Measure honestly,** by HANDOFF's rules: `uptime` before and after, one
  probe per subprocess, large data written as Parquet with `COPY`, peak memory
  read twice.
- **The order of work** (Tomas, 2026-11-21): the port comes before any new
  library area. From Phase 1 all of sqlearn's SQL runs in sqlearn's DuckDB
  build, and the Python package loads the C++ library's bindings; Phases 2 to
  4 port the library, and the inventory is the port's full map, module by
  module. Work that needs an engine function (p-values, normality tests)
  waits for the phase that brings it.
- **HANDOFF's three small queued fixes land before Phase 1:** the one-line
  `profile` fix, #75 and #76 (the agent's call).

## Considered

- Bindings only at the end, the C++ tested by C++ ports of the tests: a
  difference from today's answers shows up only at the end, across the whole
  library, and the tests are written twice (Tomas chose bindings from the
  start, 2026-11-21).

## Consequences

- A phase's spec lists each test of an internal that its port rewrites or
  deletes.
- Every group has a benchmark, run by the rules above.
- The inventory (Phase 0's second plan, a page of `docs/architecture/`) is
  the port's full map, module by module. It is written after this ADR, as is
  ADR 0068.

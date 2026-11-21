# 0067: How computation moves to the engine

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.8).

## Context

sqlearn's Python API has a contract already: about 3,190 tests and the
validation runners ([ADR 0016](0016-validation-method.md)). A
move of computation into the engine can be checked against that contract.

Tomas's order of work (2026-11-21): the migration comes first, planned from
start to end over sqlearn's whole current state, and done piece by piece
with `main` green. New library areas wait until it is done.

## Decision

- `main` stays green. Each phase has its own spec, plan and branch in a
  worktree, and Tomas merges it. `just verify` passes on `main` after every
  merge.
- The Python API and its tests are the contract. A piece moves when its C++
  version passes the same tests unchanged and its benchmark is not slower.
  Only then is its Python computation deleted.
- A test of the public API changes only with an ADR saying why the behaviour
  changes.
- A test of an internal that the move deletes (the numpy Gram batches, say)
  goes with it, and the phase's spec names it.
- Pieces move by evidence, then by the vision: profile where time and
  memory go before choosing what moves next.
- Measure honestly, by HANDOFF's rules: `uptime` before and after, one probe
  per subprocess, large data written as Parquet with `COPY`, peak memory read
  twice.
- The order of work: the migration comes first, over sqlearn's whole current
  state, piece by piece, with `main` green. From Phase 1 all of sqlearn's
  SQL runs in sqlearn's DuckDB build. Phases 2 and 3 move what Python and
  numpy still compute. Python stays the API.
- HANDOFF's three small queued fixes land before Phase 1: the one-line
  `profile` fix, #75 and #76. This is the agent's call.
- New library areas wait until the migration is done. Work that needs an
  engine function (p-values, normality tests) waits for the phase that
  brings it.

## Consequences

- A phase's spec names each test of an internal that its move deletes.
- Every move has a benchmark, run by the rules above.
- The inventory (Phase 0's second plan, a page of `docs/architecture/`) is
  the migration's full map, module by module. It is written after this ADR,
  as is ADR 0068.

---
type: adr
tags: [build-system, cmake, bazel, test-selection, decision]
summary: "Decides the sqlearn engine stays on CMake under just with its own test selection, keeping Bazel for later and listing the signs to look again."
related: [docs/questions/archived/bazel-prototype.md, docs/adr/0008-just-task-runner.md, docs/architecture/testing.md, validation/_checks.py, validation/_ctest.py, HANDOFF.md]
mdindex: [type=0fc814, tags=0bcabe, summary=e41566, related=3aec66]
---
# 0080: The engine stays on CMake for now

Status: accepted (2026-11-28). Decided by Tomas on 2026-11-28, after the
[Bazel prototype](../questions/archived/bazel-prototype.md).

## Context

Tomas asked on 2026-11-27 why sqlearn does not adopt Bazel from the start.
His aim for the checks, in his words: run linting, formatting, tests,
validation (and later profiling) only when it matters and when it is
needed. That means never on what already passed, never when the code has not
changed, and always when something it uses has changed. Speed is not the
criterion; accuracy is.

A prototype on the unmerged branch `claude/bazel-prototype-266e9b` built the
engine's groups, their tests, DuckDB's module and the wheel with Bazel, and
judged it item by item against today's selection
([report](../questions/archived/bazel-prototype.md)). Bazel selected the C++
tests as well as today, or more finely. It caught some undeclared reads, which
today nothing does. But only the C++ tests were tried: every other check would
need Bazel rules written. The Python tests depend on the one binary under both.
DuckDB stays a CMake build inside Bazel, and the library Bazel built was not the
same as CMake's (the report lists each difference). Today's selection already
covers every check. The one result that looked like a missed rerun was diagnosed
and is not one.

## Decision

- **The engine stays on CMake under `just`**, with sqlearn's own selection
  (`validation/_checks.py`, `validation/_ctest.py`, `just done`), as
  [ADR 0008](0008-just-task-runner.md) and
  [testing](../architecture/testing.md) describe.
- **The selection is strengthened with the tools already in use**, in
  `HANDOFF.md`'s order: the groups' test programs link static libraries, so
  a change reruns only the programs that use it; a check that each group's
  declared dependencies match the headers it includes; `just affected`, which
  says what a change reruns and why; and a full run at a set cadence,
  compared with what the selection chose.
- **Bazel is considered again when one of these happens:**
  - a full run finds a rerun the selection missed;
  - the selection's own code becomes a burden to keep;
  - Phase 4, which writes most of the engine's groups, is about to start.
    Moving is cheapest before it, so this is a check-in either way.

## Consequences

- No new build system and no new tool; Bazel's files stay on the
  prototype's branch, which is not merged.
- Each new kind of check still needs its own selection in
  `validation/_checks.py`; each new group is one entry in the existing one.
- An undeclared input stays uncaught until a check for it exists.
- The prototype's report is in `docs/questions/archived/`, answered by
  this record, as the evidence behind it.

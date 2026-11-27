---
type: adr
tags: [just, task-runner, build, tooling, cmake]
summary: "ADR accepting just as the single root task runner for formatting, checks, tests and docs, amended by the Phase 1 spec for C++ builds."
mdindex: [type=0fc814, tags=085efd, summary=dab5b2, related=3d2e17]
related: [docs/specs/native-engine-phase-1.md, docs/specs/foundation.md]
---
# 0008: just as the task runner

Status: accepted (decided 2026-10-01 in the earlier attempt; carried over
2026-11-03). Amended by the
[Phase 1 spec](../specs/native-engine-phase-1.md) (2026-11-21): `just`
stays the one entry point for the C++ too, and CMake, with Ninja, ccache and
presets, builds it under `just` (§3.2); `just done` runs each check on what
changed when work is done, and `just verify` runs everything in full, the
release tier (§3.1).

## Context

Formatting, checks, tests and the docs build each run several tools. People
and agents need one name for each job, the same on every machine.

## Decision

A `justfile` at the root holds every recipe. Recipes are small, one tool each,
and composites stack them: `check` on every commit, `verify` at every review,
merge and release. Recipes are added as the work needs them. The starting set
is in [specs/foundation.md](../specs/foundation.md).

## Consequences

- Instructions and agents run `just <recipe>`, not the tools directly.
- What runs on every commit changes in the `justfile`, never in the git hook.

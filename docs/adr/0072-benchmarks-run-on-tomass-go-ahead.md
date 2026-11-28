---
type: adr
tags: [benchmarks, measurement, process, checks, architecture-decision]
summary: "Records that benchmarks never run inside a check: an agent asks Tomas first, naming each one with its time and weight, runs them in small batches on his go-ahead, proposes only those whose code changed, and records the load; loaded pages are rerun when their group is rewritten."
related: [docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/benchmarks/index.md, docs/agents/working-with-tomas.md, docs/architecture/testing.md]
---
# 0072: Benchmarks run on Tomas's go-ahead

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27. Amended by
[ADR 0073](0073-the-old-python-moves-to-old-python.md): no group is benchmarked
against the old Python, and the page scripts are in `old_python/`. Its "small
batches" rule is amended for the benchmark and profiling queue by
[ADR 0081](0081-one-go-ahead-runs-the-queue-on-an-idle-machine.md).

## Context

A benchmark times code, and anything else running on the machine changes
its numbers. Tomas's machine runs his other projects at the same time.
Several pages were measured under load (`generators-on-many-threads.md`,
`gram-batches.md`, both `explore-*.md`, `engine-profile.md`: load averages up
to 145 on 8 cores) and say they are estimates.
[ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md) gates each rewritten group
on a benchmark against the Python it replaces, timed beside it.

## Decision

- **No check runs a benchmark:** none is part of `just done`, `just test` or
  `just verify`. `just bench-engine` and the benchmark pages' scripts run
  only by hand.
- **An agent asks Tomas first, every time:** which benchmark, about how long
  it takes and how heavy it is (cores, memory, disk). It runs only on his
  go-ahead, which covers that batch alone.
- **Small batches:** one page or one group at a time, never all of them;
  Tomas says when the next may run.
- **Incremental:** a benchmark records the code it measured, as the tests
  and the validation do, and only one whose code changed is proposed again.
  Until that selection is built (the coverage-based selection's spec), the
  agent proposes only the benchmarks the change in hand touches.
- **The load is recorded** with every run (`uptime` before and after, as
  HANDOFF's rules have it), so a page says what else was running.
- **The pages measured under load are rerun when their group is
  rewritten**, each on this rule: `gram-batches.md` at the start of Phase 2,
  `engine-profile.md` before Phase 4's order is fixed, the `explore-*` pages
  with the explore group. `generators-on-many-threads.md` measures
  `devdata/`, which stays Python, and waits for #46.

## Considered

- Rerunning every loaded page now: hours of the machine, for Python that is
  about to be deleted.
- Leaving the pages as they are: Phase 2 would compare against numbers
  measured under load.

## Consequences

- A benchmark's numbers come from a machine Tomas has cleared, and say its
  load.
- A group's gate (ADR 0070) waits for his go-ahead to time the old Python
  beside the new C++.
- The coverage-based selection's spec covers benchmarks as a separate kind,
  selected by the code each measured, and still run only on his go-ahead.

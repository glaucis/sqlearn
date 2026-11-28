---
type: adr
tags: [benchmarks, profiling, queue, process, architecture-decision]
summary: "Amends ADR 0072's small-batches rule for the benchmark and profiling queue only: one go-ahead from Tomas covers the whole queue, which measures only on an idle machine and stops when the load rises."
related: [docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md, docs/specs/benchmark-queue.md]
---
# 0081: One go-ahead runs the queue on an idle machine

Status: accepted (2026-11-28). Decided by Tomas on 2026-11-28. Amends
[ADR 0072](0072-benchmarks-run-on-tomass-go-ahead.md): its "small batches"
rule is replaced for the benchmark and profiling queue only.

## Context

[ADR 0072](0072-benchmarks-run-on-tomass-go-ahead.md) has an agent run
benchmarks in small batches, one page or one group at a time, with Tomas
saying when the next may run. It did so because anything else running on the
machine changes a benchmark's numbers.

The [benchmark and profiling queue](../specs/benchmark-queue.md) runs every
benchmark and profile that is due, with one command. It measures only while
the machine is idle, and stops when the load rises.

## Decision

- **One go-ahead covers the queue:** Tomas's go-ahead for `just bench-queue`
  covers everything due in that run, not one page or one group.
- **The queue waits for idle and stops on load:** it measures only on an idle
  machine and stops when the load rises, saying so in its records.
- **The rest of 0072 holds:** no check runs a benchmark; an agent asks first,
  naming what is due, its last times, and that the queue waits for idle; the
  load is recorded with every run.
- **Only the queue is changed:** a benchmark run by hand outside the queue
  still goes in small batches, as 0072 has it.

## Considered

- One item per go-ahead: it asks Tomas's time for every item, though the
  queue's own idle check already protects the numbers.
- Running regardless of load: it gives the numbers 0072's context
  describes, measured under load.

## Consequences

- Tomas answers once for the whole queue; the machine, not his go-ahead per
  item, decides when each measurement starts.
- A run the load interrupted is recorded as interrupted, never as a clean
  number.

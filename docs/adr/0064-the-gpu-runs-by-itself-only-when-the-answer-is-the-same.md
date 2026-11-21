---
type: adr
tags: [gpu, metal, apple-silicon, opt-in, float64, architecture-decision]
summary: "Records that on Apple silicon a kernel runs on the GPU by itself only when its answer is bit for bit the CPU's and the job is above the kernel's measured size, that other kernels stay on the CPU, and that this amends ADR 0046."
related: [docs/adr/0016-validation-method.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0063-the-engines-compute-libraries.md, docs/specs/native-engine.md]
---
# 0064: The GPU runs by itself only when the answer is the same

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.5).
Amends [ADR 0046](0046-sqlearn-warns-the-user-chooses.md).

## Context

[ADR 0046](0046-sqlearn-warns-the-user-chooses.md) says sqlearn never
changes on its own what the user asked for, "even when the result would be
identical". Read as it stands, the GPU would be opt-in for every kernel.

Apple GPUs have no float64 at all (Metal Shading Language 4.1, §2.1; see
[ADR 0063](0063-the-engines-compute-libraries.md)). So a GPU kernel can
give the CPU's answer only where float64 is not needed.

Kernels that can meet that: counts, histograms, sorting and ranking
(float64 keys sorted by their bits), fixed-point sums and means, naive
Bayes fitting, boosting histograms. Kernels that cannot: `eigh`, solve,
`exp` and `log`, and k-means distances in floating point.

Weighed and left out:

- **Opt-in for everything** (ADR 0046 as it stands). Most users would never
  get the speed.
- **The GPU always.** Answers would change with the machine.

## Decision

- **On Apple silicon, a kernel runs on the GPU by itself when its answer is
  bit for bit the CPU's and the job is above the kernel's measured size.**
  Otherwise it runs on the CPU.
- **The kernels that cannot meet the rule stay on the CPU.** A float32 GPU
  version runs only when the user asks for it (`sq.set_config(...)`), with
  bounds of its own.
- **The user can see which device ran, and force one.**
- **The tests require exact equality** between a kernel's CPU and GPU
  versions.
- **Each kernel's size threshold comes from benchmarks**
  ([#77](https://github.com/glaucis/sqlearn/issues/77)).
- **This amends ADR 0046.** Choosing the device when the answer is identical
  is not "changing the method". Anything that changes the answer still needs
  the user's choice.

## Consequences

- So every automatic GPU kernel has a CPU version to compare against, and a
  test that the two agree exactly.
- A setting shows which device ran and forces one.
- #77 sets the thresholds.
- A float32 GPU version needs the user's choice and its own bounds
  ([ADR 0016](0016-validation-method.md)).

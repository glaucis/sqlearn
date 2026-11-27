---
type: adr
tags: [engine, floating-point, fma, reproducibility, gpu, metal, architecture-decision]
summary: "Records that sqlearn's C++ is compiled with FMA contraction off, that a kernel fuses a multiply and an add only by calling std::fma (fma in Metal), validated, and that contraction may be turned on for one target or kernel when its benchmark shows a gain and the validation passes."
related: [docs/adr/0063-the-engines-compute-libraries.md, docs/adr/0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md, docs/adr/0043-repeatable-within-rounding.md, docs/adr/0062-apple-silicon-first.md, docs/specs/native-engine-phase-1.md]
---
# 0071: Fused multiply-add only on purpose

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27, on the
agent's proposal in the [Phase 1 spec](../specs/native-engine-phase-1.md)
(§3.9). Sits beside [ADR 0063](0063-the-engines-compute-libraries.md).

## Context

IEEE 754 rounds each operation (`+`, `−`, `×`, `÷`, `√` and the fused
multiply-add, FMA) the same way on every processor, so the same operations
in the same order give the same bits everywhere. C and C++ let a compiler
contract `a * b + c` into one FMA, which rounds once instead of twice, and
each compiler chooses its own default: clang fuses within one expression,
GCC in its GNU modes may fuse across statements after moving code, MSVC
generally does not, and a target without an FMA instruction fuses nothing.
The same source then gives different last digits on different compilers and
processors, chosen by none of them on purpose.

[ADR 0064](0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)
lets a kernel run on the GPU by itself only when its answer is the CPU's bit
for bit, which needs both sides to do the same operations. The Metal
compiler turns fast maths on by default, and
[ADR 0063](0063-the-engines-compute-libraries.md) forbids fast maths.

Most of sqlearn's time goes to DuckDB and to Accelerate or OpenBLAS, which
use FMA inside whatever sqlearn's flags say; their results already differ in
the last digits between platforms, which the validation's bounds
([ADR 0043](0043-repeatable-within-rounding.md)) allow. Contraction would
change only sqlearn's own C++.

## Decision

- **sqlearn's C++ is compiled with contraction off** (`-ffp-contract=off`,
  `SQ_FP_OPTIONS` in `engine/cmake/warnings.cmake`), on every compiler and
  platform.
- **A kernel fuses only on purpose:** it calls `std::fma(a, b, c)` where a
  multiply-add should round once, and the validation checks that kernel
  against exact values ([ADR 0016](0016-validation-method.md)).
- **GPU kernels fuse the same way:** Metal's `fma()` where the CPU kernel
  calls `std::fma`, so the two do the same operations; Metal's fast maths is
  off ([ADR 0063](0063-the-engines-compute-libraries.md)).
- **Contraction may be turned on later for one target or one kernel**, never
  silently: when its benchmark, on the same data and machine with the load
  recorded, shows a gain, and the validation passes. The flag's change is
  written beside it with its reason and the benchmark.
- **x86_64's safe build:** where the processor has no FMA instruction,
  `std::fma` runs in software and is slow. A kernel calling it in a loop
  takes the run-time dispatch of
  [ADR 0062](0062-apple-silicon-first.md) (an AVX2 path with FMA) or
  avoids it on the baseline path; its benchmark on that platform decides.

## Considered

- Letting each compiler contract by its default: perhaps a little faster
  where a loop waits on arithmetic rather than memory, but different bits per
  compiler and processor, chosen invisibly, against ADR 0064's rule.
- `-ffp-contract=fast` everywhere: the same, across statements too.

## Consequences

- The same source gives the same bits from every compiler for sqlearn's own
  arithmetic. Library functions (`exp`, `sin`) and the BLAS libraries still
  differ in the last digits by platform, within ADR 0043's bounds.
- A kernel that wants FMA's speed or accuracy writes `std::fma` where it
  counts, and its benchmark shows the gain.
- A separate DuckDB extension of the user's own is its own build and chooses
  its own flags; sqlearn's extension under `engine/` follows this ADR.

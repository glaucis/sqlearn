---
type: adr
tags: [compute-libraries, accelerate, openblas, metal, float64, gpu, architecture-decision]
summary: "Records that float64 runs on the CPU (Accelerate on macOS, OpenBLAS elsewhere), that MLX is left out, that GPU kernels are written in Metal and compiled ahead of time, and that -ffast-math is never used."
related: [docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/adr/0062-apple-silicon-first.md, docs/specs/native-engine.md, docs/questions/engine-compute-libraries.md]
---
# 0063: The engine's compute libraries: Accelerate, OpenBLAS and Metal

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.4). Revised before merging
(2026-11-21), with the spec's revision: Mojo tried beside Metal.

## Context

The engine needs matrix and special-function routines. Results are checked
in float64. Metal has no float64, so nothing on Apple's GPU has it. The
research is in [the compute libraries
question](../questions/engine-compute-libraries.md).

Measured on the M3:

- XᵀX of 400,000 × 200 took 52 ms in Accelerate's float64, and 19 ms in
  its float32. MLX's GPU took 36 ms in float32.
- In float32, the noise-level eigenvalues of XᵀX were wrong by 10 to 44 times
  their own size at 200 columns.
- MLX's float64 runs on the CPU only. There its `exp` and `erf` are
  computed in float32: `exp(1.0)` was 1.86e8 ULPs off and `exp(100)` gave
  infinity.
- MLX's kernels weigh 214 MB.
- Without a binary archive, a first kernel took 44 ms and later uses 0.5
  ms (a 200 × 200 matrix product in MLX).
- MLX's GPU won once: at 65,536 × 200 in float32, 2.9 ms against
  Accelerate's 3.5 ms.

Weighed and left out:

- **MLX.** See the numbers above.
- **Cross-platform GPU layers** (WebGPU, Vulkan, SYCL, Halide, IREE):
  float32 in practice, no linear algebra, and some compile at run time.
- **Eigen.** Its licence is MPL-2.0.
- **JAX and XLA.** They compile at the first call, and they are Python.

## Decision

- **float64 runs on the CPU, everywhere.** On macOS: Accelerate's BLAS,
  LAPACK (3.12, with 64-bit indices) and vForce (`exp`, `log`, `expm1`,
  `log1p`, `pow` over arrays), single-threaded inside each DuckDB thread
  (`BLASSetThreading`, macOS 15+). Elsewhere: OpenBLAS (BSD-3).
- **Special functions** (`erf`, the incomplete gamma and beta functions):
  the C library, Boost.Math (BSL-1.0, header-only, tested first), or our
  own, each validated against mpmath. Never Numerical Recipes' code, whose
  licence forbids it.
- **No MLX.**
- **GPU kernels are written in Metal**, through metal-cpp (Apache-2.0), and
  compiled ahead of time into a `.metallib` (Xcode's Metal toolchain on the
  build machine), with binary archives for the chips we know, so nothing
  compiles at start. Kernels use only what every Apple GPU has, from the
  M1; per-chip variants or tuning are chosen at run time, each where a
  measurement shows it pays.
- **Mojo is tried beside Metal** when the GPU kernels are benchmarked
  (Phase 6, #77; Tomas, 2026-11-21). Mojo 1.0 (August 2026) is open source
  under Apache-2.0 with LLVM exceptions, compiler included, and compiles GPU
  functions for Apple silicon to the same intermediate form as Metal (AIR).
  It also compiles the same kernel for NVIDIA and AMD GPUs, so one source
  could serve every GPU sqlearn supports later, with no second and third
  version to maintain (Tomas, 2026-11-21); NVIDIA's GPUs have float64, which
  Apple's lack. **If Mojo matches Metal on Apple silicon, Mojo becomes the
  language of sqlearn's GPU kernels,** and Metal stays only where Mojo falls
  short. Phase 6 decides it, by testing, against these conditions, all
  measured:
  - as fast as the Metal version on Apple silicon, within the run-to-run
    spread;
  - answers bit for bit the CPU's
    ([ADR 0064](0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)),
    on each GPU it runs on;
  - compiled ahead of time, with nothing compiled at start and no runtime
    added beyond what the kernels need;
  - callable from the C++ library through a plain C interface;
  - everything that ships under it permissive
    ([ADR 0066](0066-permissive-licences-never-copyleft.md)).

  Otherwise C++ and Metal stay the native languages. Either way the GPU
  stays Apple's only until another vendor's can be tested
  ([ADR 0062](0062-apple-silicon-first.md)).
- **No `-ffast-math`** anywhere, since it swaps in less accurate routines.
  Metal kernels compile in safe math mode (Metal's default is fast).

## Consequences

- MLX is not a dependency.
- The Macs that build sqlearn need Xcode's Metal toolchain.
- Validation results are kept per platform.
- #77 sets each kernel's size threshold, from measurements.

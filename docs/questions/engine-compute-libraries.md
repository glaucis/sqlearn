---
type: question
tags: [compute-libraries, float64, metal, mlx, cpu-engine]
summary: "Asks which compute libraries sqlearn's C++ engine should use, weighing Apple Accelerate, Metal, MLX and other GPU options for float64 validation."
related: [docs/adr/0043-repeatable-within-rounding.md, docs/adr/0016-validation-method.md]
mdindex: [type=1f5087, tags=dca05e, summary=0c5e38]
---
# Which compute libraries does sqlearn's engine use?

Answered by [ADR 0063](../adr/0063-the-engines-compute-libraries.md) on
2026-11-21, and kept as the research behind it.

sqlearn is building a C++ engine compiled into its own DuckDB 2.0 build.
Apple silicon comes first and should use the whole chip; Linux and Windows
get a safe CPU build; other GPUs come only when asked for and testable.
Results are validated in float64 to a few ULPs ([ADR 0043][adr-0043]). This
page merges three research reports and the main session's probes, all of
2026-11-21. *Measured* marks a probe on Tomas's M3, timings with their load
average; *estimate*, arithmetic nobody has run; other figures are sourced.

## Summary

- **Metal has no float64** ([MSL] §2.1), so nothing on Apple's GPU or Neural
  Engine has it: not MLX, MPS, nor any portable layer over Metal.
- **The M3's CPU beat its GPU even in float32**: XᵀX of 400,000 × 200 took
  19 ms in Accelerate, 36 ms through MLX on the GPU (measured, load 4); one
  probe went the other way. Accelerate's use of matrix units is inferred.
- **float32 is too coarse anyway**: on the GPU it put XᵀX's noise-level
  eigenvalues off by 10 to 1,800 times their own size (measured, load 4).
- **MLX's float64 is CPU-only**, runs the same Accelerate routines, and
  computes `exp` and `erf` in float32; its kernel file is 214 MB.
- **Nothing cross-platform gives float64 on Apple GPUs**, and none is known
  to beat MLX there, though none was benchmarked against it.
- **Fast GPU float64 is a data-centre feature**: 1:2 of float32 on H100 and
  MI300X, 1:64 on GeForce, 1:32 on RDNA 3, emulated on Intel Arc A.
- **The CPU is the one float64 path everywhere**: BLAS and LAPACK from
  DuckDB's threads, Accelerate on macOS, OpenBLAS (BSD-3-Clause) elsewhere.
- **A GPU kernel matches the CPU bit for bit only if both are exact**: integer
  or fixed-point sums, counts, histograms and XᵀX; never eigh, solve or `exp`.
- **Proposal, open, awaiting Tomas:** leave MLX out; write sqlearn's few GPU
  kernels directly in Metal through metal-cpp, precompiled (a `.metallib`
  plus binary archives); keep each on the CPU below a measured size. The
  cross-platform report would rather keep MLX as a later float32 backend.

## Apple silicon

### CPU: Accelerate

- **BLAS and LAPACK, CPU only** ([accel]): "inline with reference version
  3.9.1" since macOS 13.3, with "a new ILP64 interface" under
  `ACCELERATE_NEW_LAPACK` and `ACCELERATE_LAPACK_ILP64` ([rn133],
  [accel-lapack]); `ilaver` gives 3.12.0 (measured). CLAPACK is deprecated,
  BNNS stops at float32, and vForce has no `erf` (SDK headers).
- **Matrix units.** The M1–M3's AMX is undocumented. The M4 is "the first to
  support" Arm's Scalable Matrix Extension, with 2,009 FP32 and 503 FP64
  GFLOPS per P-core from two shared units ([m4-matrix]); LLVM gives the M4
  and M5 its float64 form ([llvm-m4]); this M3 lacks it (measured).
  Inference: Accelerate's sgemm ran at 1.35 TFLOP/s (measured, load 9–11),
  above NEON's peak on a whole M4 (656 GFLOP/s, [m4-matrix]).
- **Threads.** `BLASSetThreading` (macOS 15+) makes BLAS single-threaded "per
  thread" (SDK `thread_api.h` L26, [accel-blas]); no thread-safety statement
  was found. Both reports plan one single-threaded call per DuckDB thread and
  a merge of partial XᵀX; the cross-platform one names `dsyrk` on 2,048-row
  chunks and `dsyevd`, `dpotrf`, `dposv`, `dgesv` for the p × p work. Up to
  8 threads gained at most 1.5× (measured, load 9–11).

### GPU: Metal

"Metal does not support the double, long long, unsigned long long, and long
double data types" ([MSL] §2.1). What it has:

| From             | What a kernel can use                                                             | Source                       |
| ---------------- | --------------------------------------------------------------------------------- | ---------------------------- |
| Metal 2.2        | 64-bit `long`, `ulong` (`+`, `×`, `mulhi`); "64-bit integer math" from Apple3     | [MSL] Table 2.1, §6.4; [FST] |
| Apple7 (M1)      | `simdgroup_matrix`: 8×8 `half`, `bfloat` (Metal 3.1) or `float`, one type for all | [MSL] §2.4, §6.8; [FST] p. 4 |
| Apple8 (M2)      | 64-bit atomic `min` and `max` under macOS                                         | [FST] pp. 4–5                |
| Apple9 (M3, M4)  | every 64-bit atomic by the [FST]; only `min` and `max` by [MSL] §6.16.4.6         | [FST], [MSL]                 |
| M5, M5 Ultra, M6 | a neural accelerator in each GPU core, "over 4x peak GPU compute" against the M4  | [wwdc330], [m5], [m6]        |
| Apple11 (M6)     | float32 denormals                                                                 | [FST] p. 6                   |

- **Floating point.** Fast math is the default (no NaNs or infinities,
  reassociation) until `-fmetal-math-mode=safe` and `-ffp-contract=off`
  ([MSL] §1.6.3). `+ − × ÷ fma sqrt` round correctly, but denormals "may be
  flushed to zero", round-to-even or towards zero "may be supported", and
  `exp`, `log` are within 4 ulp (§8.1–8.4).
- **Compiling ahead.** `xcrun -sdk macosx metal` builds a `.metallib`
  ([mtl-precompile]) with Xcode's optional Metal Toolchain ([xcode-metal]);
  the Command Line Tools lack it (`xcrun -f metal` fails here). Its Metal IR
  is compiled for the GPU when a pipeline is made; a binary archive skips
  that, a miss "falls back on the compilation of Metal IR at runtime", and OS
  updates may invalidate it ([mtl-archive]). A library can be embedded and
  loaded with `newLibrary(dispatch_data_t)` ([metal-cpp]
  `Metal/MTLDevice.hpp` L466–469).
- **metal-cpp** (Apache-2.0, tag of 2026-09-22) is header-only C++17 for
  Foundation, Metal, MetalFX and QuartzCore, without MPS or Core ML; each
  calling thread needs an autorelease pool (`README.md` L55–69). Zero-copy
  buffers need page-aligned memory ([mtl-nocopy]); DuckDB's vectors are not.
- **M5 accelerators** are reached through Metal 4 tensors, which stop at
  Float32 ([metal-cpp] `Metal/MTLTensor.hpp` L41–51, [FST] p. 17), and
  `matmul2d` ([MPP]): float, half, bfloat, int8, uint8, int4, int2, fp8 or
  fp4 operands, summed at most in float (int8 in int), with overflow, order
  and rounding unstated; `relaxed_precision` "allows the operation to
  truncate the mantissa" ([MSL] §7.2.1, Table 7.3, p. 354). Apple gives no
  rate per type, only GEMMs "up to 4 to 8 times faster, depending on
  precision", and older GPUs run such code as shaders ([talk]); Modular's
  int8 kernel reached 96–99 Tops/s on an unnamed M5-family GPU ([modular]).
- **Cost.** MLX's example kernel, `axpby`, takes 525 lines, 47 of them MSL
  ([mlx] `examples/cmake_extension`). MLX's Metal back end has about 20,000
  lines of C++ and 40,000 of MSL; its GEMM alone is a 3,180-line dispatcher
  plus about 6,000 kernel lines, retuned per chip ([mlx-rel]).

### MLX

Apple's array framework (MIT, [mlx]: a C++ core with CPU, Metal and CUDA back
ends) was weighed as the short way onto the GPU, and falls short here:

- **float64 only on the CPU**: "Arrays with type float64 only work with CPU
  operations" ([mlx-dt]); any GPU node with a float64 input or output throws,
  CUDA included (`mlx/array.cpp` L19–40). Emulation was declined as "going to
  be quite slow" ([mlx-1905]).
- **Its CPU float64 is Accelerate's**: `cblas_dgemm`
  (`mlx/backend/cpu/gemms/cblas.cpp` L32–73) and LAPACK (`CMakeLists.txt`
  L271–283), the rest MLX's own SIMD code on one thread per stream
  (`mlx/scheduler.cpp` L42–80). There `exp` is cast to float32 and clamped at
  ±88, and `erf` is a float32 fit (`mlx/backend/cpu/simd/math.h` L27–56,
  L154–166).
- **No GPU linear algebra** beyond matmul: cholesky, eigh, qr, svd, inv, lu
  and solve are refused, but for cholesky on CUDA (`mlx/linalg.cpp` L14–33,
  L352). On the M5, matmuls use the accelerators (`backend/metal/device.cpp`
  L978–996) with `relaxed_precision` unless `MLX_ENABLE_TF32=0`, erring
  "several orders of magnitude" beyond float32 (`kernels/steel/gemm/nax.h`
  L401–408, `docs/src/usage/precision.rst`).
- **Size and run-time code.** All kernels ship in one `mlx.metallib`, which
  must be a file on disk (`device.cpp` L195–260); a JIT build costs "a few
  hundred millisecond to a few seconds" at cold start, and C++ users build
  MLX from source (`docs/src/install.rst`). `compile` emits Metal source
  (`device.cpp` L680–694) or C++ that it builds with `g++` in `$TMPDIR`,
  silently skipped without it (`backend/cpu/jit_compiler.cpp` L196–278).
  After twelve releases in 2026, MLX is still 0.x ([mlx-rel]).

### MPS, MPSGraph and the Neural Engine

`MPSDataType` has no float64 ([mps-dt]; SDK `MPSCoreTypes.h` L246–307); a
forged one crashed MPSGraph (measured), and PyTorch 2.15's MPS refuses it
([torch-mps]). MPSMatrix has multiply, LU, Cholesky and solves, float32 at
most, no eigen or SVD; MPSGraph adds only `inverseOfTensor` and `bandPart`
(SDK `MPSMatrix*.h`, `MPSGraphLinearAlgebraOps.h`); graphs serialise to
`.mpsgraphpackage`. Both are Objective-C or Swift, outside metal-cpp, so C++
needs `.mm` shims. The Neural Engine runs float16: "Only the NE is barred as
a compute unit when a model is typed with float 32 precision" ([ct-typed]);
no C++ API was found.

## Other systems and GPUs

| Library                    | Release | Backends                                             | GPU float64           | Kernels compiled     | Licence                    | Linear algebra   |
| -------------------------- | ------- | ---------------------------------------------------- | --------------------- | -------------------- | -------------------------- | ---------------- |
| Dawn (WebGPU) [dawn]       | 2026-11 | Metal, Vulkan, D3D12                                 | none                  | at run time          | BSD-3-Clause               | none             |
| wgpu-native (WebGPU)       | 2026-06 | Metal, Vulkan, D3D12                                 | Vulkan only           | at run time          | MIT or Apache-2.0          | none             |
| Kompute (Vulkan) [kompute] | 2024-01 | Vulkan; Metal through MoltenVK                       | per device            | SPIR-V ahead         | Apache-2.0                 | none             |
| AdaptiveCpp (SYCL) [acpp]  | 2025-11 | CUDA, HIP, Level Zero, OpenCL, CPU; Metal unreleased | not on Metal          | at run time or ahead | BSD-2-Clause               | through oneMath  |
| DPC++ (SYCL)               | 2026-10 | CUDA, HIP, Level Zero, OpenCL, CPU                   | optional              | ahead or at run time | Apache-2.0, LLVM exception | through oneMath  |
| Kokkos                     | 2026-11 | CUDA, HIP, SYCL, OpenACC, CPU                        | CUDA, HIP             | ahead                | Apache-2.0, LLVM exception | vendor libraries |
| Halide                     | 2026-10 | Metal, CUDA, Vulkan, D3D12, OpenCL, WebGPU, CPU      | per target, not Metal | ahead; Metal as MSL  | MIT                        | a BLAS example   |
| IREE                       | 2026-11 | Metal, CUDA, HIP, Vulkan, CPU; WebGPU experimental   | demoted to float32    | ahead                | Apache-2.0, LLVM exception | matmul           |
| ArrayFire                  | 2026-11 | CUDA, oneAPI, OpenCL, CPU; Metal, HIP on branches    | per device            | at run time, cached  | BSD-3-Clause; FFTW is GPL  | no eigensolver   |
| ggml                       | 2026-11 | Metal, CUDA, HIP, Vulkan, SYCL, OpenCL, WebGPU, CPU  | none                  | at run time or ahead | MIT                        | matmul           |
| MLX                        | 2026-10 | Metal, CUDA, CPU                                     | none                  | ahead, some JIT      | MIT; CUDA libraries: EULA  | on the CPU only  |
| OpenBLAS [openblas]        | 2026-07 | CPU                                                  | (CPU float64)         | ahead                | BSD-3-Clause               | BLAS, LAPACK     |

- **WebGPU** has no run-time 64-bit types ([wgsl] §6.2.1, §6.2.5) and no
  pipeline cache ([webgpu] §2.2.4, §3.6.1.1); wgpu-native's f64, Vulkan-only,
  is "frequently between 16 and 64 _times_ slower" ([wgpu-native];
  `wgpu-types/src/features.rs` L1061, L1163 in [wgpu]).
- **Vulkan on Apple**: neither MoltenVK, which translates SPIR-V to MSL at
  run time ([moltenvk] `MVKDevice.mm` L2759), nor KosmicKrisp, conformant to
  Vulkan 1.4 and needing macOS 26 ([kk-news], [kk-docs];
  `src/kosmickrisp/vulkan/kk_physical_device.c` L253 in [mesa]), sets
  `shaderFloat64` ([vk-features]).
- **SYCL** makes `aspect::fp64` optional ([sycl]). AdaptiveCpp's Metal
  backend ([acpp-1961]) is unreleased and macOS 26 only, and "`double` is
  not supported" ([acpp-metal]); DPC++ is documented for Linux and Windows
  only ([dpcpp]); oneMath, their linear algebra, has no Apple backend
  ([onemath]).
- **IREE** comes closest to one float32 library for Apple, NVIDIA, AMD and
  Intel, with modules compiled ahead and a C runtime "as low as 30KB on
  embedded systems" ([iree]); but it sets `demoteF64ToF32 = true`
  (`compiler/src/iree/compiler/Pipelines/Options.h` L84), its Metal guide
  reads "Documentation coming soon!", and no Cholesky or triangular solve was
  found. Halide's Metal code emits `double`, which MSL forbids ([halide]
  `src/CodeGen_Metal_Dev.cpp` L173). Kokkos has no Metal ([kokkos]) and no
  eigensolver ([kokkos-kernels]). ggml's `GGML_TYPE_F64` is a storage tag
  (`src/ggml.c` L664) its CPU ops abort on (`src/ggml-cpu/ops.cpp` L6066,
  [ggml]), and its linear algebra stops at `MUL_MAT`, `OUT_PROD`, `SOLVE_TRI`
  ([ggml-ops]). OpenCL is "Deprecated in macOS 10.14" ([apple-opencl]).
- **Licences.** ArrayFire's default CPU build uses FFTW ([arrayfire]
  `CMakeLists.txt` L123), which is GPL ([fftw]): outside
  [ADR 0005][adr-0005]. MLX's CUDA back end links cuBLASLt, cuFFT, cuDNN and
  NVRTC (`mlx/backend/cuda/CMakeLists.txt`), redistributable only under
  NVIDIA's EULA ([nv-eula]). MLX's Windows wheels, CPU (amd64, arm64) and
  CUDA (amd64), are missing from its install page ([mlx-pypi]); it has no AMD
  or Intel GPU back end.
- **The CPU route**: Accelerate on macOS ([accel-lapack]); elsewhere OpenBLAS
  v0.3.34, whose LAPACK "comes included", built with a Fortran compiler or an
  older C version ([openblas] `README.md` L19, L47). That is float64
  everywhere, no JIT, one CMake build, one wheel per platform. It costs a thin
  BLAS shim (symbols, integer width, one thread inside DuckDB's), OpenBLAS in
  each non-Apple wheel, and ULP-bounded tests, as libraries sum in different
  orders.

## float64 on GPUs, and matching the CPU bit for bit

**Hardware.** Fast float64 means data-centre parts: 1:2 of float32 on A100,
H100 and B200 ([cuda-cc]) and on MI300X and MI355X ([mi300], [mi355]), but
about 1:60 on B300 ([hgx]; 1:64 by [fpmp]) and 1:4 on Rubin, whose DGEMM
uses "Tensor Core-based emulation" ([rubin]). GeForce RTX 30 to 50 runs 1:64
([cuda-cc], [cuda-gpus], [ada], [rtxbw]); the RDNA 3 W7900 1:32 ([w7900], from
a search engine's copy; ROCm's tables give no Radeon ratios, [rocm]). Intel
emulates it on Arc A and has a "small" rate on Arc B ([intelpr], [xe2oz];
[mesa] `src/intel/dev/intel_device_info.c` L833, L1177).

**Double-float**, a pair of float32s, holds 46 bits by NVIDIA's count or
"about 48" by luma.gl's, in float32's range ([fpmp], [luma]), against
float64's 53 bits and 11-bit exponent. It rests on Dekker's exact product
([dekker]) and TwoSum, exact only with round-to-nearest and gradual underflow
([riedy]), which MSL does not promise. At 10–20 instructions an add and 6–9 a
multiply ([fpmp]), an M3 GPU XᵀX would take at least 0.6 s, against 52 ms on
the CPU (estimate), and its bits never match float64's. For Metal, only
`metal-float64` (MIT) emulates IEEE float64, from 32-bit integers, at an
estimated 1/32–1/64 of float32, unfinished and archived ([mf64]); MLX
declined to emulate float64 ([mlx-1905]).

**Ozaki schemes** cut float64 into scaled integer slices whose products and
sums are exact, so only the final combination rounds ([oz12], [ozaki-2026]):
Ozaki I in s² products; INT8 slices in 45–91 GEMMs ([oot24], code [ozimmu]);
Ozaki II in one GEMM per modulus, 14–16 of them, "bit-wise" reproducible
([oz2], code [gemmul8]), though correct rounding wants 16 and wide ranges
20–24 ([xe2oz]). FP16 slices gave equal bits at any thread count ([muk20]).
cuBLAS has emulated FP64 on INT8 since CUDA 13.0 Update 2 ([nvb25]),
repeatable only with a user workspace ([cublas]), its adaptive bits ([adp])
within the classical error bound ([esc]); its Ozaki II reached 37 TFLOPS on
an RTX PRO 6000, 10–23× native, with no claim of equality to DGEMM
([nvb26]). No Metal port was found.

**Exact and reproducible sums** give the same bits in any order: a Kulisch
accumulator, 4,288 bits for double ([koenig]); xsum, under 2× an ordered sum
but 1 GB per thread for XᵀX at p = 2,000 (estimate, [neal]); ExBLAS, at "no
additional cost", in OpenCL last changed in 2021 ([cdgi15], [exblas]);
ReproBLAS, at 4× MKL's dot, for CPUs and MPI ([reproblas-tr], [repro]);
IEEE 754's augmented operations, in no hardware ([ieee], [riedy]); and int64
fixed point, as in XGBoost's GPU code ([xgbd], [xgbq]). DuckDB's float `sum`
and `fsum` are "affected by ordering" ([ducka]), hence today's ULP bounds; its
DECIMAL, stored as integers up to INT128 ([duckn]), is exact.

**The rule, kernel by kernel**: a GPU kernel returns bit for bit what the
CPU computes with the same exact method.

| Kernel              | Bit-equal on an Apple GPU?        | Cost              |
| ------------------- | --------------------------------- | ----------------- |
| Sums, means, counts | yes: fixed point or binned        | about a plain sum |
| XᵀX, the Gram       | yes: exact integer slices         | below             |
| eigh, solve (p × p) | no: no FP64; double-float differs | stays on the CPU  |

Of the models, outside sqlearn for now ([ADR 0017][adr-0017]), a naive Bayes
fit, HGB histograms and linear regression's Gram could match; logistic
regression (`exp`, `log` within 4 ulp), k-means without exact distances and
HGB gradients could not. Exact XᵀX takes power-of-two column scales, integer
slices of the IEEE bits, exact sums in any order, one rounding on the CPU,
and exact centring as XᵀX − ssᵀ/n; a fixed-order float32 sum is no way out,
as MSL allows rounding towards zero and flushing. For 400,000 × 200
(estimates): a CPU twin of 3 slices of 21 bits (6 DGEMMs) takes about 0.3 s,
six times today's 52 ms, for results free of thread order; M1–M4 GPUs need
28 float GEMMs, 0.3–1 s, no faster; the M5 and later 17–36 int8 GEMMs, 5–46
ms at 25–100 TOPS plus 4 ms to read 640 MB, for which Apple publishes no
rate. Philip Turner measured MSL's 64-bit integer add at about 4 cycles and
multiply at 16, against 1 for a float FMA, on M1-generation GPUs ([turner]).

## Measurements on the M3

The M3 has 8 cores, a 10-core GPU and 16 GB, on macOS 26.6.1, with numpy
2.5.5 on Accelerate, MLX 0.32.4 and Python 3.12, one process per probe. Loads
are 1-minute averages on 8 cores, about 4 for the main session and 3.7 to
11.3 for the reports' probes; values and sizes do not depend on them.

| XᵀX, rows × columns           | Accelerate f64 | MLX CPU f64 | Accelerate f32 | MLX GPU f32 | Timing, load             |
| ----------------------------- | -------------- | ----------- | -------------- | ----------- | ------------------------ |
| 400,000 × 200, factor data    | 52 ms          | 52 ms       | 19 ms          | 36 ms       | best of 5, load 4        |
| 100,000 × 1,000, factor data  | 307 ms         | 306 ms      | 87 ms          | 163 ms      | best of 5, load 4        |
| 1,500,000 × 200, normal       | –              | –           | 80 ms          | 176 ms      | best of 5, load 9–11     |
| 65,536 × 200, normal          | 9.9 ms         | –           | 3.5 ms         | 2.9 ms      | median of 300, load 9–10 |
| 2,048 × 200 (a chunk), normal | 251 µs         | –           | 83 µs          | 293 µs      | median of 300, load 9–10 |

Factor data are centred columns built from 11 factors plus small noise.
MLX's CPU float32 took 89 ms at 1.5 M rows. The GPU won only at 65,536 rows,
in the probe that took medians of 300 runs after 20 warm-ups, while the
larger sizes took a best of 5 after one; the cause was not checked. A
2,048-row chunk is 3.5 times slower on the GPU, so GPU work needs batches.

| Probe                            | Result                                                                                                                                                 | Load |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| float32 error, first two rows    | noise-level eigenvalues off by 10–44 times their size at 200 columns, 340–1,800 at 1,000; largest entry error 1.1e-6 and 1.8e-5 of the largest entry    | 4    |
| MLX float64 `exp`, in ULPs       | `exp(1.0)` gave 2.7182817459106445, float32's e, 1.86e8 off; 2.1e8–9.1e8 at 0.1–20; inf at 100 and 700                                                  | –    |
| MLX float64 `erf`, in ULPs       | 0.7e9–4.3e9 at 0.1–2.7, `erf(1.5)` 1.2e9; `erf(0.5)` 2.2e9 alone, 1.1e9 inside a seven-element array (rechecked for this page)                          | –    |
| MLX float64, other ops           | `sigmoid` up to 1.7e8 ULPs; `log`, `log1p`, `tanh` within 1; `fft` returns complex64                                                                    | –    |
| MLX on the GPU                   | `mx.ones((4, 4), dtype=mx.float64)`, float64 matmul and add: `ValueError: float64 is not supported on the GPU`; cholesky, solve, qr, svd, inv, eigh refused | 9 |
| MLX start-up                     | `import mlx.core` 28 ms; first GPU result 47 ms after spawn, 89 ms after install; first 200 × 200 matmul 44 ms, 0.5 ms cached; tiny op 8 µs CPU, 105 µs GPU | 9–11 |
| MPSGraph, f32 XᵀX of 2,048 × 200 | device and queue 44–48 ms; first compile 30 ms, 4.5 ms in later processes; first run 145 ms, 11 ms cached; warm 0.64–0.84 ms; 177 and 5.7 ms at 100,000 rows | 3.7 |
| f64 XᵀX of 50,000 × 200, threads | 113, 135, 168, 164 blocks a second on 1, 2, 4, 8 threads at once; 123, –, 161, 169 with `VECLIB_MAXIMUM_THREADS=1`                                      | 9–11 |
| Sizes                            | `mlx.metallib` 214.2 MB, `libmlx.dylib` 21.7 MB on disk; MLX's wheels 45 MB (macOS 14, 15) and 78 MB (26) compressed ([mlx-pypi]); the official duckdb 2.0.0 macOS arm64 wheel, 17.6 MB | – |

## Unknowns

- Whether Accelerate drives AMX or the Scalable Matrix Extension, at what
  integer rates (the CPU twin's real cost), and how many units Pro and Max
  chips give.
- Every timing on a quiet machine, an M4 or an M5; why the GPU won at 65,536
  rows; thread scaling without load.
- Which `matmul2d` types run on the M5's accelerators, and how fast: the
  float64 report's summary names int8, fp16, bf16, fp8 and fp4; [MSL] also
  lists float. Overflow, order and precision of `matmul2d` and
  `simdgroup_matrix` sums.
- Apple9's 64-bit atomics ([FST] against [MSL]); denormals and ties-to-even
  in safe mode; how often OS updates invalidate binary archives.
- Exact XᵀX's cost on an M5; whether any bit-equal kernel beats the CPU on
  M1–M4; MLX's float64 accuracy beyond the ops probed.
- Dawn, wgpu, MoltenVK, KosmicKrisp, IREE or Halide against MLX or
  Accelerate on Apple silicon; `cl_khr_fp64` there; FP64 rates of RDNA 4,
  Xe2 and Adreno.
- Licences of oneMKL, Arm Performance Libraries and rocSOLVER; OpenBLAS's
  wheel size and `dsyrk` speed against Accelerate.

[adr-0005]: ../adr/0005-runtime-dependencies.md
[adr-0017]: ../adr/0017-models-from-other-libraries.md
[adr-0043]: ../adr/0043-repeatable-within-rounding.md
[MSL]: https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf
[FST]: https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf
[MPP]: https://developer.apple.com/download/files/Metal-Performance-Primitives-Programming-Guide.pdf
[wwdc330]: https://developer.apple.com/videos/play/wwdc2026/330/
[talk]: https://developer.apple.com/videos/play/tech-talks/111432/
[m5]: https://www.apple.com/newsroom/2025/10/apple-unleashes-m5-the-next-big-leap-in-ai-performance-for-apple-silicon/
[m6]: https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/
[modular]: https://github.com/modular/modular/blob/09e51e9e537aaa9b57bd62d40f2191a726dea222/max/kernels/src/linalg/matmul/gpu/apple/int8_matmul.mojo
[turner]: https://github.com/philipturner/metal-benchmarks/tree/dc2adc640a1588246f4471d415aa6873cb6e3499
[metal-cpp]: https://github.com/apple/metal-cpp/tree/8cdde68ae36a636c84cbb48ebcbc8f3b60251ea0
[mtl-nocopy]: https://developer.apple.com/documentation/metal/mtldevice/makebuffer%28bytesnocopy:length:options:deallocator:%29
[mtl-precompile]: https://developer.apple.com/documentation/metal/building-a-shader-library-by-precompiling-source-files
[mtl-archive]: https://developer.apple.com/documentation/metal/creating-binary-archives-from-device-built-pipeline-state-objects
[xcode-metal]: https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components
[mps-dt]: https://developer.apple.com/documentation/metalperformanceshaders/mpsdatatype
[accel]: https://developer.apple.com/documentation/accelerate
[accel-blas]: https://developer.apple.com/documentation/accelerate/blas
[accel-lapack]: https://developer.apple.com/documentation/accelerate/lapack-functions
[rn133]: https://developer.apple.com/documentation/macos-release-notes/macos-13_3-release-notes
[ct-typed]: https://apple.github.io/coremltools/docs-guides/source/typed-execution.html
[m4-matrix]: https://doi.org/10.1109/SCW63240.2024.00185
[llvm-m4]: https://github.com/llvm/llvm-project/blob/b24e96763c12f9fab3cd17c0c975b0168fcdce07/llvm/lib/Target/AArch64/AArch64Processors.td#L1130-L1147
[apple-opencl]: https://developer.apple.com/opencl/
[mlx]: https://github.com/ml-explore/mlx/tree/v0.32.4
[mlx-dt]: https://ml-explore.github.io/mlx/build/html/python/data_types.html
[mlx-1905]: https://github.com/ml-explore/mlx/issues/1905
[mlx-rel]: https://github.com/ml-explore/mlx/releases
[mlx-pypi]: https://pypi.org/project/mlx/0.32.4/#files
[torch-mps]: https://docs.pytorch.org/docs/2.15/notes/mps.html
[wgsl]: https://www.w3.org/TR/2026/CRD-WGSL-20261106/
[webgpu]: https://www.w3.org/TR/webgpu/
[dawn]: https://github.com/google/dawn/tree/v20261119.211954
[wgpu-native]: https://github.com/gfx-rs/wgpu-native/releases/tag/v29.0.1.1
[wgpu]: https://github.com/gfx-rs/wgpu/tree/v30.0.2
[vk-features]: https://docs.vulkan.org/refpages/latest/refpages/source/VkPhysicalDeviceFeatures.html
[moltenvk]: https://github.com/KhronosGroup/MoltenVK/tree/v1.4.2
[mesa]: https://gitlab.freedesktop.org/mesa/mesa
[kk-news]: https://www.khronos.org/news/permalink/kosmickrisp-achieves-vulkan-1.4-conformance-on-apple-silicon
[kk-docs]: https://docs.mesa3d.org/drivers/kosmickrisp.html
[kompute]: https://github.com/KomputeProject/kompute
[sycl]: https://registry.khronos.org/SYCL/specs/sycl-2020/html/sycl-2020.html
[acpp]: https://github.com/AdaptiveCpp/AdaptiveCpp/tree/v25.10.0
[acpp-1961]: https://github.com/AdaptiveCpp/AdaptiveCpp/pull/1961
[acpp-metal]: https://github.com/AdaptiveCpp/AdaptiveCpp/blob/develop/doc/install-metal.md
[dpcpp]: https://github.com/intel/llvm/tree/v7.2.0
[onemath]: https://github.com/uxlfoundation/oneMath
[kokkos]: https://github.com/kokkos/kokkos/tree/5.3.0
[kokkos-kernels]: https://github.com/kokkos/kokkos-kernels/tree/5.3.0
[halide]: https://github.com/halide/Halide/tree/v22.1.0
[iree]: https://github.com/iree-org/iree/tree/v3.14.0
[arrayfire]: https://github.com/arrayfire/arrayfire/tree/v3.10.1
[fftw]: https://www.fftw.org/doc/License-and-Copyright.html
[ggml]: https://github.com/ggml-org/ggml/tree/v1.0.0
[ggml-ops]: https://github.com/ggml-org/llama.cpp/blob/v1.0.0/docs/ops.md
[nv-eula]: https://docs.nvidia.com/cuda/eula/index.html
[openblas]: https://github.com/OpenMathLib/OpenBLAS/tree/v0.3.34
[cuda-cc]: https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html
[cuda-gpus]: https://developer.nvidia.com/cuda-gpus
[ada]: https://images.nvidia.com/aem-dam/Solutions/geforce/ada/nvidia-ada-gpu-architecture.pdf
[rtxbw]: https://images.nvidia.com/aem-dam/Solutions/geforce/blackwell/nvidia-rtx-blackwell-gpu-architecture.pdf
[hgx]: https://www.nvidia.com/en-us/data-center/hgx/
[rubin]: https://www.nvidia.com/en-us/data-center/vera-rubin-nvl72/
[fpmp]: https://nvidia.github.io/cccl/unstable/libcudacxx/extended_api/fp/fpmp.html
[cublas]: https://docs.nvidia.com/cuda/cublas/index.html
[nvb25]: https://developer.nvidia.com/blog/unlocking-tensor-core-performance-with-floating-point-emulation-in-cublas/
[nvb26]: https://developer.nvidia.com/blog/faster-scientific-simulations-with-new-fp64-algorithms-in-nvidia-cublas/
[adp]: https://arxiv.org/abs/2511.13778
[esc]: https://research.nvidia.com/publication/2026-11_providing-accuracy-guarantees-fixed-point-emulation-matrix-multiplication
[rocm]: https://rocm.docs.amd.com/en/latest/reference/gpu-arch-specs.html
[w7900]: https://www.amd.com/content/dam/amd/en/documents/partner-hub/radeon-pro/amd-radeon-pro-w7900-dual-slot-datasheet-competitive.pdf
[mi300]: https://rocm.docs.amd.com/en/docs-10.0.0/reference/gpu-arch/mi300.html
[mi355]: https://rocm.docs.amd.com/en/docs-10.0.0/reference/gpu-arch/mi350.html
[intelpr]: https://github.com/intel/torch-xpu-ops/pull/2180
[xe2oz]: https://arxiv.org/abs/2610.26945
[dekker]: https://doi.org/10.1007/BF01397083
[riedy]: https://doi.org/10.1109/ARITH.2018.8464813
[luma]: https://luma.gl/docs/api-guide/shaders/gpu-floating-point-precision
[mf64]: https://github.com/philipturner/metal-float64
[oz12]: https://doi.org/10.1007/s11075-011-9478-1
[ozaki-2026]: https://doi.org/10.1177/10943420261467787
[muk20]: https://doi.org/10.1007/978-3-030-50743-5_12
[oot24]: https://arxiv.org/abs/2306.11975
[ozimmu]: https://github.com/enp1s0/ozIMMU
[oz2]: https://arxiv.org/abs/2504.08009
[gemmul8]: https://github.com/RIKEN-RCCS/GEMMul8/tree/v3.5.7
[koenig]: https://www2.eecs.berkeley.edu/Pubs/TechRpts/2018/EECS-2018-51.html
[neal]: https://arxiv.org/abs/1505.05571
[cdgi15]: https://doi.org/10.1016/j.parco.2015.09.001
[exblas]: https://github.com/riakymch/exblas/blob/856130ebcfe906f519a623d57d1359e744e29042/LICENSE
[reproblas-tr]: https://www2.eecs.berkeley.edu/Pubs/TechRpts/2016/EECS-2016-121.html
[repro]: https://github.com/willow-ahrens/ReproBLAS/tree/v2.1.0
[ieee]: https://grouper.ieee.org/groups/msc/ANSI_IEEE-Std-754-2019/background/
[xgbd]: https://github.com/dmlc/xgboost/blob/v3.4.2/src/common/deterministic.cuh
[xgbq]: https://github.com/dmlc/xgboost/blob/v3.4.2/src/tree/gpu_hist/quantiser.cuh
[duckn]: https://duckdb.org/docs/2.0/sql/data_types/numeric.html
[ducka]: https://duckdb.org/docs/2.0/sql/functions/aggregates.html

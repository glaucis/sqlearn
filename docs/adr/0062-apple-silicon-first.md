---
type: adr
tags: [platforms, apple-silicon, macos, gpu, ci, github-pages, architecture-decision]
summary: "Records that macOS 15 or later on Apple silicon gets the tuned build, Linux and Windows get the safe CPU build, Intel Macs and musl get none, and the public repository serves the site from GitHub Pages; amends ADR 0009."
related: [docs/adr/0009-sphinx-documentation-site.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/specs/native-engine.md]
---
# 0062: Apple silicon first, a safe CPU build elsewhere

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.3). Amends
[ADR 0009](0009-sphinx-documentation-site.md).

## Context

Data preparation on Apple silicon, with unified memory (the CPU, the matrix
units and the GPU share one memory), is one of the best setups there is, and
its users miss out today. sqlearn starts there.

Three points from Tomas (Tomas, 2026-11-21). Apple silicon is the priority above
all, with maximum optimisation and speed, because he uses it. The other
platforms are built at the same time, on the CPU only, with general
optimisations. Accuracy is never traded for speed: no `-ffast-math`, because
a machine learning library has to be exact. Fine-grained tuning is welcome
where it squeezes out more.

The other platforms are the ones DuckDB itself builds for: Linux x86_64 and
arm64 (glibc) and Windows x86_64 and arm64. DuckDB's own extension builds
treat Intel Macs as best-effort in 2.0 and drop them in 2.1. DuckDB ships no
musl build, and the sanitizers do not support musl.

Three other ways were weighed:

- **macOS 14 as the floor.** Accelerate's per-thread setting needs macOS 15,
  so it would need a second code path.
- **macOS 26 as the floor.** It leaves out companies a year behind.
- **Scripts that compile on the user's machine.** Every user would need a
  C++ compiler and a long build.

## Decision

- **Apple silicon first:** macOS 15 or later on Apple silicon (M1 onwards)
  gets the tuned build. Apple-only, granular optimisations are welcome
  wherever a benchmark proves the gain and the tests prove the same answers:
  compiler settings for Apple's chips, link-time and profile-guided
  optimisation, Accelerate on the matrix units, Metal kernels, and DuckDB
  allocating page-aligned memory so the GPU reads its columns in place.
- **Every other platform gets the safe default CPU build:** Linux x86_64 and
  arm64 (glibc) and Windows x86_64 and arm64. Intel Macs get none. Nor does
  musl Linux (Alpine) for now; it comes when users ask (Tomas, 2026-11-21).
  The safe build still takes general optimisations: full compiler
  optimisation, link-time optimisation, and faster instructions (AVX2 or
  AVX-512 on x86_64) chosen at run time where the running processor has
  them. The condition is Apple's: a benchmark proves the gain and the tests
  prove the same answers (Tomas, 2026-11-21).
- **One ready-made build per platform** serves every Python from 3.12, on
  CPython's stable ABI as DuckDB's own wheels are (`cp312-abi3`; ADR 0007
  unchanged). CI builds them and attaches them to GitHub Releases. PyPI comes
  later, once sqlearn runs (Tomas: no unready product goes out). On a
  platform with no ready-made build, installing compiles from the source
  package; users need no script of their own.
- **GPU: Apple only for now.** NVIDIA, AMD and others come when someone asks
  and they can be tested.
- **The repository is public** (Tomas, 2026-11-21), so CI runs free on every
  platform, and code scanning of the C++ is free too. The site is served by
  GitHub Pages from it, which answers the site-hosting question (amends ADR
  0009).

## Consequences

- Phase 1's CI covers five platforms: macOS on Apple silicon, Linux x86_64
  and arm64, and Windows x86_64 and arm64.
- Validation results are kept per platform.
- Apple-only code paths are allowed where a benchmark and the tests back
  them.
- #4 and #6, the site on GitHub Pages, follow Phase 1's CI.

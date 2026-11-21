---
type: adr
tags: [cpp, safety, sanitizers, fuzzing, static-analysis, architecture-decision]
summary: "Records the safety rules binding the engine's C++ from its first commit: Core Guidelines coding, strict compiler flags, static analysis, a hardened standard library, sanitizers and fuzzing in CI, and no crash reaching the user."
related: [docs/adr/0016-validation-method.md, docs/adr/0043-repeatable-within-rounding.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/specs/native-engine.md]
---
# 0065: Safety rules for the C++

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.6).

## Context

Memory safety is Tomas's main worry about C++. The engine runs inside the user's
Python process (see [ADR 0060](0060-a-native-engine-in-cpp-inside-duckdb.md)),
so a crash in it kills their notebook.

The rules bind from the first commit.

## Decision

- **Coding:** the C++ Core Guidelines. No raw `new` or `delete`
  (`unique_ptr`, RAII). `std::span` and `std::vector`, never C arrays. Raw
  memory (DuckDB's vectors, Metal buffers) lives only in one thin, named
  layer, reviewed hardest.
- **Compiler:** `-Wall -Wextra -Wconversion -Werror`, and the MSVC
  equivalent. No `-ffast-math`.
- **Static analysis:** clang-tidy (`bugprone-*`, `cppcoreguidelines-*`,
  `performance-*`) and the Clang static analyser in CI. A finding fails the
  build.
- **Hardened standard library** (libc++ hardening, or
  `_GLIBCXX_ASSERTIONS`) in every build, release included, unless a
  benchmark proves a cost and an ADR accepts it. Phase 1 measures the cost;
  Tomas rules.
- **Sanitizers on every CI run:** AddressSanitizer with
  UndefinedBehaviorSanitizer, and ThreadSanitizer as a separate run,
  wherever the tools exist: all three on Linux (glibc) and macOS,
  AddressSanitizer on Windows (MSVC has no others). The same code is
  sanitized there, and every other build is built and tested (the agent's
  call).
- **Fuzzing:** libFuzzer on each function's pure core (random, NaN, ±inf,
  empty and huge inputs), in CI.
- **SQL-level tests:** DuckDB sqllogictest files for every function.
- **Numerics:** the [ADR 0016](0016-validation-method.md) method (exact
  values from mpmath or `Fraction`, bounds in ULPs per
  [ADR 0043](0043-repeatable-within-rounding.md)), run from Python against the
  built engine.
- **No crash reaches the user:** every entry point catches exceptions and
  returns a DuckDB error worded with sqlearn's `Why:` and `Fix:` lines.

## Consequences

- Phase 1 sets up a CI job for each rule.
- Phase 1's spec names the thin layer for raw memory.
- Phase 1 measures the cost of the hardened standard library, and Tomas
  rules on it.

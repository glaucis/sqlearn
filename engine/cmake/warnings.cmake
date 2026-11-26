# The warnings sqlearn's own sources compile with, as errors, and the
# floating-point rule they keep. DuckDB's, duckdb-python's, nanobind's and
# the test libraries' sources keep their own flags; their headers reach ours
# as system headers, so these cover our code only.

# Spec §3.2 and §3.9. -Wunsafe-buffer-usage is kept apart: it is on
# everywhere but engine/src/raw/, the one layer for raw memory (ADR 0065).
set(
  SQ_WARNINGS
  -Wall
  -Wextra
  -Wconversion
  -Wsign-conversion
  -Wshadow
  -Wold-style-cast
  -Wnon-virtual-dtor
  -Wimplicit-fallthrough
  -Wswitch-enum
  -Wdouble-promotion
  -Werror
)
set(SQ_BUFFER_WARNING "")

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  list(APPEND SQ_WARNINGS -Wdocumentation -Wthread-safety)
  set(SQ_BUFFER_WARNING -Wunsafe-buffer-usage)
  # -Wlifetime-safety (experimental, spec §3.9), kept after a trial on
  # 2026-11-23: the core, bindings and extension sources build clean with
  # it under Apple clang 21 and Homebrew LLVM 23. Only LLVM 23 acts on it
  # (a returned view of a local string is found); Apple clang 21 accepts it
  # and reports nothing, so the llvm-dev build is where it bites. Tried again
  # on 2026-11-23 with the version parser and the raw layer's Buffer: no
  # finding, true or false, under LLVM 23. It misses a returned span of a
  # local Buffer and a view of a local Version's `pre`, so it is a net, not
  # a proof.
  list(APPEND SQ_WARNINGS -Wlifetime-safety)
endif()

# Never -ffast-math (ADR 0063). FMA contraction off, so every compiler and
# platform gives the same bits (spec §3.9); a kernel that wants FMA calls
# std::fma. The FMA ADR before Phase 2's kernels may change this line.
set(SQ_FP_OPTIONS -ffp-contract=off)

# Give `target` sqlearn's warnings and floating-point rule. RAW marks the
# raw memory layer, which alone goes without -Wunsafe-buffer-usage.
function(sq_target_warnings target)
  cmake_parse_arguments(PARSE_ARGV 1 arg "RAW" "" "")
  target_compile_options(${target} PRIVATE ${SQ_WARNINGS} ${SQ_FP_OPTIONS})
  if(NOT arg_RAW)
    target_compile_options(${target} PRIVATE ${SQ_BUFFER_WARNING})
  endif()
endfunction()

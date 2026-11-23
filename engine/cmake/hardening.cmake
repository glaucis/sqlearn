# The build flavours of sqlearn's own sources (spec §3.9's presets): the
# optimisation and debug-information levels, the hardened libc++ mode, how
# uninitialised locals start, the CPU target and the sanitizers. A preset
# sets SQ_FLAVOR; the wheel (scikit-build-core, no preset) is `release`.
#
# libc++'s hardening mode is chosen per translation unit, so ours can differ
# from DuckDB's (theirs are built without the macro, libc++'s default
# `none`): libc++ tags every function hidden from its ABI with a signature
# whose first character is the mode (_LIBCPP_ODR_SIGNATURE, `__config`), so
# copies inlined under two modes are distinct symbols, never an ODR clash,
# and a mode does not change the ABI (libc++'s Hardening documentation:
# "ABI tags allow translation units built with different hardening modes to
# interact"). The prebuilt libc++ dylib keeps the mode Apple built it with.
# The macro must come before any header: it is a compile definition.

set(
  SQ_FLAVOR
  "release"
  CACHE STRING
  "The flavour of sqlearn's own sources: dev, debug, release or profile"
)
set_property(
  CACHE SQ_FLAVOR
  PROPERTY STRINGS dev debug release profile
)

set(SQ_HARDENING_EXTENSIVE "_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE")
set(SQ_HARDENING_FAST "_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST")

# CPU targets as ADR 0062: Apple silicon gets apple-m1; elsewhere the
# compiler's safe default.
set(SQ_CPU_OPTIONS "")
if(APPLE AND CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
  set(SQ_CPU_OPTIONS -mcpu=apple-m1)
endif()

set(SQ_SANITIZERS "")
if(SQ_FLAVOR STREQUAL "dev")
  set(SQ_FLAVOR_OPTIONS -O1 -g -fno-omit-frame-pointer -ftrivial-auto-var-init=pattern)
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
  # Every finding stops the program, so a test cannot pass over one.
  set(SQ_SANITIZERS -fsanitize=address,undefined -fno-sanitize-recover=all)
elseif(SQ_FLAVOR STREQUAL "debug")
  set(SQ_FLAVOR_OPTIONS -O0 -g -ftrivial-auto-var-init=pattern)
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
elseif(SQ_FLAVOR STREQUAL "release")
  # ThinLTO is left out: our objects link into _duckdb with DuckDB's, which
  # are built without it, and no build with it has been measured; spec
  # §3.9's `just tune` tries LTO.
  set(SQ_FLAVOR_OPTIONS -O2 -gline-tables-only -ftrivial-auto-var-init=zero ${SQ_CPU_OPTIONS})
  set(SQ_HARDENING ${SQ_HARDENING_FAST})
elseif(SQ_FLAVOR STREQUAL "profile")
  set(
    SQ_FLAVOR_OPTIONS
    -O2
    -g
    -fno-omit-frame-pointer
    -ftrivial-auto-var-init=zero
    ${SQ_CPU_OPTIONS}
  )
  set(SQ_HARDENING ${SQ_HARDENING_FAST})
else()
  message(
    FATAL_ERROR
    "SQ_FLAVOR is \"${SQ_FLAVOR}\".\n"
    "Fix: configure with a preset (cmake --preset dev), or set SQ_FLAVOR to dev, debug, release or profile"
  )
endif()

# Give `target` the flavour: its compile options, the hardening mode and,
# for a program, the sanitizers' runtime at the link.
function(sq_target_flavor target)
  target_compile_options(${target} PRIVATE ${SQ_FLAVOR_OPTIONS} ${SQ_SANITIZERS})
  target_compile_definitions(${target} PRIVATE ${SQ_HARDENING})
  target_link_options(${target} PRIVATE ${SQ_SANITIZERS})
endfunction()

# In a build of our groups alone (SQ_ENGINE_ONLY), the sanitizers and the
# hardening mode cover every target, the test libraries included: a
# sanitizer that sees half a program misses errors and reports false ones
# (spec §3.2).
function(sq_flavor_everywhere)
  add_compile_options(${SQ_SANITIZERS})
  add_link_options(${SQ_SANITIZERS})
  add_compile_definitions(${SQ_HARDENING})
endfunction()

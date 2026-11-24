# The build flavours of sqlearn's own sources (spec §3.9's presets): the
# optimisation and debug-information levels, the hardened libc++ mode, how
# uninitialised locals start, the CPU target, the release hardening and the
# sanitizers. A preset sets SQ_FLAVOR; the wheel (scikit-build-core, no
# preset) is `release`.
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
  "The flavour of sqlearn's own sources: dev, debug, release, profile, tsan, lsan or tysan"
)
set_property(
  CACHE SQ_FLAVOR
  PROPERTY STRINGS dev debug release profile tsan lsan tysan
)

set(SQ_HARDENING_EXTENSIVE "_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE")
set(SQ_HARDENING_FAST "_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST")

# CPU targets as ADR 0062: Apple silicon gets apple-m1; elsewhere the
# compiler's safe default.
set(SQ_CPU_OPTIONS "")
if(APPLE AND CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
  set(SQ_CPU_OPTIONS -mcpu=apple-m1)
endif()

# The release hardening of OpenSSF's compiler options guide, for the
# optimised flavours: _FORTIFY_SOURCE needs optimisation, and is undefined
# first in case the compiler or a caller set another level. macOS's SDK
# reads any level above 1 as its level 2 (secure/_common.h). Stack clash
# protection only where the compiler takes it: Apple clang 21 and LLVM 23
# ignore it on arm64 macOS ("argument unused"), so it is left out there.
# Branch protection (pointer authentication, branch targets) on arm64.
include(CheckCXXCompilerFlag)
include(CMakePushCheckState)
set(SQ_RELEASE_HARDENING -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3 -fstack-protector-strong)
# The check compiles and links, where Clang's unused argument is only a
# warning, so Clang is asked to make it an error; GCC refuses that option,
# and says itself when it does not take a flag.
cmake_push_check_state()
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  set(CMAKE_REQUIRED_FLAGS -Werror=unused-command-line-argument)
endif()
check_cxx_compiler_flag(-fstack-clash-protection SQ_TAKES_STACK_CLASH_PROTECTION)
cmake_pop_check_state()
if(SQ_TAKES_STACK_CLASH_PROTECTION)
  list(APPEND SQ_RELEASE_HARDENING -fstack-clash-protection)
endif()
if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
  list(APPEND SQ_RELEASE_HARDENING -mbranch-protection=standard)
endif()

# The sanitizer flavours build as dev does, for the debugger's sake, with
# their one sanitizer. A finding fails the program, so a test cannot pass
# over one: -fno-sanitize-recover=all, and halt_on_error in each test's
# environment (SQ_TEST_ENVIRONMENT) for ThreadSanitizer and for
# TypeSanitizer, which reports and goes on whatever that flag says. Most
# stop at the fault; LeakSanitizer looks at exit, and fails the program
# then.
set(SQ_DEBUG_OPTIONS -O1 -g -fno-omit-frame-pointer -ftrivial-auto-var-init=pattern)
set(SQ_SANITIZERS "")
set(SQ_TEST_ENVIRONMENT "")
if(SQ_FLAVOR MATCHES "^(lsan|tysan)$" AND NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
  # Apple clang has no LeakSanitizer on Apple silicon and no TypeSanitizer.
  message(
    FATAL_ERROR
    "SQ_FLAVOR ${SQ_FLAVOR} needs Homebrew LLVM's clang, not ${CMAKE_CXX_COMPILER_ID}.\n"
    "Fix: cmake --preset ${SQ_FLAVOR} (it builds with engine/cmake/toolchain-llvm.cmake)"
  )
endif()
if(SQ_FLAVOR STREQUAL "dev")
  set(SQ_FLAVOR_OPTIONS ${SQ_DEBUG_OPTIONS})
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
  set(SQ_SANITIZERS -fsanitize=address,undefined -fno-sanitize-recover=all)
  # AddressSanitizer's leak check: Homebrew LLVM's runtime has it on Apple
  # silicon, Apple's refuses detect_leaks=1 there.
  if(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    set(SQ_TEST_ENVIRONMENT ASAN_OPTIONS=detect_leaks=1)
  endif()
elseif(SQ_FLAVOR STREQUAL "tsan")
  set(SQ_FLAVOR_OPTIONS ${SQ_DEBUG_OPTIONS})
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
  set(SQ_SANITIZERS -fsanitize=thread -fno-sanitize-recover=all)
  set(SQ_TEST_ENVIRONMENT TSAN_OPTIONS=halt_on_error=1)
elseif(SQ_FLAVOR STREQUAL "lsan")
  set(SQ_FLAVOR_OPTIONS ${SQ_DEBUG_OPTIONS})
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
  set(SQ_SANITIZERS -fsanitize=leak -fno-sanitize-recover=all)
elseif(SQ_FLAVOR STREQUAL "tysan")
  set(SQ_FLAVOR_OPTIONS ${SQ_DEBUG_OPTIONS})
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
  set(SQ_SANITIZERS -fsanitize=type -fno-sanitize-recover=all)
  set(SQ_TEST_ENVIRONMENT TYSAN_OPTIONS=halt_on_error=1)
elseif(SQ_FLAVOR STREQUAL "debug")
  set(SQ_FLAVOR_OPTIONS -O0 -g -ftrivial-auto-var-init=pattern)
  set(SQ_HARDENING ${SQ_HARDENING_EXTENSIVE})
elseif(SQ_FLAVOR STREQUAL "release")
  # ThinLTO is left out: our objects link into _duckdb with DuckDB's, which
  # are built without it, and no build with it has been measured; spec
  # §3.9's `just tune` tries LTO.
  set(
    SQ_FLAVOR_OPTIONS
    -O2
    -gline-tables-only
    -ftrivial-auto-var-init=zero
    ${SQ_CPU_OPTIONS}
    ${SQ_RELEASE_HARDENING}
  )
  set(SQ_HARDENING ${SQ_HARDENING_FAST})
elseif(SQ_FLAVOR STREQUAL "profile")
  set(
    SQ_FLAVOR_OPTIONS
    -O2
    -g
    -fno-omit-frame-pointer
    -ftrivial-auto-var-init=zero
    ${SQ_CPU_OPTIONS}
    ${SQ_RELEASE_HARDENING}
  )
  set(SQ_HARDENING ${SQ_HARDENING_FAST})
else()
  message(
    FATAL_ERROR
    "SQ_FLAVOR is \"${SQ_FLAVOR}\".\n"
    "Fix: configure with a preset (cmake --preset dev), or set SQ_FLAVOR to dev, debug, release, profile, tsan, lsan or tysan"
  )
endif()

# Give the test `test` the flavour's sanitizer options (SQ_TEST_ENVIRONMENT),
# before any the user exported: each NAME=options becomes NAME=options:<the
# user's>, and the sanitizers read their options left to right, so the
# user's win. The checks hash the test's properties and the user's variables
# both (validation/_ctest.py), so a group's identity is what it runs with.
function(sq_test_environment test)
  set(changes "")
  foreach(entry IN LISTS SQ_TEST_ENVIRONMENT)
    string(FIND "${entry}" "=" split)
    string(SUBSTRING "${entry}" 0 ${split} name)
    math(EXPR start "${split} + 1")
    string(SUBSTRING "${entry}" ${start} -1 options)
    list(APPEND changes "${name}=string_prepend:${options}:")
  endforeach()
  if(changes)
    set_property(TEST ${test} APPEND PROPERTY ENVIRONMENT_MODIFICATION ${changes})
  endif()
endfunction()

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

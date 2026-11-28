# sqlearn's engine: DuckDB's Python module built from the submodules, with
# sqlearn's C++ compiled into the same binary. scikit-build-core runs this
# (pyproject.toml, [tool.scikit-build]), and so do the presets, for our
# groups alone (below); nothing is fetched at configure time.
cmake_minimum_required(VERSION 3.29)

project(sqlearn LANGUAGES C CXX)

# Our targets are C++23 (spec §3.8); duckdb-python sets C++17 for its own and
# DuckDB's, inside its directory.
set(SQ_CXX_STANDARD 23)

# compile_commands.json for clang-tidy and the editors: it must be set at the
# top level, or the submodules' targets are left out of it.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Two builds read this file. The wheel's (scikit-build-core, pyproject.toml)
# compiles DuckDB, duckdb-python and our groups into the _duckdb module. A
# preset's (CMakePresets.json, `just build-engine`) sets SQ_ENGINE_ONLY and
# compiles our groups alone, with their test programs: no group of step 2
# needs DuckDB, so the sanitizer builds do not rebuild it.
option(
  SQ_ENGINE_ONLY
  "Build sqlearn's C++ groups and their tests, without DuckDB or the module"
  OFF
)
option(SQ_BUILD_TESTS "Build the C++ test programs (CTest)" ${SQ_ENGINE_ONLY})

include(cmake/pins.cmake)
include(cmake/ccache.cmake)
include(cmake/duckdb_package.cmake)
include(cmake/warnings.cmake)
include(cmake/hardening.cmake)
include(cmake/groups.cmake)
include(cmake/headers_alone.cmake)
include(cmake/cpptrace.cmake)
sq_check_pins()
sq_ccache()

set(SQ_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# What the build is, compiled into core/version.cpp and the extension's
# version: sqlearn's version as scikit-build-core has it, DuckDB's from the
# pins, the compiler and the build type.
if(DEFINED SKBUILD_PROJECT_VERSION_FULL)
  set(SQ_SQLEARN_VERSION "${SKBUILD_PROJECT_VERSION_FULL}")
else()
  set(SQ_SQLEARN_VERSION "0+unknown")
endif()
string(REGEX REPLACE "^v" "" SQ_DUCKDB_VERSION "${SQ_DUCKDB_TAG}")

# The core group's sources: the groups' build (below) and the SQL tests'
# (engine/sqllogic) compile them alike.
set(SQ_CORE_SOURCES src/core/error.cpp src/core/parse_version.cpp src/core/version.cpp)

# Give `source`, core/version.cpp, the build identity: a header written into
# this build directory (from cmake/build_identity.hpp.in), on its include
# path alone. configure_file rewrites it only when a value changes, so a new
# version recompiles only that file. A header rather than definitions on the
# command line, which Mull cannot parse when a value has a space (the
# compiler's). A source file's properties hold in the directory that sets
# them, so each directory compiling it calls this.
function(sq_build_identity source)
  set(SQ_COMPILER "${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
  set(SQ_BUILD_TYPE "${CMAKE_BUILD_TYPE}")
  foreach(
    name
    IN
    ITEMS SQ_SQLEARN_VERSION SQ_DUCKDB_VERSION SQ_DUCKDB_COMMIT SQ_COMPILER SQ_BUILD_TYPE
  )
    if("${${name}}" MATCHES "[\"\\\\\n]")
      message(
        FATAL_ERROR
        "${name} is \"${${name}}\", which a C++ string literal cannot "
        "hold as it is.\nFix: give it no quote, backslash or new line"
      )
    endif()
  endforeach()
  set(dir "${CMAKE_BINARY_DIR}/generated")
  configure_file("${SQ_ENGINE_DIR}/cmake/build_identity.hpp.in" "${dir}/build_identity.hpp" @ONLY)
  set_source_files_properties(${source} PROPERTIES INCLUDE_DIRECTORIES "${dir}")
endfunction()

# The sqllogic preset builds the SQL tests alone: DuckDB's own tree with its
# sqllogictest runner and the sqlearn extension (engine/sqllogic), without
# duckdb-python or our groups' test programs.
option(SQ_SQLLOGIC "Build DuckDB's unittest with the sqlearn extension, and nothing else" OFF)
if(SQ_SQLLOGIC)
  # At the top level, so `ctest --test-dir engine/build/sqllogic` finds the test.
  enable_testing()
  add_subdirectory(sqllogic)
  return()
endif()

if(SQ_ENGINE_ONLY)
  sq_flavor_everywhere()
else()
  # The sqlearn extension, configured by DuckDB's own extension build and
  # linked into _duckdb beside the official four. LINK_EXTENSIONS replaces
  # duckdb-python's default list, so pyproject.toml repeats the four.
  set(DUCKDB_EXTENSION_CONFIGS "${CMAKE_CURRENT_SOURCE_DIR}/extension/sqlearn_config.cmake")
  if(NOT "sqlearn" IN_LIST LINK_EXTENSIONS)
    message(
      FATAL_ERROR
      "LINK_EXTENSIONS is \"${LINK_EXTENSIONS}\", without sqlearn: the module "
      "would have no sqlearn_version() and would download extensions.\n"
      "Fix: set LINK_EXTENSIONS to \"core_functions;json;parquet;icu;sqlearn\" "
      "in pyproject.toml's [tool.scikit-build.cmake.define]"
    )
  endif()

  # The version and commit DuckDB is built as, from the pins, not from git
  # describe: _duckdb.__version__ and _duckdb.__git_revision__.
  set(OVERRIDE_GIT_DESCRIBE "${SQ_DUCKDB_TAG}")
  set(GIT_COMMIT_HASH "${SQ_DUCKDB_COMMIT}")

  add_subdirectory(duckdb-python)

  # The flavour's link options reach the module our objects are compiled
  # into: in the coverage wheel (just audit-groups), the coverage runtime
  # that writes their counts. The release flavour has none.
  target_link_options(_duckdb PRIVATE ${SQ_FLAVOR_LINK_OPTIONS})

  # Their headers are system headers to our targets, so our warnings (as
  # errors) cover our code and not theirs. Setting a property of their
  # targets edits none of their files.
  foreach(
    theirs
    IN
    ITEMS _duckdb_dependencies duckdb_target duckdb_static nanobind-static-abi3 nanobind-static
  )
    if(TARGET ${theirs})
      set_property(TARGET ${theirs} PROPERTY SYSTEM TRUE)
    endif()
  endforeach()

  # Compile the objects of one of our libraries (a group's static library,
  # the bindings' object library) into _duckdb, beside duckdb-python's own
  # objects (the spike's mechanism): all of them, used or not. sq_add_group
  # calls it for each group.
  function(sq_add_to_module target)
    target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:${target}>)
  endfunction()
endif()

# cpptrace, for the crash group's stack traces (engine/cmake/cpptrace.cmake):
# after the flavour, so a preset's sanitizers reach it as they reach Catch2.
sq_add_cpptrace()
if(NOT SQ_ENGINE_ONLY)
  target_link_libraries(_duckdb PRIVATE cpptrace::cpptrace)
endif()

if(SQ_BUILD_TESTS)
  enable_testing()
  set(CATCH_INSTALL_DOCS OFF CACHE BOOL "" FORCE)
  set(CATCH_INSTALL_EXTRAS OFF CACHE BOOL "" FORCE)
  add_subdirectory(third_party/catch2 EXCLUDE_FROM_ALL)
  # As system headers to our tests, so our warnings cover our code only.
  set_property(TARGET Catch2 Catch2WithMain PROPERTY SYSTEM TRUE)

  # RapidCheck's library from its own CMake, with no tests, examples or
  # extras: its extras' CMake would add ext/catch, a nested submodule we do
  # not fetch. Its Catch2 header (extras/catch/include) is all the
  # integration there is, so sq_rapidcheck_catch carries it beside the
  # library. It keeps its own flags; the flavour's sanitizers and hardening
  # reach it through sq_flavor_everywhere, as they reach Catch2.
  set(RC_ENABLE_TESTS OFF CACHE BOOL "" FORCE)
  set(RC_ENABLE_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(RC_INSTALL_ALL_EXTRAS OFF CACHE BOOL "" FORCE)
  set(RC_ENABLE_CATCH OFF CACHE BOOL "" FORCE)
  add_subdirectory(third_party/rapidcheck EXCLUDE_FROM_ALL)
  set_property(TARGET rapidcheck PROPERTY SYSTEM TRUE)
  add_library(sq_rapidcheck_catch INTERFACE)
  target_include_directories(
    sq_rapidcheck_catch
    SYSTEM
    INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/third_party/rapidcheck/extras/catch/include"
  )
  target_link_libraries(sq_rapidcheck_catch INTERFACE rapidcheck)
endif()

sq_add_group(
  core
  SOURCES ${SQ_CORE_SOURCES}
  TESTS tests/core/test_version.cpp tests/core/test_parse_version.cpp tests/core/test_error.cpp
)
# The one layer allowed raw memory (ADR 0065); its SQ_EXPECTS throws core's
# PreconditionError.
sq_add_group(
  raw
  SOURCES
    src/raw/buffer.cpp
    src/raw/demangle.cpp
    src/raw/fd_writer.cpp
    src/raw/fixed_text.cpp
    src/raw/images.cpp
  DEPENDS core
  TESTS tests/raw/test_buffer.cpp tests/raw/test_demangle.cpp tests/raw/test_signal_safe.cpp
  BENCH buffer
)
# The crash report: a handler for the fatal signals, written to a local file
# with cpptrace's signal-safe stack trace, never sent anywhere (ADR 0006).
# ThreadSanitizer intercepts signals and delivers them late, so the cases
# tagged [signals], which test how the handler chains a signal (delivery,
# masks, SA_NODEFER, SA_RESETHAND, re-entry), cannot be trusted under it:
# the tsan flavour runs the rest of the group (docs/architecture/testing.md).
set(sq_crash_args "")
if(SQ_FLAVOR STREQUAL "tsan")
  set(sq_crash_args "~[signals]")
endif()
# TypeSanitizer cannot see the kernel's writes of siginfo and ucontext, and
# every crash case reads them, so its findings there are the tool's limit,
# not our code's: the tysan flavour builds the group without its tests.
# They run under dev, tsan (without [signals]), lsan, llvm-dev and the
# other presets (tests/engine/test_sanitizers.py pins that crash alone is
# left out).
set(sq_crash_tests tests/crash/test_handler.cpp)
if(SQ_FLAVOR STREQUAL "tysan")
  set(sq_crash_tests "")
endif()
sq_add_group(
  crash
  SOURCES src/crash/handler.cpp
  DEPENDS core raw
  TESTS ${sq_crash_tests}
  ARGS ${sq_crash_args}
)
target_link_libraries(sq_crash PUBLIC cpptrace::cpptrace)
# The tests' hook into the report (crash/handler.hpp), in a preset's build
# alone: the wheel's module never has it.
if(SQ_ENGINE_ONLY)
  target_compile_definitions(sq_crash PUBLIC SQ_CRASH_TEST_HOOKS)
endif()
# Its tests crash forked children, which die before the coverage runtime
# writes their profile at exit: in the coverage flavour they write it first
# (tests/crash/test_handler.cpp).
if(TARGET test_crash AND SQ_FLAVOR STREQUAL "coverage")
  target_compile_definitions(test_crash PRIVATE SQ_COVERAGE)
endif()
sq_build_identity(src/core/version.cpp)
sq_write_groups_manifest()

sq_add_headers_alone()

if(NOT SQ_ENGINE_ONLY)
  # The bindings: sqlearn._native, built against DuckDB's and nanobind's
  # headers through duckdb-python's interface target (which carries
  # NB_DOMAIN=duckdb). They need the module, so they are no group of their
  # own in a preset's build.
  add_library(sq_bindings OBJECT src/bindings/module.cpp src/bindings/connection.cpp)
  sq_target_options(sq_bindings)
  target_link_libraries(sq_bindings PRIVATE _duckdb_dependencies)
  sq_add_to_module(sq_bindings)

  sq_install_duckdb_package("${CMAKE_CURRENT_SOURCE_DIR}/duckdb-python")
endif()

if(SQ_BUILD_TESTS)
  add_subdirectory(tests)
  add_subdirectory(fuzz)
  add_subdirectory(bench)
endif()

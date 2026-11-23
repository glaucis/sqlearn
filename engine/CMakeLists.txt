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
include(cmake/duckdb_package.cmake)
include(cmake/warnings.cmake)
include(cmake/hardening.cmake)
include(cmake/groups.cmake)
include(cmake/headers_alone.cmake)
sq_check_pins()

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

  # Compile one of our object libraries into _duckdb, beside duckdb-python's
  # own objects (the spike's mechanism). sq_add_group calls it for each group.
  function(sq_add_to_module target)
    target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:${target}>)
  endfunction()
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
  SOURCES src/core/error.cpp src/core/parse_version.cpp src/core/version.cpp
  TESTS tests/core/test_version.cpp tests/core/test_parse_version.cpp
)
# The one layer allowed raw memory (ADR 0065); its SQ_EXPECTS throws core's
# PreconditionError.
sq_add_group(raw SOURCES src/raw/buffer.cpp DEPENDS core TESTS tests/raw/test_buffer.cpp)
# On this file alone, so a new version recompiles only it.
set_source_files_properties(
  src/core/version.cpp
  PROPERTIES
    COMPILE_DEFINITIONS
      "SQ_SQLEARN_VERSION=\"${SQ_SQLEARN_VERSION}\";SQ_DUCKDB_VERSION=\"${SQ_DUCKDB_VERSION}\";SQ_DUCKDB_COMMIT=\"${SQ_DUCKDB_COMMIT}\";SQ_COMPILER=\"${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}\";SQ_BUILD_TYPE=\"${CMAKE_BUILD_TYPE}\""
)

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
  add_subdirectory(bench)
endif()

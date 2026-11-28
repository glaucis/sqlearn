# The SQL tests of the sqlearn extension (ADR 0065: sqllogictest files for
# every function), run by DuckDB's own runner. DuckDB's sqllogictest runner
# exists only in its unittest program, so this builds DuckDB's own tree (not
# duckdb-python) with BUILD_UNITTESTS and our extension statically linked, as
# DuckDB's extension template builds an extension's tests. engine/CMakeLists.txt
# adds this directory alone for the sqllogic preset (SQ_SQLLOGIC), after the
# pins are checked and with its helpers and the build identity defined.
#
# DuckDB's options are set here, before its directory reads them; none of its
# files is edited. Our warnings and flavour reach our sources only (the
# extension's CMakeLists.txt and sq_core below), never DuckDB's.

set(SQ_DUCKDB_DIR "${SQ_ENGINE_DIR}/duckdb-python/external/duckdb")

set(BUILD_UNITTESTS ON CACHE BOOL "DuckDB's unittest, the sqllogictest runner" FORCE)
# The runner alone: no C++ unit tests of DuckDB's, no shell, no benchmarks,
# and no sanitizers of DuckDB's own (its debug default).
set(ENABLE_UNITTEST_CPP_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_SHELL OFF CACHE BOOL "" FORCE)
set(BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(ENABLE_SANITIZER OFF CACHE BOOL "" FORCE)
set(ENABLE_UBSAN OFF CACHE BOOL "" FORCE)
# Only read with its sanitizer on; set, DuckDB does not warn about it.
set(DISABLE_VPTR_SANITIZER ON CACHE BOOL "" FORCE)
# Our extension, with its tests, and only the extensions it needs: DuckDB's
# base config loads parquet, json and icu on every build, which the tests do
# not use, so they are skipped. core_functions stays: DuckDB's SQL needs it.
set(
  DUCKDB_EXTENSION_CONFIGS
  "${SQ_ENGINE_DIR}/extension/sqlearn_config.cmake"
  CACHE STRING
  "The sqlearn extension (engine/sqllogic)"
  FORCE
)
set(SKIP_EXTENSIONS "parquet;json;icu" CACHE STRING "" FORCE)
set(STATICALLY_LINK_EXTENSIONS "core_functions;sqlearn" CACHE STRING "" FORCE)
# The version and commit DuckDB is built as, from the pins, as the wheel's.
set(OVERRIDE_GIT_DESCRIBE "${SQ_DUCKDB_TAG}")
set(GIT_COMMIT_HASH "${SQ_DUCKDB_COMMIT}")

add_subdirectory("${SQ_DUCKDB_DIR}" duckdb)

# DuckDB is added above with CMake's defaults; sq_core below is ours, with
# the flavour's levels alone (hardening.cmake).
sq_flavor_levels_only()

# DuckDB copies its compile_commands.json to .cache/clangd two levels above
# the build directory, which here is engine/, inside our tree: the target is
# left out of the build (a property of their target; their file is as it
# was).
if(TARGET clangd_cache)
  set_property(TARGET clangd_cache PROPERTY EXCLUDE_FROM_ALL TRUE)
endif()

# core::describe, which sqlearn_version() calls: in the wheel its objects are
# in _duckdb with the rest of ours; here they go into the extension's archive,
# which DuckDB links into its library.
list(TRANSFORM SQ_CORE_SOURCES PREPEND "${SQ_ENGINE_DIR}/" OUTPUT_VARIABLE sq_core_sources)
add_library(sq_core OBJECT ${sq_core_sources})
sq_target_options(sq_core)
sq_build_identity("${SQ_ENGINE_DIR}/src/core/version.cpp")
target_sources(sqlearn_extension PRIVATE $<TARGET_OBJECTS:sq_core>)

# The test: every file the runner takes under engine/extension/test/sql
# (.test, .test_slow, .test_coverage, at any depth; engine/cmake/
# sql_tests.cmake), never DuckDB's own suite. Every file under
# engine/extension/test (the `sql` task's inputs: the tests and any data file
# they read, at any depth) is a REQUIRED_FILES entry (sq_test_data), so the
# checks hash it and an edit to any reruns the label (validation/_ctest.py);
# the glob is read again at each configure, which every run of the checks
# does, so a new file joins it.
include("${SQ_ENGINE_DIR}/cmake/sql_tests.cmake")
sq_sql_test_files(sq_sql_tests "${SQ_ENGINE_DIR}/extension/test/sql")
sq_sql_test_data(sq_sql_test_data_files "${SQ_ENGINE_DIR}/extension/test")
if(NOT sq_sql_tests)
  message(
    FATAL_ERROR
    "No SQL test in ${SQ_ENGINE_DIR}/extension/test/sql/.\n"
    "Fix: add a sqllogictest file there, as sqlearn_version.test"
  )
endif()
# The runner works in engine/extension, where the pattern is read, and keeps
# its scratch files in the build directory, not in the source tree. A test
# whose `require sqlearn` finds no extension is skipped by default, so
# --require makes that a failure; and a pattern that matches no file exits 0
# with "No tests ran", which fails the test too.
add_test(
  NAME sqllogic
  COMMAND
    unittest --test-dir "${SQ_ENGINE_DIR}/extension" --temp-dir-root
    "${CMAKE_CURRENT_BINARY_DIR}/unittest_tempdir" --require sqlearn "test/sql/*"
)
set_tests_properties(sqllogic PROPERTIES LABELS sql FAIL_REGULAR_EXPRESSION "No tests ran")
sq_test_timeout(sqllogic)
sq_test_data(sqllogic ${sq_sql_test_data_files})

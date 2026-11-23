# sqlearn's engine: DuckDB's Python module built from the submodules, with
# sqlearn's C++ compiled into the same binary. scikit-build-core runs this
# (pyproject.toml, [tool.scikit-build]); nothing is fetched at configure time.
cmake_minimum_required(VERSION 3.29)

project(sqlearn LANGUAGES C CXX)

# Our targets are C++23 (spec §3.8); duckdb-python sets C++17 for its own and
# DuckDB's, inside its directory.
set(SQ_CXX_STANDARD 23)

# compile_commands.json for clang-tidy and the editors: it must be set at the
# top level, or the submodules' targets are left out of it.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(cmake/pins.cmake)
include(cmake/duckdb_package.cmake)
sq_check_pins()

# The version and commit DuckDB is built as, from the pins, not from git
# describe: _duckdb.__version__ and _duckdb.__git_revision__.
set(OVERRIDE_GIT_DESCRIBE "${SQ_DUCKDB_TAG}")
set(GIT_COMMIT_HASH "${SQ_DUCKDB_COMMIT}")

add_subdirectory(duckdb-python)

# Compile one of our object libraries into _duckdb, beside duckdb-python's
# own objects (the spike's mechanism). Each of ours is added with it once
# defined; none is yet.
function(sq_add_to_module target)
  target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:${target}>)
endfunction()

sq_install_duckdb_package("${CMAKE_CURRENT_SOURCE_DIR}/duckdb-python")

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

set(SQ_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
# The warnings our own targets compile with; theirs keep their own.
set(SQ_WARNINGS -Wall -Wextra -Werror)

# What the build is, compiled into core/version.cpp and the extension's
# version: sqlearn's version as scikit-build-core has it, DuckDB's from the
# pins, the compiler and the build type.
if(DEFINED SKBUILD_PROJECT_VERSION_FULL)
  set(SQ_SQLEARN_VERSION "${SKBUILD_PROJECT_VERSION_FULL}")
else()
  set(SQ_SQLEARN_VERSION "0+unknown")
endif()
string(REGEX REPLACE "^v" "" SQ_DUCKDB_VERSION "${SQ_DUCKDB_TAG}")

# The sqlearn extension, configured by DuckDB's own extension build and
# linked into _duckdb beside the official four. LINK_EXTENSIONS replaces
# duckdb-python's default list, so pyproject.toml repeats the four.
set(DUCKDB_EXTENSION_CONFIGS "${CMAKE_CURRENT_SOURCE_DIR}/extension/sqlearn_config.cmake")
if(NOT "sqlearn" IN_LIST LINK_EXTENSIONS)
  message(FATAL_ERROR
          "LINK_EXTENSIONS is \"${LINK_EXTENSIONS}\", without sqlearn: the module "
          "would have no sqlearn_version() and would download extensions.\n"
          "Fix: set LINK_EXTENSIONS to \"core_functions;json;parquet;icu;sqlearn\" "
          "in pyproject.toml's [tool.scikit-build.cmake.define]")
endif()

# The version and commit DuckDB is built as, from the pins, not from git
# describe: _duckdb.__version__ and _duckdb.__git_revision__.
set(OVERRIDE_GIT_DESCRIBE "${SQ_DUCKDB_TAG}")
set(GIT_COMMIT_HASH "${SQ_DUCKDB_COMMIT}")

add_subdirectory(duckdb-python)

# Their headers are system headers to our targets, so our warnings (as
# errors) cover our code and not theirs. Setting a property of their targets
# edits none of their files.
foreach(theirs IN ITEMS _duckdb_dependencies duckdb_target duckdb_static
                        nanobind-static-abi3 nanobind-static)
  if(TARGET ${theirs})
    set_property(TARGET ${theirs} PROPERTY SYSTEM TRUE)
  endif()
endforeach()

# Compile one of our object libraries into _duckdb, beside duckdb-python's
# own objects (the spike's mechanism). Each of ours is added with it once
# defined.
function(sq_add_to_module target)
  target_sources(_duckdb PRIVATE $<TARGET_OBJECTS:${target}>)
endfunction()

# An object library of ours: C++23, hidden symbols (the module exports
# DuckDB's), our warnings, built against DuckDB's and nanobind's headers
# through duckdb-python's interface target (which carries NB_DOMAIN=duckdb).
function(sq_object_library target)
  add_library(${target} OBJECT ${ARGN})
  set_target_properties(
    ${target}
    PROPERTIES CXX_STANDARD ${SQ_CXX_STANDARD}
               CXX_STANDARD_REQUIRED ON
               CXX_EXTENSIONS OFF
               CXX_VISIBILITY_PRESET hidden
               VISIBILITY_INLINES_HIDDEN ON
               POSITION_INDEPENDENT_CODE ON)
  target_include_directories(${target} PRIVATE "${SQ_ENGINE_DIR}/src")
  target_link_libraries(${target} PRIVATE _duckdb_dependencies)
  target_compile_options(${target} PRIVATE ${SQ_WARNINGS})
  sq_add_to_module(${target})
endfunction()

sq_object_library(sq_core src/core/error.cpp src/core/version.cpp)
# On this file alone, so a new version recompiles only it.
set_source_files_properties(
  src/core/version.cpp
  PROPERTIES COMPILE_DEFINITIONS
             "SQ_SQLEARN_VERSION=\"${SQ_SQLEARN_VERSION}\";SQ_DUCKDB_VERSION=\"${SQ_DUCKDB_VERSION}\";SQ_DUCKDB_COMMIT=\"${SQ_DUCKDB_COMMIT}\";SQ_COMPILER=\"${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}\";SQ_BUILD_TYPE=\"${CMAKE_BUILD_TYPE}\""
)
sq_object_library(sq_bindings src/bindings/module.cpp src/bindings/connection.cpp)

sq_install_duckdb_package("${CMAKE_CURRENT_SOURCE_DIR}/duckdb-python")

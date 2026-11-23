# The sqlearn DuckDB extension: its SQL functions and its load-time settings.
# DuckDB's build adds this directory (sqlearn_config.cmake); the archive is
# linked into _duckdb only, so no loadable .duckdb_extension is made.
cmake_minimum_required(VERSION 3.29)

project(SqlearnExtension LANGUAGES CXX)

build_static_extension(sqlearn src/sqlearn_extension.cpp)
set_target_properties(
  sqlearn_extension
  PROPERTIES CXX_STANDARD ${SQ_CXX_STANDARD}
             CXX_STANDARD_REQUIRED ON
             CXX_EXTENSIONS OFF
             CXX_VISIBILITY_PRESET hidden
             VISIBILITY_INLINES_HIDDEN ON)
# DuckDB's directories give this target their headers as ordinary include
# directories; as system ones instead, our warnings (as errors) cover our
# code and not theirs.
get_target_property(sq_duckdb_includes sqlearn_extension INCLUDE_DIRECTORIES)
set_property(TARGET sqlearn_extension PROPERTY INCLUDE_DIRECTORIES "")
target_include_directories(sqlearn_extension SYSTEM PRIVATE ${sq_duckdb_includes})
# core/version.hpp: core::describe is compiled into _duckdb with the rest of
# sqlearn's objects, and this archive resolves it there at the link.
target_include_directories(sqlearn_extension PRIVATE "${SQ_ENGINE_DIR}/src")
target_compile_options(sqlearn_extension PRIVATE ${SQ_WARNINGS})

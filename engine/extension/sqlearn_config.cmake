# Read by DuckDB's extension_build_tools.cmake, through DUCKDB_EXTENSION_CONFIGS
# (engine/CMakeLists.txt): the sqlearn extension, built from this directory
# and statically linked into _duckdb, so every database has it. Its version
# is sqlearn's, never git describe of this checkout.
duckdb_extension_load(sqlearn
    SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}"
    EXTENSION_VERSION "${SQ_SQLEARN_VERSION}"
)

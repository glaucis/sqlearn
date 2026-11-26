# Read by DuckDB's extension_build_tools.cmake, through DUCKDB_EXTENSION_CONFIGS
# (engine/CMakeLists.txt): the sqlearn extension, built from this directory
# and statically linked into _duckdb, so every database has it. Its version
# is sqlearn's, never git describe of this checkout. LOAD_TESTS registers
# its test/sql directory with DuckDB's unittest, which only the sqllogic
# preset builds (engine/sqllogic); the wheel builds no unittest.
duckdb_extension_load(sqlearn
    SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}"
    LOAD_TESTS
    EXTENSION_VERSION "${SQ_SQLEARN_VERSION}"
)

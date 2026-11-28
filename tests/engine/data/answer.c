/* An extension a user could build and install themselves: one SQL
 * function, sqlearn_test_answer(), returning 42. It uses DuckDB's C
 * extension API, which hands the extension DuckDB's functions at load, so
 * it links nothing of DuckDB's and loads into sqlearn's DuckDB as into any.
 * tests/engine/test_extension.py compiles it and appends DuckDB's footer. */
#include "duckdb_extension.h"

DUCKDB_EXTENSION_EXTERN

static void answer(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    (void)info;
    idx_t rows = duckdb_data_chunk_get_size(input);
    int32_t *out = (int32_t *)duckdb_vector_get_data(output);
    for (idx_t i = 0; i < rows; i++) {
        out[i] = 42;
    }
}

DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection connection, duckdb_extension_info info,
                            struct duckdb_extension_access *access) {
    (void)info;
    (void)access;
    duckdb_scalar_function function = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(function, "sqlearn_test_answer");
    duckdb_logical_type integer = duckdb_create_logical_type(DUCKDB_TYPE_INTEGER);
    duckdb_scalar_function_set_return_type(function, integer);
    duckdb_destroy_logical_type(&integer);
    duckdb_scalar_function_set_function(function, answer);
    duckdb_state state = duckdb_register_scalar_function(connection, function);
    duckdb_destroy_scalar_function(&function);
    return state == DuckDBSuccess;
}

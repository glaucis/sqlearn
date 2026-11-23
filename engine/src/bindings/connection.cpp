/// @file
/// The functions of sqlearn._native that take a user's DuckDB connection
/// and reach the C++ connection behind it.
#include "bindings/guard.hpp"
#include "core/expects.hpp"

#include "duckdb.hpp"
#include "duckdb/common/sql_identifier.hpp"
#include "duckdb_python/pyconnection/pyconnection.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/string.h>

#include <cstdint>
#include <format>
#include <memory>
#include <string>

namespace nb = nanobind;

namespace {

/// Count the rows of `table` on the database behind `con`, through DuckDB's
/// C++ API, under the connection's own lock.
/// @param con The user's connection, or a cursor of it.
/// @param table The table's name, unquoted.
/// @return The table's row count.
std::int64_t count_rows(duckdb::DuckDBPyConnection &con, const std::string &table) {
    return sq::bindings::guarded([&]() -> std::int64_t {
        SQ_EXPECTS(!table.empty());
        const duckdb::DuckDBPyConnection::ConnectionLockGuard lock(con);
        auto &connection = con.con.GetConnection();
        const auto sql = std::format("SELECT count(*) FROM {}", duckdb::SQLIdentifier::ToString(table));
        const nb::gil_scoped_release release;
        auto result = connection.Query(sql);
        if (result->HasError()) {
            result->ThrowError(); // DuckDB's own exception, through its translators
        }
        auto chunk = result->Fetch();
        if (!chunk || chunk->size() != 1) {
            throw sq::core::Error(std::format("SELECT count(*) FROM {} returned no row", table),
                                  "a count returns one row, so DuckDB answered what sqlearn "
                                  "did not expect, which is a bug in sqlearn",
                                  "please report it at https://github.com/glaucis/sqlearn/issues "
                                  "with this message");
        }
        return chunk->GetValue(0, 0).GetValue<std::int64_t>();
    });
}

/// Return `con` itself, through C++ and back.
/// @param con The user's connection.
/// @return The same Python object.
std::shared_ptr<duckdb::DuckDBPyConnection> roundtrip(std::shared_ptr<duckdb::DuckDBPyConnection> con) {
    return con;
}

} // namespace

namespace sq::bindings {

void add_connection(nb::module_ &m) {
    m.def("count_rows", &count_rows, nb::arg("con"), nb::arg("table"),
          "Count the rows of `table` through DuckDB's C++ API, on the database behind\n"
          "`con`.");
    m.def("roundtrip", &roundtrip, nb::arg("con"),
          "Return `con` itself, after it crossed into C++ and back.");
}

} // namespace sq::bindings

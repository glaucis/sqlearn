/// @file
/// The core group's build identity and its one line.
#include "core/version.hpp"

#include <catch2/catch_test_macros.hpp>

#include <string>

TEST_CASE("describe gives the build identity in one line", "[core]") {
    const auto identity = sq::core::build_identity();
    const auto line = sq::core::describe(identity);
    CHECK(line.starts_with("sqlearn " + identity.sqlearn_version + ", DuckDB " +
                           identity.duckdb_version + " ("));
    CHECK(line.find(identity.duckdb_commit.substr(0, 10)) != std::string::npos);
    CHECK(line.ends_with(identity.compiler + ", " + identity.build_type));
    CHECK(line.find('\n') == std::string::npos);
}

TEST_CASE("build_identity may throw, so a failed allocation is std::bad_alloc", "[core]") {
    // Its five strings allocate: under noexcept a std::bad_alloc would end
    // the process (ADR 0065); without it the bindings pass it to Python as
    // MemoryError.
    STATIC_CHECK_FALSE(noexcept(sq::core::build_identity()));
}

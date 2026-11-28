/// @file
/// The build identity, from the header engine/CMakeLists.txt writes into
/// the build directory for this file alone (sq_build_identity), so a new
/// version recompiles only it.
#include "core/version.hpp"

#include "build_identity.hpp"

#include <cstddef>
#include <format>
#include <string>

namespace sq::core {

namespace {

/// How many hex digits of DuckDB's commit describe() shows.
constexpr std::size_t commit_digits = 10;

} // namespace

BuildIdentity build_identity() {
    return {SQ_SQLEARN_VERSION, SQ_DUCKDB_VERSION, SQ_DUCKDB_COMMIT,
            SQ_COMPILER,        SQ_BUILD_TYPE,     SQ_TARGET};
}

std::string describe(const BuildIdentity &identity) {
    return std::format("sqlearn {}, DuckDB {} ({}), {}, {}, {}", identity.sqlearn_version,
                       identity.duckdb_version, identity.duckdb_commit.substr(0, commit_digits),
                       identity.compiler, identity.build_type, identity.target);
}

} // namespace sq::core

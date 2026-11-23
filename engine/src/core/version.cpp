/// @file
/// The build identity, from the definitions engine/CMakeLists.txt sets on
/// this file alone, so a new version recompiles only it.
#include "core/version.hpp"

#include <format>

#if !defined(SQ_SQLEARN_VERSION) || !defined(SQ_DUCKDB_VERSION) || !defined(SQ_DUCKDB_COMMIT) ||  \
    !defined(SQ_COMPILER) || !defined(SQ_BUILD_TYPE)
#error "engine/CMakeLists.txt defines the build identity on this file"
#endif

namespace sq::core {

BuildIdentity build_identity() noexcept {
    return {SQ_SQLEARN_VERSION, SQ_DUCKDB_VERSION, SQ_DUCKDB_COMMIT, SQ_COMPILER, SQ_BUILD_TYPE};
}

std::string describe(const BuildIdentity &identity) {
    return std::format("sqlearn {}, DuckDB {} ({}), {}, {}", identity.sqlearn_version,
                       identity.duckdb_version, identity.duckdb_commit.substr(0, 10),
                       identity.compiler, identity.build_type);
}

} // namespace sq::core

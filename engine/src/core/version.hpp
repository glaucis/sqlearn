/// @file
/// What sqlearn's engine was built as: its version, DuckDB's, the compiler.
#pragma once

#include <string>

namespace sq::core {

/// The identity of this build of the engine, fixed when it was compiled.
struct BuildIdentity {
    std::string sqlearn_version; ///< sqlearn's version, as its wheel has it.
    std::string duckdb_version;  ///< DuckDB's version, without a leading "v".
    std::string duckdb_commit;   ///< The DuckDB commit the build is pinned to.
    std::string compiler;        ///< The C++ compiler's name and version.
    std::string build_type;      ///< The CMake build type, such as Release.
    std::string target;          ///< The system and processor, such as "Darwin arm64".
};

/// Return this build's identity.
/// @return The values CMake compiled in.
/// @throws std::bad_alloc when there is no memory for its strings.
[[nodiscard]] BuildIdentity build_identity();

/// Describe a build in one line.
/// @param identity The build to describe.
/// @return "sqlearn <version>, DuckDB <version> (<commit[:10]>), <compiler>,
///         <build type>".
[[nodiscard]] std::string describe(const BuildIdentity &identity);

} // namespace sq::core

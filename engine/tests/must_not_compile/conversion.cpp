/// @file
/// Must not compile under sqlearn's warnings: an implicit narrowing from a
/// 64-bit to a 32-bit integer, which -Wconversion refuses. It compiles
/// cleanly without that flag (the control target, engine/tests/CMakeLists.txt).
#include <cstdint>

namespace sq::must_not_compile {

/// Return `wide` as a 32-bit integer, narrowed implicitly.
/// @param wide Any 64-bit integer.
/// @return Its low 32 bits.
std::int32_t narrow(std::int64_t wide);

std::int32_t narrow(std::int64_t wide) {
    return wide;
}

} // namespace sq::must_not_compile

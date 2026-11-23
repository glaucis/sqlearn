/// @file
/// Must not compile under sqlearn's warnings: a span of a temporary Buffer
/// kept past the end of the statement, which -Wdangling refuses because
/// Buffer::span() is [[clang::lifetimebound]]. It compiles cleanly without
/// that flag (the control target, engine/tests/CMakeLists.txt).
#include "raw/buffer.hpp"

#include <cstddef>

namespace sq::must_not_compile {

/// Return how many elements a span of a buffer that is already gone holds.
/// @return 4, read from a dangling span.
std::size_t dangling();

std::size_t dangling() {
    const auto elements = raw::Buffer<double>(4).span();
    return elements.size();
}

} // namespace sq::must_not_compile

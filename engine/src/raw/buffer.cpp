/// @file
/// The raw layer's allocation: the one place sqlearn's C++ calls operator
/// new and delete itself (ADR 0065).
#include "raw/buffer.hpp"

#include <cstddef>
#include <new>

namespace sq::raw::detail {

void *allocate_aligned(std::size_t bytes) {
    return ::operator new(bytes, std::align_val_t{buffer_alignment});
}

void free_aligned(void *memory) noexcept {
    ::operator delete(memory, std::align_val_t{buffer_alignment});
}

} // namespace sq::raw::detail

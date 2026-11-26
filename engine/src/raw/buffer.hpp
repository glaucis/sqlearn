/// @file
/// Buffer, an owned run of elements on a 64-byte boundary: the one owner of
/// raw memory in sqlearn's C++ (ADR 0065). Every other group reads and
/// writes it through the std::span it gives, so no code outside
/// engine/src/raw/ allocates, frees or does arithmetic on a pointer.
#pragma once

#include "core/expects.hpp"

#include <cstddef>
#include <limits>
#include <memory>
#include <span>
#include <type_traits>
#include <utility>

/// [[clang::lifetimebound]] where the compiler has it: a value returned from
/// a function marked with it must not outlive the object it was called on,
/// and -Wdangling (an error under sqlearn's warnings) refuses code where it
/// would. Other compilers get nothing.
#if defined(__has_cpp_attribute)
#if __has_cpp_attribute(clang::lifetimebound)
#define SQ_LIFETIMEBOUND [[clang::lifetimebound]]
#endif
#endif
#ifndef SQ_LIFETIMEBOUND
#define SQ_LIFETIMEBOUND
#endif

namespace sq::raw {

/// The boundary every Buffer starts on: a cache line on Apple silicon and
/// x86-64, and the width the vector kernels load.
inline constexpr std::size_t buffer_alignment = 64;

namespace detail {

/// Allocate `bytes` bytes on a buffer_alignment boundary.
/// @param bytes How many bytes; 0 gives a unique pointer to no bytes, which
///        free_aligned frees like any other (Buffer allocates nothing for
///        no elements and never asks for 0).
/// @return The memory, uninitialised; std::bad_alloc when there is none.
[[nodiscard]] void *allocate_aligned(std::size_t bytes);

/// Free memory allocate_aligned gave.
/// @param memory What allocate_aligned returned, or null.
void free_aligned(void *memory) noexcept;

/// The deleter of a Buffer's std::unique_ptr: free_aligned.
struct FreeAligned {
    /// Free the memory `memory` points to.
    /// @param memory What allocate_aligned returned, or null.
    void operator()(void *memory) const noexcept { free_aligned(memory); }
};

} // namespace detail

/// An owned run of `size()` elements of `T`, each set to `T{}`, starting on
/// a 64-byte boundary. Move-only; a moved-from Buffer is empty. A Buffer of
/// no elements owns no memory.
///
/// `T` is a trivial type (numbers, plain structs of them): its elements
/// need no destructor, and setting one is a store.
/// @tparam T The element type.
template <class T> class Buffer {
    static_assert(std::is_trivially_default_constructible_v<T> &&
                      std::is_trivially_destructible_v<T> && std::is_trivially_copyable_v<T>,
                  "Buffer holds trivial types only");
    static_assert(!std::is_const_v<T> && !std::is_volatile_v<T>,
                  "Buffer<T> owns its elements: use std::span<const T> for a read-only view");
    static_assert(alignof(T) <= buffer_alignment, "T is aligned past 64 bytes");

public:
    /// Allocate `n` elements, each set to `T{}`.
    /// @param n How many elements; 0 allocates nothing.
    /// @throws sq::core::PreconditionError when `n` elements of T are more
    ///         bytes than a std::size_t counts.
    /// @throws std::bad_alloc when the memory is not there.
    explicit Buffer(std::size_t n) : size_(n) {
        SQ_EXPECTS(n <= std::numeric_limits<std::size_t>::max() / sizeof(T));
        if (n == 0) {
            return;
        }
        data_.reset(static_cast<T *>(detail::allocate_aligned(n * sizeof(T))));
        std::uninitialized_value_construct_n(data_.get(), n);
    }

    /// Not copyable: a Buffer is the one owner of its memory.
    Buffer(const Buffer &) = delete;
    /// Not copyable: a Buffer is the one owner of its memory.
    Buffer &operator=(const Buffer &) = delete;

    /// Take `other`'s memory, leaving it empty.
    /// @param other The buffer to move from.
    Buffer(Buffer &&other) noexcept
        : data_(std::move(other.data_)), size_(std::exchange(other.size_, 0)) {}

    /// Free this buffer's memory and take `other`'s, leaving it empty.
    /// @param other The buffer to move from.
    /// @return This buffer.
    Buffer &operator=(Buffer &&other) noexcept {
        data_ = std::move(other.data_);
        size_ = std::exchange(other.size_, 0);
        return *this;
    }

    /// Free the memory.
    ~Buffer() = default;

// The two views below pair the pointer with the count this class keeps, the
// one place a span is made from a raw pointer. This header is compiled into
// every group that holds a Buffer, so the raw layer's exemption from
// -Wunsafe-buffer-usage is marked here, in the source, around these lines
// alone; the rest of each including file keeps the warning.
#if defined(__clang__)
#pragma clang unsafe_buffer_usage begin
#endif
    /// Return the elements to read and write. The view must not outlive the
    /// buffer (SQ_LIFETIMEBOUND).
    /// @return A view of all `size()` elements; empty for an empty buffer.
    [[nodiscard]] std::span<T> span() noexcept SQ_LIFETIMEBOUND { return {data_.get(), size_}; }

    /// Return the elements to read. The view must not outlive the buffer
    /// (SQ_LIFETIMEBOUND).
    /// @return A read-only view of all `size()` elements.
    [[nodiscard]] std::span<const T> span() const noexcept SQ_LIFETIMEBOUND {
        return {data_.get(), size_};
    }
#if defined(__clang__)
#pragma clang unsafe_buffer_usage end
#endif

    /// Return how many elements there are.
    /// @return The count the buffer was made with, 0 once moved from.
    [[nodiscard]] std::size_t size() const noexcept { return size_; }

private:
    std::unique_ptr<T, detail::FreeAligned> data_;
    std::size_t size_;
};

} // namespace sq::raw

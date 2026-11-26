/// @file
/// FixedText: text of at most N bytes in place, always NUL-terminated,
/// built by appending, allocating nothing and taking no lock, so a signal
/// handler may build a path or a line with it (the crash report). The
/// writing into its array is the raw layer's (fixed_text.cpp, ADR 0065).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace sq::raw {

/// The bases FixedText writes numbers in.
inline constexpr int decimal_base = 10;
inline constexpr int hex_base = 16; ///< As decimal_base.

namespace detail {

/// Append `text` to the `size` bytes of text in `storage`, as much as fits
/// before its last byte, and NUL-terminate it. Async-signal-safe.
/// @param storage The text's bytes and room for its NUL; not empty.
/// @param size How many bytes of text it holds now, below storage.size().
/// @param text What to append.
/// @param truncated Set to true when not all of `text` fitted.
/// @return The text's new size.
std::size_t append_text(std::span<char> storage, std::size_t size, std::string_view text,
                        bool &truncated) noexcept;

/// Append `value`'s digits in `base` as append_text appends text.
/// @param storage As for append_text.
/// @param size As for append_text.
/// @param value The number.
/// @param base decimal_base or hex_base; another appends nothing and sets
///        `truncated`.
/// @param truncated Set to true when not all its digits fitted.
/// @return The text's new size.
std::size_t append_number(std::span<char> storage, std::size_t size, std::uintmax_t value, int base,
                          bool &truncated) noexcept;

} // namespace detail

/// Up to N bytes of text and a NUL. An append that does not fit appends
/// what fits and marks the text truncated; every member is
/// async-signal-safe.
/// @tparam N The most bytes it holds, the NUL aside.
template <std::size_t N> class FixedText {
    static_assert(N > 0, "FixedText holds at least one byte");

public:
    /// Append `text`, or as much of it as fits.
    /// @param text The bytes.
    /// @return This text, for the next append.
    FixedText &append(std::string_view text) noexcept {
        size_ = detail::append_text(bytes_, size_, text, truncated_);
        return *this;
    }

    /// Append `value` in `base`, without a prefix.
    /// @param value The number.
    /// @param base decimal_base or hex_base.
    /// @return This text.
    FixedText &append_number(std::uintmax_t value, int base = decimal_base) noexcept {
        size_ = detail::append_number(bytes_, size_, value, base, truncated_);
        return *this;
    }

    /// The text, without its NUL.
    /// @return A view of it, valid while this FixedText lives unchanged.
    [[nodiscard]] std::string_view view() const noexcept { return {bytes_.data(), size_}; }

    /// The text, NUL-terminated, for a system call such as open(2).
    /// @return Its first byte.
    [[nodiscard]] const char *c_str() const noexcept { return bytes_.data(); }

    /// Whether an append did not fit.
    /// @return True once one was cut short.
    [[nodiscard]] bool truncated() const noexcept { return truncated_; }

private:
    std::array<char, N + 1> bytes_{};
    std::size_t size_ = 0;
    bool truncated_ = false;
};

} // namespace sq::raw

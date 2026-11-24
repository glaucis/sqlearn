/// @file
/// FixedText's appends: copying into its array, the raw layer's work.
#include "raw/fixed_text.hpp"

#include <array>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>
#include <system_error>

namespace sq::raw::detail {

namespace {

/// Room for a std::uintmax_t's digits: 2^64 has 20 decimal digits and 16
/// hexadecimal ones.
constexpr std::size_t max_digits = 24;

} // namespace

std::size_t append_text(std::span<char> storage, std::size_t size, std::string_view text,
                        bool &truncated) noexcept {
    const std::size_t room = storage.size() - 1 - size;
    const std::size_t count = text.size() < room ? text.size() : room;
    for (std::size_t i = 0; i < count; ++i) {
        storage[size + i] = text[i];
    }
    size += count;
    storage[size] = '\0';
    if (count < text.size()) {
        truncated = true;
    }
    return size;
}

std::size_t append_number(std::span<char> storage, std::size_t size, std::uintmax_t value, int base,
                          bool &truncated) noexcept {
    if (base != decimal_base && base != hex_base) {
        truncated = true;
        return size;
    }
    std::array<char, max_digits> digits{};
    // max_digits holds any std::uintmax_t in either base, so this never
    // fails; were it to, it would append nothing.
    const auto [end, error] =
        std::to_chars(digits.data(), digits.data() + digits.size(), value, base);
    const auto count = error == std::errc{} ? static_cast<std::size_t>(end - digits.data()) : 0;
    return append_text(storage, size, std::string_view(digits.data(), count), truncated);
}

} // namespace sq::raw::detail

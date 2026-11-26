/// @file
/// FdWriter: write(2), retried on EINTR and on a short write.
#include "raw/fd_writer.hpp"

#include "raw/fixed_text.hpp"

#include <sys/types.h>
#include <unistd.h>

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace sq::raw {

namespace {

/// Room for a number's text: "0x" and a std::uintmax_t's 20 digits at most.
constexpr std::size_t number_room = 24;

} // namespace

void FdWriter::put(const char *bytes, std::size_t size) noexcept {
    while (ok_ && size > 0) {
        const ssize_t wrote = ::write(fd_, bytes, size);
        if (wrote < 0 && errno == EINTR) {
            continue;
        }
        if (wrote <= 0) {
            ok_ = false;
            return;
        }
        const auto count = static_cast<std::size_t>(wrote);
        bytes += count;
        size -= count;
    }
}

FdWriter &FdWriter::text(std::string_view text) noexcept {
    put(text.data(), text.size());
    return *this;
}

FdWriter &FdWriter::hex(std::uintptr_t value) noexcept {
    FixedText<number_room> digits;
    digits.append("0x").append_number(value, hex_base);
    return text(digits.view());
}

FdWriter &FdWriter::decimal(std::uintmax_t value) noexcept {
    FixedText<number_room> digits;
    digits.append_number(value);
    return text(digits.view());
}

FdWriter &FdWriter::decimal(int value) noexcept {
    if (value < 0) {
        text("-");
        // The magnitude of INT_MIN does not fit an int, but does fit here.
        return decimal(static_cast<std::uintmax_t>(-static_cast<std::intmax_t>(value)));
    }
    return decimal(static_cast<std::uintmax_t>(value));
}

} // namespace sq::raw

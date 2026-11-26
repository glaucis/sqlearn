/// @file
/// FdWriter: text and numbers written straight to a file descriptor with
/// write(2), allocating nothing and taking no lock, so a signal handler may
/// use it (the crash report, engine/src/crash/). It formats into its own
/// small buffer, hence its place in the raw layer (ADR 0065).
#pragma once

#include <cstddef>
#include <cstdint>
#include <string_view>

namespace sq::raw {

/// Writes to one file descriptor, every call async-signal-safe: write(2)
/// alone, retried on EINTR and on a short write. A failed write stops every
/// later one; ok() says whether all went through.
class FdWriter {
public:
    /// Write to `fd`, which the caller owns and closes.
    /// @param fd An open file descriptor.
    explicit FdWriter(int fd) noexcept : fd_(fd) {}

    /// Write `text` as it is.
    /// @param text The bytes.
    /// @return This writer, for the next call.
    FdWriter &text(std::string_view text) noexcept;

    /// Write `value` as "0x" and its lowercase hexadecimal digits.
    /// @param value The number.
    /// @return This writer.
    FdWriter &hex(std::uintptr_t value) noexcept;

    /// Write `value` in decimal.
    /// @param value The number.
    /// @return This writer.
    FdWriter &decimal(std::uintmax_t value) noexcept;

    /// Write `value` in decimal, with its sign.
    /// @param value The number.
    /// @return This writer.
    FdWriter &decimal(int value) noexcept;

    /// Whether every write so far went through.
    /// @return False after the first failed write.
    [[nodiscard]] bool ok() const noexcept { return ok_; }

private:
    /// Write `size` bytes from `bytes`, all of them or fail.
    /// @param bytes The first byte.
    /// @param size How many.
    void put(const char *bytes, std::size_t size) noexcept;

    int fd_;
    bool ok_ = true;
};

} // namespace sq::raw

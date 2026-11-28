/// @file
/// The alternate signal stack: memory a signal handler runs on instead of
/// the thread's own stack, so a handler still runs when that stack is
/// used up (a stack overflow). Handing memory to the system is the raw
/// layer's work (ADR 0065).
#pragma once

#include <cstddef>
#include <span>

namespace sq::raw {

/// Give the calling thread `spare` as its alternate signal stack, unless it
/// has one already of at least `enough` bytes (Python's faulthandler and
/// AddressSanitizer install their own), which it keeps. Not
/// async-signal-safe: call it before a handler needs it.
/// @param spare The memory, which must outlive the thread's use of it.
/// @param enough The smallest stack already in place that is kept.
/// @return True when the thread has an alternate signal stack now.
[[nodiscard]] bool use_signal_stack(std::span<std::byte> spare, std::size_t enough) noexcept;

} // namespace sq::raw

/// @file
/// The alternate signal stack, through sigaltstack(2).
#include "raw/signal_stack.hpp"

#include <csignal>
#include <cstddef>
#include <span>

namespace sq::raw {

bool use_signal_stack(std::span<std::byte> spare, std::size_t enough) noexcept {
    stack_t current{};
    if (::sigaltstack(nullptr, &current) == 0 &&
        (static_cast<unsigned>(current.ss_flags) & static_cast<unsigned>(SS_DISABLE)) == 0 &&
        current.ss_size >= enough) {
        return true;
    }
    stack_t stack{};
    stack.ss_sp = spare.data();
    stack.ss_size = spare.size();
    stack.ss_flags = 0;
    return ::sigaltstack(&stack, nullptr) == 0;
}

} // namespace sq::raw

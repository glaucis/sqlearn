/// @file
/// The raw layer's demangling: the one place sqlearn's C++ frees memory the
/// C++ runtime allocated with malloc (ADR 0065).
#include "raw/demangle.hpp"

#include <cxxabi.h>

#include <cstdlib>
#include <memory>
#include <string>

namespace sq::raw {

namespace {

/// The deleter of __cxa_demangle's text: std::free, as its contract asks.
struct FreeText {
    void operator()(char *text) const noexcept {
        // The runtime mallocs the text, and only free may release it.
        // NOLINTNEXTLINE(cppcoreguidelines-no-malloc,cppcoreguidelines-owning-memory)
        std::free(text);
    }
};

} // namespace

std::string demangle(const char *mangled) {
    // No buffer and no status: __cxa_demangle allocates the text, and gives
    // null when the name does not demangle.
    const std::unique_ptr<char, FreeText> text{
        abi::__cxa_demangle(mangled, nullptr, nullptr, nullptr)};
    if (text == nullptr) {
        return mangled;
    }
    return text.get();
}

} // namespace sq::raw

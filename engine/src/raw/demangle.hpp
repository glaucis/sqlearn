/// @file
/// demangle: a C++ type's name as its source spells it, from the mangled
/// name typeid gives. The C++ runtime allocates the text with malloc and the
/// caller frees it, hence its place in the raw layer (ADR 0065).
#pragma once

#include <string>

namespace sq::raw {

/// Return the demangled form of `mangled`, a type's name as
/// std::type_info::name() gives it (`St13runtime_error` becomes
/// `std::runtime_error`), or `mangled` itself when it does not demangle.
/// It allocates, so it is not for a signal handler.
/// @param mangled A NUL-terminated mangled name.
/// @return The name a reader knows the type by.
/// @throws std::bad_alloc when there is no memory for the text.
[[nodiscard]] std::string demangle(const char *mangled);

} // namespace sq::raw

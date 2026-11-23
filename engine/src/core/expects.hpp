/// @file
/// SQ_EXPECTS, the one way sqlearn's C++ states a precondition.
#pragma once

// What SQ_EXPECTS expands to, so a file that uses it includes this alone.
#include "core/error.hpp" // IWYU pragma: export

#include <source_location> // IWYU pragma: export
#include <string_view>     // IWYU pragma: export

/// Throw sq::core::PreconditionError, carrying the condition's text and
/// where it was checked, when `cond` is false. On in every build.
#define SQ_EXPECTS(cond)                                                                           \
    do {                                                                                           \
        if (!(cond)) [[unlikely]] {                                                                \
            throw ::sq::core::PreconditionError(#cond, std::source_location::current());           \
        }                                                                                          \
    } while (false)

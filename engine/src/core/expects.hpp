/// @file
/// SQ_EXPECTS, the one way sqlearn's C++ states a precondition.
#pragma once

#include "core/error.hpp"

#include <source_location>

/// Throw sq::core::PreconditionError, carrying the condition's text and
/// where it was checked, when `cond` is false. On in every build.
#define SQ_EXPECTS(cond)                                                                           \
    do {                                                                                           \
        if (!(cond)) [[unlikely]] {                                                                \
            throw ::sq::core::PreconditionError(#cond, std::source_location::current());          \
        }                                                                                          \
    } while (false)

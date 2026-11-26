/// @file
/// The property the version parser keeps for every text, one place for the
/// fuzz target (libFuzzer's inputs) and the replay (the kept corpus).
#pragma once

#include "core/parse_version.hpp"

#include <expected>
#include <string_view>

namespace sq::fuzz {

/// Parse `text`; when it is a version, write it and parse that text: the
/// result must succeed and be the same version. The property is on the
/// version and not on the text, because format() normalises ("0.1.dev5" is
/// written "0.1.0.dev5"). A text that is no version holds the property.
/// @param text Any bytes.
/// @return False when a version did not survive writing and reading again.
[[nodiscard]] inline bool round_trips(std::string_view text) {
    const auto parsed = core::parse_version(text);
    if (!parsed) {
        return true;
    }
    const auto again = core::parse_version(core::format(*parsed));
    return again && *again == *parsed;
}

} // namespace sq::fuzz

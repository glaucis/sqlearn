/// @file
/// Versions as sqlearn and DuckDB write them: a subset of PEP 440, read and
/// written back.
///
/// The grammar parse_version accepts, and nothing else:
///
///     version  := number "." number [ "." number ] [ ".dev" number [ "+" local ] ]
///     number   := "0" | [1-9][0-9]*            (at most INT_MAX)
///     local    := segment ( "." segment )*
///     segment  := [a-z0-9]+
///
/// so "2.0.1", "1.0.0", "0.1.dev597" and "0.1.dev667+g136548be1" (what
/// sq.__version__ shows) are versions, and a leading "v", a fourth release
/// number, a pre-release ("rc1"), a post-release, a local label on a final
/// release, upper case and leading zeros are not. A missing patch number is
/// 0, as PEP 440 pads a release with zeros: "0.1.dev597" and "0.1.0.dev597"
/// are the same version.
#pragma once

#include <cstddef>
#include <cstdint>
#include <expected>
#include <string>
#include <string_view>

namespace sq::core {

/// A version in parse_version's subset of PEP 440.
///
/// It is valid when each number is from 0 to INT_MAX and `pre` is empty (a
/// final release) or "dev<N>" or "dev<N>+<local>", with N and local as the
/// file's grammar has them. format() writes every valid version as text
/// parse_version reads back to it.
struct Version {
    int major = 0;   ///< The first release number.
    int minor = 0;   ///< The second release number.
    int patch = 0;   ///< The third release number, 0 when the text has none.
    std::string pre; ///< The dev part and its local label after the release
                     ///< numbers, without the "." before it, such as "dev597"
                     ///< or "dev667+g136548be1"; empty for a final release.

    /// Compare two versions member by member.
    /// @param other The version to compare with.
    /// @return True when every member is equal.
    bool operator==(const Version &other) const = default;
};

/// Why parse_version refused a text, and where.
struct ParseError {
    /// What was wrong.
    enum class Kind : std::uint8_t {
        empty,            ///< The text is empty.
        expected_number,  ///< A number is missing where the grammar needs one.
        leading_zero,     ///< A number other than 0 starts with 0.
        number_too_large, ///< A number is larger than INT_MAX.
        unexpected_text,  ///< Text the grammar has no place for.
        bad_local,        ///< The local label after "+" is empty, has an empty
                          ///< segment, or a character outside [a-z0-9.].
    };

    Kind kind;          ///< What was wrong.
    std::size_t offset; ///< Where in the text, counted in bytes from 0.

    /// Compare two errors member by member.
    /// @param other The error to compare with.
    /// @return True when kind and offset are equal.
    bool operator==(const ParseError &other) const = default;
};

/// Read a version in the file's subset of PEP 440.
/// @param text The whole text: nothing may come before or after the version.
/// @return The version, or why and where the text is not one.
/// @throws std::bad_alloc when there is no memory to copy the dev part into
///         the version's `pre`; a text that is no version is never an
///         exception.
[[nodiscard]] std::expected<Version, ParseError> parse_version(std::string_view text);

/// Write a version as text: "MAJOR.MINOR.PATCH", then "." and `pre` when
/// `pre` is not empty. The patch number is always written, so this is not
/// always the text the version was read from: "0.1.dev597" is written
/// "0.1.0.dev597", the same version (PEP 440 pads a release with zeros).
/// @param version A valid version (see Version).
/// @return The text, which parse_version reads back to `version`.
[[nodiscard]] std::string format(const Version &version);

} // namespace sq::core

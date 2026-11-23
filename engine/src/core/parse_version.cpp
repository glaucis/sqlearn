/// @file
/// The version parser and its writer.
#include "core/parse_version.hpp"

#include <charconv>
#include <cstddef>
#include <expected>
#include <format>
#include <string>
#include <string_view>
#include <system_error>

namespace sq::core {

namespace {

/// Return whether `c` is an ASCII digit.
/// @param c Any character.
/// @return True for '0' to '9'.
constexpr bool is_digit(char c) noexcept {
    return c >= '0' && c <= '9';
}

/// Return whether `c` may stand in a segment of a local label.
/// @param c Any character.
/// @return True for '0' to '9' and 'a' to 'z'.
constexpr bool is_local_character(char c) noexcept {
    return is_digit(c) || (c >= 'a' && c <= 'z');
}

/// A cursor over the text parse_version reads.
class Reader {
public:
    /// Start at the beginning of `text`.
    /// @param text The text to read.
    explicit Reader(std::string_view text) noexcept : text_(text) {}

    /// Return where the cursor is.
    /// @return Its offset in bytes from the start of the text.
    [[nodiscard]] std::size_t offset() const noexcept { return offset_; }

    /// Return whether the whole text has been read.
    /// @return True at the end.
    [[nodiscard]] bool done() const noexcept { return offset_ == text_.size(); }

    /// Return the text from the cursor to the end.
    /// @return What is left to read; empty at the end.
    [[nodiscard]] std::string_view rest() const noexcept {
        auto rest = text_;
        rest.remove_prefix(offset_);
        return rest;
    }

    /// Return whether the text continues with `word` at the cursor.
    /// @param word The text to look for.
    /// @return True when it is there; the cursor does not move.
    [[nodiscard]] bool at(std::string_view word) const noexcept { return rest().starts_with(word); }

    /// Skip `word` when the text continues with it.
    /// @param word The text to look for at the cursor.
    /// @return True, past `word`, when it was there; false, unmoved, if not.
    bool skip(std::string_view word) noexcept {
        if (!at(word)) {
            return false;
        }
        offset_ += word.size();
        return true;
    }

    /// Skip the characters `keep` accepts, from the cursor on.
    /// @param keep Whether a character is part of what is skipped.
    /// @return What was skipped; empty when the cursor did not move.
    std::string_view skip_while(bool (*keep)(char) noexcept) noexcept {
        auto skipped = rest();
        std::size_t count = 0;
        for (const char c : skipped) {
            if (!keep(c)) {
                break;
            }
            ++count;
        }
        skipped.remove_suffix(skipped.size() - count);
        offset_ += count;
        return skipped;
    }

    /// Read a number: "0", or a digit 1 to 9 and more digits, at most
    /// INT_MAX.
    /// @return The number, or why and where there is none.
    std::expected<int, ParseError> number() noexcept {
        const auto start = offset_;
        const auto digits = skip_while(is_digit);
        if (digits.empty()) {
            return std::unexpected(ParseError{ParseError::Kind::expected_number, start});
        }
        if (digits.size() > 1 && digits.front() == '0') {
            return std::unexpected(ParseError{ParseError::Kind::leading_zero, start});
        }
        int value = 0;
        // Only digits are left to read, so the one error is overflow.
        if (std::from_chars(digits.begin(), digits.end(), value).ec != std::errc{}) {
            return std::unexpected(ParseError{ParseError::Kind::number_too_large, start});
        }
        return value;
    }

    /// Read a local label to the end of the text: segments of [a-z0-9],
    /// at least one, separated by single '.'.
    /// @return Nothing, or why and where the label is wrong.
    std::expected<void, ParseError> local() noexcept {
        while (true) {
            if (skip_while(is_local_character).empty() || !(done() || at("."))) {
                return std::unexpected(ParseError{ParseError::Kind::bad_local, offset_});
            }
            if (done()) {
                return {};
            }
            ++offset_; // the '.' between two segments
        }
    }

private:
    std::string_view text_;
    std::size_t offset_ = 0;
};

/// Read the release numbers, "MAJOR.MINOR" and an optional ".PATCH", into
/// `version`.
/// @param reader At the start of the text.
/// @param version Where the numbers go; the patch stays 0 when absent.
/// @return Nothing, or why and where the text is not a release.
std::expected<void, ParseError> read_release(Reader &reader, Version &version) noexcept {
    const auto major = reader.number();
    if (!major) {
        return std::unexpected(major.error());
    }
    version.major = *major;
    if (!reader.skip(".")) {
        const auto kind =
            reader.done() ? ParseError::Kind::expected_number : ParseError::Kind::unexpected_text;
        return std::unexpected(ParseError{kind, reader.offset()});
    }
    const auto minor = reader.number();
    if (!minor) {
        return std::unexpected(minor.error());
    }
    version.minor = *minor;
    // A third release number unless the dev part comes first (PEP 440 pads
    // "0.1" to "0.1.0").
    if (!reader.at(".dev") && reader.skip(".")) {
        const auto patch = reader.number();
        if (!patch) {
            return std::unexpected(patch.error());
        }
        version.patch = *patch;
    }
    return {};
}

/// Read the dev part, ".devN" and an optional "+local", when the text
/// continues with one.
/// @param reader Just after the release numbers.
/// @return Where `pre` starts, after the '.'; npos for a final release; or
///         why and where the dev part is wrong.
std::expected<std::size_t, ParseError> read_dev(Reader &reader) noexcept {
    if (!reader.skip(".")) {
        return std::string_view::npos;
    }
    const auto start = reader.offset();
    if (!reader.skip("dev")) {
        return std::unexpected(ParseError{ParseError::Kind::unexpected_text, start - 1});
    }
    const auto dev = reader.number();
    if (!dev) {
        return std::unexpected(dev.error());
    }
    if (reader.skip("+")) {
        const auto local = reader.local();
        if (!local) {
            return std::unexpected(local.error());
        }
    }
    return start;
}

} // namespace

std::expected<Version, ParseError> parse_version(std::string_view text) {
    if (text.empty()) {
        return std::unexpected(ParseError{ParseError::Kind::empty, 0});
    }
    Reader reader(text);
    Version version;
    if (const auto release = read_release(reader, version); !release) {
        return std::unexpected(release.error());
    }
    const auto pre_start = read_dev(reader);
    if (!pre_start) {
        return std::unexpected(pre_start.error());
    }
    if (!reader.done()) {
        return std::unexpected(ParseError{ParseError::Kind::unexpected_text, reader.offset()});
    }
    if (*pre_start != std::string_view::npos) {
        // The rest of the text, as the grammar has checked it.
        version.pre = std::string(text.substr(*pre_start));
    }
    return version;
}

std::string format(const Version &version) {
    auto text = std::format("{}.{}.{}", version.major, version.minor, version.patch);
    if (!version.pre.empty()) {
        text += '.';
        text += version.pre;
    }
    return text;
}

} // namespace sq::core

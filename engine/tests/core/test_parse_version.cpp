/// @file
/// The core group's version parser: the versions sqlearn and DuckDB carry,
/// what it refuses, and that formatting a version parses back to it.
#include "core/parse_version.hpp"
#include "core/version.hpp"

#include <catch2/catch_test_macros.hpp>
#include <rapidcheck/catch.h>

#include <climits>
#include <cstddef>
#include <expected>
#include <ostream>
#include <string>
#include <vector>

namespace sq::core {

/// Show a version in RapidCheck's counterexamples.
/// @param version The version to show.
/// @param os The stream RapidCheck writes to.
void showValue(const Version &version, std::ostream &os);

void showValue(const Version &version, std::ostream &os) {
    os << "Version{" << version.major << ", " << version.minor << ", " << version.patch << ", \""
       << version.pre << "\"}";
}

} // namespace sq::core

namespace {

using sq::core::ParseError;
using sq::core::Version;

/// Return the error parse_version gives for `text`, which it must refuse.
/// @param text A string parse_version refuses.
/// @return The error it gave.
ParseError refusal(std::string_view text) {
    const auto parsed = sq::core::parse_version(text);
    REQUIRE_FALSE(parsed.has_value());
    return parsed.error();
}

/// Generate a release number: any int from 0 to INT_MAX, small ones first.
/// @return The generator.
rc::Gen<int> number() {
    return rc::gen::oneOf(rc::gen::inRange(0, INT_MAX), rc::gen::just(INT_MAX));
}

/// Generate one segment of a local label: lower-case ASCII letters and
/// digits, at least one.
/// @return The generator.
rc::Gen<std::string> local_segment() {
    static const std::vector<char> alphabet{'0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                                            'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j',
                                            'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't',
                                            'u', 'v', 'w', 'x', 'y', 'z'};
    return rc::gen::nonEmpty(rc::gen::container<std::string>(rc::gen::elementOf(alphabet)));
}

/// Generate what a valid Version's `pre` holds: nothing, "dev<N>", or
/// "dev<N>+<local>" with a local label of one or more segments.
/// @return The generator.
rc::Gen<std::string> pre() {
    const auto dev = rc::gen::map(number(), [](int n) { return "dev" + std::to_string(n); });
    const auto local = rc::gen::map(
        rc::gen::nonEmpty(rc::gen::container<std::vector<std::string>>(local_segment())),
        [](const std::vector<std::string> &segments) {
            std::string label;
            for (const auto &segment : segments) {
                label += label.empty() ? segment : "." + segment;
            }
            return label;
        });
    return rc::gen::oneOf(rc::gen::just(std::string{}), dev,
                          rc::gen::apply([](const std::string &d,
                                            const std::string &l) { return d + "+" + l; },
                                         dev, local));
}

} // namespace

TEST_CASE("parse_version reads a final release", "[core]") {
    CHECK(sq::core::parse_version("2.0.1") == Version{2, 0, 1, ""});
    CHECK(sq::core::parse_version("1.0.0") == Version{1, 0, 0, ""});
}

TEST_CASE("parse_version reads a development release", "[core]") {
    CHECK(sq::core::parse_version("0.1.dev597") == Version{0, 1, 0, "dev597"});
    CHECK(sq::core::parse_version("0.1.dev667+g136548be1") ==
          Version{0, 1, 0, "dev667+g136548be1"});
    CHECK(sq::core::parse_version("2.0.1.dev3+g1a2b.d20261123") ==
          Version{2, 0, 1, "dev3+g1a2b.d20261123"});
}

TEST_CASE("parse_version reads the DuckDB version the build is pinned to", "[core]") {
    CHECK(sq::core::parse_version(sq::core::build_identity().duckdb_version).has_value());
}

TEST_CASE("parse_version refuses an empty string", "[core]") {
    CHECK(refusal("") == ParseError{ParseError::Kind::empty, 0});
}

TEST_CASE("parse_version refuses a missing number", "[core]") {
    CHECK(refusal("1..0") == ParseError{ParseError::Kind::expected_number, 2});
    CHECK(refusal("1") == ParseError{ParseError::Kind::expected_number, 1});
    CHECK(refusal("1.0.dev") == ParseError{ParseError::Kind::expected_number, 7});
    CHECK(refusal("-1.0.0") == ParseError{ParseError::Kind::expected_number, 0});
}

TEST_CASE("parse_version refuses a number that overflows an int", "[core]") {
    CHECK(refusal("99999999999.0.0") == ParseError{ParseError::Kind::number_too_large, 0});
    CHECK(refusal("2147483648.0.0") == ParseError{ParseError::Kind::number_too_large, 0});
    CHECK(refusal("1.0.0.dev99999999999") == ParseError{ParseError::Kind::number_too_large, 9});
    CHECK(sq::core::parse_version("2147483647.0.0") == Version{INT_MAX, 0, 0, ""});
}

TEST_CASE("parse_version refuses a number with a leading zero", "[core]") {
    CHECK(refusal("01.0.0") == ParseError{ParseError::Kind::leading_zero, 0});
    CHECK(refusal("1.0.dev01") == ParseError{ParseError::Kind::leading_zero, 7});
}

TEST_CASE("parse_version refuses text outside its subset of PEP 440", "[core]") {
    CHECK(refusal("v2.0.1") == ParseError{ParseError::Kind::expected_number, 0});
    CHECK(refusal("1.0.0.0") == ParseError{ParseError::Kind::unexpected_text, 5});
    CHECK(refusal("1.0.0rc1") == ParseError{ParseError::Kind::unexpected_text, 5});
    CHECK(refusal("1.0.0+local") == ParseError{ParseError::Kind::unexpected_text, 5});
    CHECK(refusal("1.0.0 ") == ParseError{ParseError::Kind::unexpected_text, 5});
    CHECK(refusal("1.0.dev1+") == ParseError{ParseError::Kind::bad_local, 9});
    CHECK(refusal("1.0.dev1+a..b") == ParseError{ParseError::Kind::bad_local, 11});
    CHECK(refusal("1.0.dev1+Ab") == ParseError{ParseError::Kind::bad_local, 9});
    CHECK(refusal("1.0.dev1+a-b") == ParseError{ParseError::Kind::bad_local, 10});
}

TEST_CASE("format writes the three release numbers, then the dev part", "[core]") {
    CHECK(sq::core::format(Version{2, 0, 1, ""}) == "2.0.1");
    CHECK(sq::core::format(Version{0, 1, 0, "dev597"}) == "0.1.0.dev597");
    CHECK(sq::core::format(Version{0, 1, 0, "dev667+g136548be1"}) == "0.1.0.dev667+g136548be1");
}

TEST_CASE("a formatted version parses back to itself", "[core]") {
    rc::prop("parse_version(format(v)) == v", [] {
        const Version version{*number(), *number(), *number(), *pre()};
        const auto parsed = sq::core::parse_version(sq::core::format(version));
        RC_ASSERT(parsed.has_value());
        RC_ASSERT(*parsed == version);
    });
}

TEST_CASE("whatever parse_version accepts formats to text it accepts again", "[core]") {
    rc::prop("parse_version(format(parse_version(s))) == parse_version(s)", [] {
        static const std::vector<char> alphabet{'0', '1', '9', '.', 'd', 'e', 'v', '+', 'g', 'x'};
        const auto text = *rc::gen::container<std::string>(rc::gen::elementOf(alphabet));
        const auto parsed = sq::core::parse_version(text);
        if (parsed.has_value()) {
            const auto again = sq::core::parse_version(sq::core::format(*parsed));
            RC_ASSERT(again.has_value());
            RC_ASSERT(*again == *parsed);
        } else {
            RC_ASSERT(parsed.error().offset <= text.size());
        }
    });
}

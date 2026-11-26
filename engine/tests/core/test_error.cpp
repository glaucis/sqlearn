/// @file
/// The core group's errors: what failed, why and the fix, and what a failed
/// precondition says about where it failed.
#include "core/expects.hpp"

#include <catch2/catch_test_macros.hpp>

#include <string>

namespace {

using sq::core::PreconditionError;

/// Return the error SQ_EXPECTS throws for `cond`, which must be false.
/// @param cond A false condition.
/// @return The error it threw.
PreconditionError failure(bool cond) {
    try {
        SQ_EXPECTS(cond);
    } catch (const PreconditionError &error) {
        return error;
    }
    FAIL("SQ_EXPECTS(false) did not throw");
    return {"", std::source_location::current()};
}

} // namespace

TEST_CASE("an error carries what failed, why and the fix", "[core]") {
    const sq::core::Error error("the engine failed", "a reason", "a fix");
    CHECK(std::string(error.what()) == "the engine failed");
    CHECK(error.why() == "a reason");
    CHECK(error.fix() == "a fix");
}

TEST_CASE("a failed precondition names its condition and where it was checked", "[core]") {
    const auto error = failure(false);
    CHECK(error.condition() == "cond");
    CHECK(std::string(error.where().file_name()).ends_with("test_error.cpp"));
    CHECK(std::string(error.where().function_name()).find("failure") != std::string::npos);
    const std::string what = error.what();
    CHECK(what.starts_with("sqlearn's engine was called with `cond` false ("));
    CHECK(what.find("test_error.cpp:" + std::to_string(error.where().line()) + ", in ") !=
          std::string::npos);
    CHECK(error.why().find("a bug in sqlearn") != std::string::npos);
    CHECK(error.fix().find("https://github.com/glaucis/sqlearn/issues") != std::string::npos);
}

TEST_CASE("a failed precondition's message carries no path of the build machine", "[core]") {
    // The file's own name only: the path where the module was built says
    // nothing to the user, and differs between machines.
    const std::string what = failure(false).what();
    CHECK(what.find('/') == std::string::npos);
    CHECK(what.find('\\') == std::string::npos);
}

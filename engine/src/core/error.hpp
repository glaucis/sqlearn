/// @file
/// sqlearn's own C++ errors: what failed, why, and the fix.
#pragma once

#include <source_location>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace sq::core {

/// An error sqlearn's C++ raises on purpose. Its message says what failed;
/// why() and fix() are the two lines the user reads after it. The bindings
/// turn it into sqlearn.errors.InternalError.
class Error : public std::runtime_error {
public:
    /// Make an error from what failed, why, and the fix.
    /// @param what What failed, one sentence.
    /// @param why Why it failed.
    /// @param fix What the user can do about it.
    Error(const std::string &what, std::string why, std::string fix)
        : std::runtime_error(what), why_(std::move(why)), fix_(std::move(fix)) {}

    /// Return why it failed.
    /// @return The reason, without its "Why:" label.
    [[nodiscard]] const std::string &why() const noexcept { return why_; }

    /// Return the fix.
    /// @return The fix, without its "Fix:" label.
    [[nodiscard]] const std::string &fix() const noexcept { return fix_; }

private:
    std::string why_;
    std::string fix_;
};

/// A precondition of sqlearn's C++ was false: sqlearn called its own engine
/// wrongly, a bug in sqlearn. Thrown by SQ_EXPECTS.
class PreconditionError : public Error {
public:
    /// Make the error for `condition`, false at `where`.
    /// @param condition The condition's source text.
    /// @param where Where the condition was checked.
    PreconditionError(std::string_view condition, std::source_location where);

    /// Return the condition's source text.
    /// @return The condition, as written in the source.
    [[nodiscard]] const std::string &condition() const noexcept { return condition_; }

    /// Return where the condition was checked.
    /// @return The file, line and function of the check.
    [[nodiscard]] const std::source_location &where() const noexcept { return where_; }

private:
    std::string condition_;
    std::source_location where_;
};

} // namespace sq::core

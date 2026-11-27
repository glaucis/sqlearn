/// @file
/// The messages of the C++ errors in sqlearn.
#include "core/error.hpp"

#include <format>
#include <source_location>
#include <string_view>

namespace sq::core {

namespace {

/// Return the last component of a source path, so a message carries no path
/// of the machine that built the module.
/// @param path A path as std::source_location gives it.
/// @return The part after the last '/' or '\'.
std::string_view base_name(std::string_view path) noexcept {
    const auto slash = path.find_last_of("/\\");
    if (slash != std::string_view::npos) {
        path.remove_prefix(slash + 1);
    }
    return path;
}

} // namespace

PreconditionError::PreconditionError(std::string_view condition, std::source_location where)
    : Error(std::format("sqlearn's engine was called with `{}` false ({}:{}, in {})", condition,
                        base_name(where.file_name()), where.line(), where.function_name()),
            "a precondition of sqlearn's C++ failed: sqlearn called its own engine wrongly, "
            "which is a bug in sqlearn, not a mistake in your code",
            "please report it at https://github.com/glaucis/sqlearn/issues with this message"),
      condition_(condition), where_(where) {}

} // namespace sq::core

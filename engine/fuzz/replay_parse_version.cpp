/// @file
/// Runs the files it is given, the kept corpus of the version parser's fuzz
/// target, and a 1 MiB string of digits, through the property the target
/// keeps, so a case the fuzzer found stays tested in every build.
#include "parse_version_property.hpp"

#include <cstddef>
#include <exception>
#include <fstream>
#include <iostream>
#include <iterator>
#include <span>
#include <string>

namespace {

/// Run one input through the property and say so when it fails.
/// @param name What the input is, for the message.
/// @param text The input's bytes.
/// @return True when the property holds.
bool check(const std::string &name, const std::string &text) {
    if (sq::fuzz::round_trips(text)) {
        return true;
    }
    std::cerr << "replay_parse_version: " << name
              << ": a version did not survive format() and parse_version()\n";
    return false;
}

} // namespace

/// Replay each file named on the command line.
/// @param argc The number of arguments.
/// @param argv The program's name, then the files.
/// @return True when every input holds the property.
/// @throws std::bad_alloc when there is no memory for an input.
bool replay(int argc, char **argv) {
    // The 1 MiB string of digits is built here, not kept as a file.
    constexpr std::size_t mebibyte = 1048576;
    bool good = check("1 MiB of digits", std::string(mebibyte, '7'));
    // main's argv is the one place a pointer and a count meet, as raw/'s
    // Buffer is for memory; the span is built once, then indexed safely.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunsafe-buffer-usage-in-container"
    const std::span<char *> arguments{argv, static_cast<std::size_t>(argc)};
#pragma clang diagnostic pop
    for (const char *path : arguments.subspan(1)) {
        // NOLINTNEXTLINE(bugprone-signed-bitwise): the standard's own flag type
        std::ifstream in{path, std::ios::binary};
        if (!in) {
            std::cerr << "replay_parse_version: cannot read " << path << "\n";
            good = false;
            continue;
        }
        const std::string text{std::istreambuf_iterator<char>{in}, {}};
        good = check(path, text) && good;
    }
    return good;
}

/// Replay the files, never letting an exception out of main.
/// @param argc The number of arguments.
/// @param argv The program's name, then the files.
/// @return 0 when every input holds the property, 1 when one does not, a
///         file cannot be read or memory runs out.
int main(int argc, char **argv) {
    try {
        return replay(argc, argv) ? 0 : 1;
    } catch (const std::exception &error) {
        std::cerr << "replay_parse_version: " << error.what() << "\n";
        return 1;
    }
}

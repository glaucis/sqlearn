/// @file
/// libFuzzer's target for the version parser (`just fuzz`): any bytes go in,
/// and a version that does not survive format() and parse_version() stops
/// the program, which libFuzzer reports with the input.
#include "parse_version_property.hpp"

#include <cstddef>
#include <cstdint>
#include <string_view>

extern "C" {
/// libFuzzer's entry point, called once for each input it tries.
/// @param data The input's bytes.
/// @param size Their number.
/// @return Always 0, as libFuzzer asks.
int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size);
}

int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
    const std::string_view text{reinterpret_cast<const char *>(data), size};
    if (!sq::fuzz::round_trips(text)) {
        __builtin_trap();
    }
    return 0;
}

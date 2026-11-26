/// @file
/// TypeSanitizer's canary: an int stored into a float, against strict
/// aliasing.
#include <cstdio>

namespace {
/// The float the store hits.
float value = 1.0F;

/// Store 42 through `target`, an int pointer to a float.
[[gnu::noinline]] void store(int *target) {
    *target = 42;
}
} // namespace

/// Store an int into a float; TypeSanitizer stops the program.
int main() {
    store(reinterpret_cast<int *>(&value));
    std::printf("canary: survived with %f\n", static_cast<double>(value));
    return 0;
}

/// @file
/// UndefinedBehaviorSanitizer's canary: a signed integer overflow.
#include <climits>
#include <cstdio>

namespace {
/// The largest int, volatile so the compiler cannot fold the overflow away.
volatile int largest = INT_MAX;
} // namespace

/// Add one to the largest int; UndefinedBehaviorSanitizer stops the program.
int main() {
    int value = largest;
    value += 1;
    std::printf("canary: survived with %d\n", value);
    return 0;
}

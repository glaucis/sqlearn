/// @file
/// ThreadSanitizer's canary: two threads write one int with no lock.
#include <cstdio>
#include <thread>

namespace {
/// The int both threads write.
int shared = 0;
} // namespace

/// Race two writes; ThreadSanitizer stops the program.
int main() {
    std::thread first([] { ++shared; });
    std::thread second([] { ++shared; });
    first.join();
    second.join();
    std::printf("canary: survived with %d\n", shared);
    return 0;
}

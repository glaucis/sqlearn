/// @file
/// LeakSanitizer's canary: a heap block whose last pointer is dropped.
#include <cstdio>
#include <cstdlib>

namespace {
/// The block's one pointer, volatile so the allocation is not optimised away.
void *volatile kept = nullptr;
} // namespace

/// Allocate, then forget the block; LeakSanitizer fails the program at exit.
int main() {
    kept = std::malloc(64);
    kept = nullptr;
    std::puts("canary: survived");
    return 0;
}

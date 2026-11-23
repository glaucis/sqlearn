/// @file
/// AddressSanitizer's canary: a write one past the end of a heap block.
#include <cstddef>
#include <cstdio>
#include <vector>

/// Write past the end of four ints; AddressSanitizer stops the program.
int main() {
    std::vector<int> block(4);
    int *first = block.data();
    volatile std::size_t past = block.size();
    first[past] = 1;
    std::puts("canary: survived");
    return 0;
}

/// @file
/// Must not pass clang-tidy: pointer arithmetic outside engine/src/raw/,
/// which cppcoreguidelines-pro-bounds-pointer-arithmetic refuses (ADR 0065).
/// It breaks no other check (tests/engine/test_tidy.py).

namespace sq::must_not_pass_tidy {

/// Return the element after the one `first` points to.
/// @param first A pointer into an array of at least two elements.
/// @return The second element.
int second(const int *first);

int second(const int *first) {
    return *(first + 1);
}

} // namespace sq::must_not_pass_tidy

/// @file
/// Must not pass clang-tidy: a raw new and delete outside engine/src/raw/,
/// which cppcoreguidelines-owning-memory refuses (ADR 0065). It breaks no
/// other check (tests/engine/test_tidy.py).

namespace sq::must_not_pass_tidy {

/// Return 1, from an int made with new and freed with delete.
/// @return 1.
int one();

int one() {
    const int *const value = new int(1);
    const int result = *value;
    delete value;
    return result;
}

} // namespace sq::must_not_pass_tidy

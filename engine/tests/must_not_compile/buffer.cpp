/// @file
/// Must not compile under sqlearn's warnings: pointer arithmetic outside
/// engine/src/raw/, which -Wunsafe-buffer-usage refuses. It compiles cleanly
/// without that flag (the control target, engine/tests/CMakeLists.txt).

namespace sq::must_not_compile {

/// Return the element after the one `first` points to.
/// @param first A pointer into an array of at least two elements.
/// @return The second element.
int second(const int *first);

int second(const int *first) {
    return *(first + 1);
}

} // namespace sq::must_not_compile

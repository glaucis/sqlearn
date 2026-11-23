/// @file
/// Must not compile under sqlearn's warnings: a switch case falling into the
/// next without [[fallthrough]], which -Wimplicit-fallthrough refuses. It
/// compiles cleanly without that flag (the control target,
/// engine/tests/CMakeLists.txt).

namespace sq::must_not_compile {

/// Return how many of the steps from `step` to the last are left.
/// @param step 0, 1 or 2.
/// @return 3 for 0, 2 for 1, 1 for 2, 0 otherwise.
int remaining(int step);

int remaining(int step) {
    int left = 0;
    switch (step) {
    case 0:
        ++left;
    case 1:
        ++left;
    case 2:
        ++left;
        break;
    default:
        break;
    }
    return left;
}

} // namespace sq::must_not_compile

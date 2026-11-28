/// @file
/// demangle, which names the type of a C++ exception the bindings did not
/// expect (bindings/guard.hpp).
#include "raw/demangle.hpp"

#include <catch2/catch_test_macros.hpp>

#include <stdexcept>
#include <string>
#include <typeinfo>

TEST_CASE("demangle names a standard exception as its source spells it", "[demangle]") {
    CHECK(sq::raw::demangle(typeid(std::runtime_error).name()) == "std::runtime_error");
}

TEST_CASE("demangle gives back a name that does not demangle", "[demangle]") {
    CHECK(sq::raw::demangle("%not a mangled name%") == "%not a mangled name%");
    CHECK(sq::raw::demangle("").empty());
}

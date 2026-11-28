/// @file
/// The raw group's program: Buffer, the one owner of raw memory.
#include "core/error.hpp"
#include "raw/buffer.hpp"

#include <catch2/catch_test_macros.hpp>
#include <rapidcheck.h>
#include <rapidcheck/catch.h>

#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>
#include <span>
#include <string>
#include <type_traits>
#include <utility>

namespace {

using sq::raw::Buffer;

/// Return whether `pointer` is on a 64-byte boundary. Reading a pointer as
/// an integer is allowed here, in the raw layer's tests, and nowhere else.
/// @param pointer Any pointer.
/// @return True when its address is a multiple of 64.
bool on_64_bytes(const void *pointer) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): an address as a number
    return reinterpret_cast<std::uintptr_t>(pointer) % sq::raw::buffer_alignment == 0;
}

/// Whether a sanitizer's allocator serves the program: on a request larger
/// than it can serve it ends the program instead of throwing
/// std::bad_alloc, so the test of that request is skipped (it runs in the
/// debug, release, profile, coverage and mutate presets).
constexpr bool sanitized_allocator =
#if __has_feature(address_sanitizer) || __has_feature(thread_sanitizer) ||                         \
    __has_feature(leak_sanitizer) || __has_feature(type_sanitizer)
    true;
#else
    false;
#endif

} // namespace

TEST_CASE("a buffer has the size it was made with", "[raw]") {
    const Buffer<double> buffer(1000);
    CHECK(buffer.size() == 1000);
    CHECK(buffer.span().size() == 1000);
}

TEST_CASE("a buffer's elements start at zero", "[raw]") {
    constexpr std::size_t count = 17;
    const Buffer<std::int64_t> buffer(count);
    for (const auto element : buffer.span()) {
        CHECK(element == 0);
    }
}

TEST_CASE("a buffer starts on a 64-byte boundary", "[raw]") {
    rc::prop("Buffer(n).span().data() is 64-byte aligned", [] {
        const auto n = *rc::gen::inRange<std::size_t>(1, 100000);
        Buffer<char> chars(n);
        Buffer<double> doubles(n);
        RC_ASSERT(chars.span().size() == n);
        RC_ASSERT(doubles.span().size() == n);
        RC_ASSERT(on_64_bytes(chars.span().data()));
        RC_ASSERT(on_64_bytes(doubles.span().data()));
    });
}

TEST_CASE("a buffer's span covers every element, each writable", "[raw]") {
    rc::prop("writing i at element i reads back i", [] {
        const auto n = *rc::gen::inRange<std::size_t>(0, 5000);
        Buffer<std::size_t> buffer(n);
        RC_ASSERT(buffer.span().size() == n);
        std::size_t i = 0;
        for (auto &element : buffer.span()) {
            element = i++;
        }
        i = 0;
        for (const auto element : std::as_const(buffer).span()) {
            RC_ASSERT(element == i++);
        }
        RC_ASSERT(i == n);
    });
}

TEST_CASE("a buffer of no elements is allowed", "[raw]") {
    Buffer<double> buffer(0);
    CHECK(buffer.size() == 0);
    CHECK(buffer.span().empty());
}

TEST_CASE("moving a buffer leaves the source empty", "[raw]") {
    constexpr std::size_t count = 8;
    Buffer<double> source(count);
    const auto *const data = source.span().data();

    Buffer<double> moved(std::move(source));
    CHECK(moved.size() == count);
    CHECK(moved.span().data() == data);
    CHECK(source.size() == 0); // NOLINT(bugprone-use-after-move): what a move leaves
    CHECK(source.span().empty());

    Buffer<double> assigned(3);
    assigned = std::move(moved);
    CHECK(assigned.size() == count);
    CHECK(assigned.span().data() == data);
    CHECK(moved.size() == 0); // NOLINT(bugprone-use-after-move): what a move leaves
    CHECK(moved.span().empty());
}

TEST_CASE("moving a buffer into itself leaves it as it was", "[raw]") {
    constexpr std::size_t count = 8;
    constexpr double first = 2.5;
    Buffer<double> buffer(count);
    buffer.span().front() = first;
    const auto *const data = buffer.span().data();

    // GCC's pragma, which clang reads too: both warn of a self-move.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wself-move" // the self-move is what is tested
    buffer = std::move(buffer);
#pragma GCC diagnostic pop

    CHECK(buffer.size() == count);
    CHECK(buffer.span().data() == data);
    CHECK(buffer.span().front() == first);
}

TEST_CASE("a buffer is move-only", "[raw]") {
    STATIC_CHECK_FALSE(std::is_copy_constructible_v<Buffer<double>>);
    STATIC_CHECK_FALSE(std::is_copy_assignable_v<Buffer<double>>);
    STATIC_CHECK(std::is_nothrow_move_constructible_v<Buffer<double>>);
    STATIC_CHECK(std::is_nothrow_move_assignable_v<Buffer<double>>);
}

TEST_CASE("a buffer too large to count in bytes is a precondition error", "[raw]") {
    const auto too_many = std::numeric_limits<std::size_t>::max() / sizeof(double) + 1;
    CHECK_THROWS_AS(Buffer<double>(too_many), sq::core::PreconditionError);
}

TEST_CASE("a buffer as large as a std::size_t counts in bytes passes the precondition", "[raw]") {
    if (sanitized_allocator) {
        SKIP("a sanitizer's allocator ends the program on this request");
    }
    // The bound itself is allowed: the request reaches the allocator, which
    // has no such memory.
    const auto most = std::numeric_limits<std::size_t>::max() / sizeof(double);
    CHECK_THROWS_AS(Buffer<double>(most), std::bad_alloc);
}

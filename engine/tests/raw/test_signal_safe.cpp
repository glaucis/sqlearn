/// @file
/// The raw layer's signal-safe pieces the crash report is written with:
/// FixedText, FdWriter and the loaded images' table.
#include "raw/fd_writer.hpp"
#include "raw/fixed_text.hpp"
#include "raw/images.hpp"

#include <catch2/catch_test_macros.hpp>
#include <rapidcheck.h>
#include <rapidcheck/catch.h>

#include <sys/types.h> // IWYU pragma: keep
#include <unistd.h>

#include <array>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>

namespace {

using sq::raw::FdWriter;
using sq::raw::FixedText;

/// A pipe, both ends closed at the end.
class Pipe {
public:
    /// Open the pipe.
    Pipe() { REQUIRE(::pipe(ends_.data()) == 0); }
    Pipe(const Pipe &) = delete;
    Pipe &operator=(const Pipe &) = delete;
    Pipe(Pipe &&) = delete;
    Pipe &operator=(Pipe &&) = delete;
    /// Close what is still open.
    ~Pipe() {
        close_write();
        ::close(std::get<0>(ends_));
    }
    /// The end to write to.
    /// @return Its descriptor.
    [[nodiscard]] int write_end() const { return std::get<1>(ends_); }
    /// Close the end to write to, so a read sees the end of the data.
    void close_write() {
        if (std::get<1>(ends_) >= 0) {
            ::close(std::get<1>(ends_));
            std::get<1>(ends_) = -1;
        }
    }
    /// Close the write end and read everything written.
    /// @return The bytes.
    std::string drain() {
        close_write();
        std::string out;
        constexpr std::size_t chunk_size = 256;
        std::array<char, chunk_size> chunk{};
        for (ssize_t got = 0; (got = ::read(std::get<0>(ends_), chunk.data(), chunk.size())) > 0;) {
            out.append(chunk.data(), static_cast<std::size_t>(got));
        }
        return out;
    }

private:
    std::array<int, 2> ends_{-1, -1};
};

/// The function whose own address the images' test looks up.
/// @return 1.
[[gnu::noinline]] int in_this_program() {
    return 1;
}

} // namespace

TEST_CASE("fixed text appends text and numbers and stays terminated", "[raw]") {
    constexpr std::size_t size = 32;
    constexpr std::uintmax_t pid = 1234;
    constexpr std::uintmax_t address = 0xbeef;
    FixedText<size> text;
    text.append("pid ").append_number(pid).append(" at 0x").append_number(address,
                                                                          sq::raw::hex_base);
    CHECK(std::string(text.view()) == "pid 1234 at 0xbeef");
    CHECK(std::string(text.c_str()) == std::string(text.view()));
    CHECK_FALSE(text.truncated());
}

TEST_CASE("fixed text keeps what fits and marks the rest cut", "[raw]") {
    constexpr std::size_t size = 5;
    FixedText<size> text;
    text.append("abc").append("defg");
    CHECK(std::string(text.view()) == "abcde");
    CHECK(std::string(text.c_str()) == "abcde");
    CHECK(text.truncated());
}

TEST_CASE("fixed text refuses a base other than 10 and 16", "[raw]") {
    constexpr std::size_t size = 8;
    constexpr std::uintmax_t seven = 7;
    constexpr int octal = 8;
    FixedText<size> text;
    text.append_number(seven, octal);
    CHECK(text.view().empty());
    CHECK(text.truncated());
}

TEST_CASE("fixed text cuts a number that does not fit", "[raw]") {
    FixedText<3> text;
    constexpr std::uintmax_t six_digits = 123456;
    text.append_number(six_digits);
    CHECK(std::string(text.view()) == "123");
    CHECK(text.truncated());
}

TEST_CASE("fixed text holds any two appends up to its size", "[raw]") {
    rc::prop("it keeps their first 16 bytes, and says when it cut", [] {
        const auto a = *rc::gen::arbitrary<std::string>();
        const auto b = *rc::gen::arbitrary<std::string>();
        constexpr std::size_t size = 16;
        FixedText<size> text;
        text.append(a).append(b);
        RC_ASSERT(text.view() == (a + b).substr(0, size));
        RC_ASSERT(text.truncated() == (a.size() + b.size() > size));
    });
}

TEST_CASE("an fd writer writes text and numbers to its descriptor", "[raw]") {
    Pipe pipe;
    FdWriter out(pipe.write_end());
    constexpr std::uintmax_t n = 42;
    constexpr int m = -7;
    constexpr std::uintptr_t p = 0x1f;
    out.text("n=").decimal(n).text(" m=").decimal(m).text(" p=").hex(p);
    out.text(" z=").decimal(0).text(" min=").decimal(INT_MIN).text(" h0=").hex(0);
    CHECK(out.ok());
    CHECK(pipe.drain() == "n=42 m=-7 p=0x1f z=0 min=" + std::to_string(INT_MIN) + " h0=0x0");
}

TEST_CASE("an fd writer stops at the first failed write", "[raw]") {
    FdWriter out(-1);
    out.text("lost");
    CHECK_FALSE(out.ok());
    out.text("also lost").hex(1);
    CHECK_FALSE(out.ok());
}

TEST_CASE("an fd writer writes nothing for empty text", "[raw]") {
    Pipe pipe;
    FdWriter out(pipe.write_end());
    out.text("");
    CHECK(out.ok());
    CHECK(pipe.drain().empty());
}

TEST_CASE("the loaded images hold this program's code, with its path", "[raw]") {
    constexpr std::size_t room = 1024;
    std::array<sq::raw::Image, room> images{};
    const std::size_t count = sq::raw::loaded_images(images);
    REQUIRE(count > 0);
    const std::span<const sq::raw::Image> loaded = std::span(images).first(count);
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): a function's address
    const auto here = reinterpret_cast<std::uintptr_t>(&in_this_program);
    const sq::raw::Image *image = sq::raw::image_of(loaded, here);
    REQUIRE(image != nullptr);
    CHECK(image->start <= here);
    CHECK(here < image->end);
    CHECK(image->load <= image->start);
#if defined(__APPLE__)
    REQUIRE(image->path != nullptr);
    CHECK(std::string_view(image->path).ends_with("test_raw"));
#endif
    CHECK(in_this_program() == 1);
}

TEST_CASE("no image holds address 0, and a full table stops at its size", "[raw]") {
    std::array<sq::raw::Image, 1> one{};
    CHECK(sq::raw::loaded_images(one) == 1);
    CHECK(sq::raw::image_of(std::span<const sq::raw::Image>(one), 0) == nullptr);
    CHECK(sq::raw::loaded_images(std::span<sq::raw::Image>()) == 0);
}

TEST_CASE("no context has no program counter", "[raw]") {
    CHECK(sq::raw::context_pc(nullptr) == 0);
}

TEST_CASE("an address is its pointer as a number", "[raw]") {
    const int value = 0;
    CHECK(sq::raw::address_of(nullptr) == 0);
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the same conversion
    CHECK(sq::raw::address_of(&value) == reinterpret_cast<std::uintptr_t>(&value));
}

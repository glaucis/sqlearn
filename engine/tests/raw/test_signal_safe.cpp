/// @file
/// The raw layer's signal-safe pieces the crash report is written with:
/// FixedText, FdWriter and the loaded images' table.
#include "raw/fd_writer.hpp"
#include "raw/fixed_text.hpp"
#include "raw/images.hpp"
#include "raw/signal_stack.hpp"

#include <catch2/catch_test_macros.hpp>
#include <rapidcheck.h>
#include <rapidcheck/catch.h>

#include <fcntl.h>
#include <sys/types.h> // IWYU pragma: keep
#include <unistd.h>

#if defined(__APPLE__)
#include <mach-o/dyld.h>
#else
#include <link.h>
#endif

#include <algorithm>
#include <array>
#include <cerrno>
#include <climits>
#include <csignal>
// IWYU pragma: no_include <sys/_types/_sigaltstack.h>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <iterator>
#include <limits>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using sq::raw::FdWriter;
using sq::raw::FixedText;

/// Room for the loaded images' paths, as the crash handler gives it.
constexpr std::size_t name_room = 262'144;
/// Room for the loaded images, as many as the crash handler keeps.
constexpr std::size_t table_room = 1024;
/// Room for one short name at most: a path of seven bytes and its NUL.
constexpr std::size_t few_room = 8;
/// A spare signal stack's size in the tests, as the crash handler's.
constexpr std::size_t spare_room = 262'144;

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
    /// Make a write to a full pipe fail with EAGAIN instead of waiting.
    void never_block() const {
        const int fd = std::get<1>(ends_);
        // fcntl(2) takes varargs, and its flags are an int.
        // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg,bugprone-signed-bitwise)
        REQUIRE(::fcntl(fd, F_SETFL, ::fcntl(fd, F_GETFL) | O_NONBLOCK) == 0);
    }
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

TEST_CASE("fixed text holds exactly its size, and cuts one byte over", "[raw]") {
    constexpr std::size_t size = 4;
    FixedText<size> under;
    under.append("abc");
    CHECK(std::string(under.view()) == "abc");
    CHECK_FALSE(under.truncated());
    FixedText<size> exact;
    exact.append("abcd");
    CHECK(std::string(exact.view()) == "abcd");
    CHECK(std::string(exact.c_str()) == "abcd");
    CHECK_FALSE(exact.truncated());
    FixedText<size> over;
    over.append("abcde");
    CHECK(std::string(over.view()) == "abcd");
    CHECK(over.truncated());
}

TEST_CASE("an fd writer reads errno only after a failed write", "[raw]") {
    // An errno left at EINTR by an earlier call says nothing about a write
    // that went through: the text is written once, and the writer is ok.
    // Were it read after a success too, the writer would write the text
    // again until the pipe, which never blocks, refused it.
    Pipe pipe;
    pipe.never_block();
    FdWriter out(pipe.write_end());
    errno = EINTR;
    out.text("once");
    CHECK(out.ok());
    CHECK(pipe.drain() == "once");
}

TEST_CASE("an fd writer goes on after a short write and fails on a full pipe", "[raw]") {
    // More than a pipe holds: the first write is short, the writer goes on
    // from where it stopped, and the next write, to a full pipe that never
    // blocks, fails, so the writer is not ok and wrote a prefix of the text.
    Pipe pipe;
    pipe.never_block();
    constexpr std::size_t more_than_a_pipe = 1'048'576;
    constexpr std::string_view alphabet = "abcdefghijklmnopqrstuvwxyz";
    std::string text;
    while (text.size() < more_than_a_pipe) {
        text.append(alphabet);
    }
    FdWriter out(pipe.write_end());
    out.text(text);
    CHECK_FALSE(out.ok());
    const std::string written = pipe.drain();
    CHECK_FALSE(written.empty());
    CHECK(written.size() < text.size());
    CHECK(text.starts_with(written));
}

TEST_CASE("an image holds its first code address, not its end", "[raw]") {
    constexpr std::uintptr_t start = 0x1000;
    constexpr std::uintptr_t end = 0x2000;
    const std::array<sq::raw::Image, 2> images{
        sq::raw::Image{.load = start, .start = start, .end = end, .path = "a"},
        sq::raw::Image{.load = end, .start = end + 0x1000, .end = end + 0x2000, .path = "b"},
    };
    const std::span<const sq::raw::Image> table(images);
    CHECK(sq::raw::image_of(table, start) == &std::get<0>(images));
    CHECK(sq::raw::image_of(table, end - 1) == &std::get<0>(images));
    CHECK(sq::raw::image_of(table, end) == nullptr);
    CHECK(sq::raw::image_of(table, start - 1) == nullptr);
    CHECK(sq::raw::image_of(table, end + 0x1000) == &std::get<1>(images));
}

TEST_CASE("the loaded images hold this program's code, with its path", "[raw]") {
    constexpr std::size_t room = 1024;
    std::array<sq::raw::Image, room> images{};
    std::vector<char> names(name_room);
    const std::size_t count = sq::raw::loaded_images(images, names);
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
    // Its load address is its Mach-O header, which starts with the 64-bit
    // magic number (MH_MAGIC_64, 0xfeedfacf, little-endian on arm64).
    constexpr std::array<unsigned char, 4> mh_magic_64{0xcf, 0xfa, 0xed, 0xfe};
    std::array<unsigned char, 4> magic{};
    // The loader's own address, read as bytes.
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast,performance-no-int-to-ptr)
    const auto *header = reinterpret_cast<const unsigned char *>(image->load);
    std::copy_n(header, magic.size(), magic.begin());
    CHECK(magic == mh_magic_64);
#endif
    // Every image is listed, not the first alone: the program and the
    // system's libraries it loads.
    CHECK(count > 1);
    CHECK(std::ranges::any_of(loaded, [](const sq::raw::Image &other) {
        return other.path != nullptr &&
               std::string_view(other.path).find("libc++") != std::string_view::npos;
    }));
    CHECK(in_this_program() == 1);
}

TEST_CASE("no image holds address 0, and a full table stops at its size", "[raw]") {
    std::array<sq::raw::Image, 1> one{};
    std::vector<char> names(name_room);
    CHECK(sq::raw::loaded_images(one, names) == 1);
    CHECK(sq::raw::image_of(std::span<const sq::raw::Image>(one), 0) == nullptr);
    CHECK(sq::raw::loaded_images(std::span<sq::raw::Image>(), names) == 0);
}

namespace {

/// Return the loader's own name of the image loaded at `load`, or null.
/// @param load An image's load address.
/// @return The name the loader keeps for it.
const char *loaders_name(std::uintptr_t load) {
#if defined(__APPLE__)
    for (std::uint32_t i = 0; i < _dyld_image_count(); ++i) {
        // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the header's address
        if (reinterpret_cast<std::uintptr_t>(_dyld_get_image_header(i)) == load) {
            return _dyld_get_image_name(i);
        }
    }
    return nullptr;
#else
    struct Found {
        std::uintptr_t load;
        const char *name;
    } found{load, nullptr};
    dl_iterate_phdr(
        [](dl_phdr_info *info, std::size_t, void *data) noexcept -> int {
            auto &want = *static_cast<Found *>(data);
            if (info->dlpi_addr != want.load) {
                return 0;
            }
            want.name = info->dlpi_name;
            return 1;
        },
        &found);
    return found.name;
#endif
}

} // namespace

TEST_CASE("each image's path is the table's own copy, not the loader's", "[raw]") {
    // An image unloaded after the table is taken frees the loader's copy of
    // its name; the table's stays, so a report never reads freed memory.
    std::array<sq::raw::Image, table_room> images{};
    std::vector<char> names(name_room);
    const std::size_t count = sq::raw::loaded_images(images, names);
    REQUIRE(count > 1);
    const char *first = names.data();
    const char *past = std::to_address(names.end());
    std::size_t named = 0;
    for (const sq::raw::Image &image : std::span(images).first(count)) {
        if (image.path == nullptr) {
            continue;
        }
        ++named;
        const char *theirs = loaders_name(image.load);
        REQUIRE(theirs != nullptr);
        CHECK(std::string(image.path) == std::string(theirs));
        CHECK(image.path != theirs);
        CHECK(std::less_equal<>{}(first, image.path));
        CHECK(std::less<>{}(image.path, past));
    }
    CHECK(named > 1);
}

TEST_CASE("a name with no room left is marked, never cut", "[raw]") {
    // Room for one short name at most: every image is still listed, each
    // with its whole path or names_full.
    std::array<sq::raw::Image, table_room> images{};
    std::vector<char> names(name_room);
    const std::size_t count = sq::raw::loaded_images(images, names);
    REQUIRE(count > 1);
    std::array<sq::raw::Image, table_room> tight{};
    std::array<char, few_room> few{};
    REQUIRE(sq::raw::loaded_images(tight, few) == count);
    std::size_t marked = 0;
    for (std::size_t i = 0; i < count; ++i) {
        const char *path = tight.at(i).path;
        if (path == sq::raw::names_full.data()) {
            ++marked;
            continue;
        }
        if (path == nullptr) {
            continue;
        }
        CHECK(std::string(path) == std::string(images.at(i).path));
        CHECK(std::string_view(path).size() < few.size());
    }
    CHECK(marked > 0);
}

TEST_CASE("a name fits with its NUL exactly, and not one byte less", "[raw]") {
    std::array<sq::raw::Image, table_room> images{};
    std::vector<char> names(name_room);
    const std::size_t count = sq::raw::loaded_images(images, names);
    // The first two images with a path, in the loader's order.
    std::vector<std::size_t> named;
    for (std::size_t i = 0; i < count && named.size() < 2; ++i) {
        if (images.at(i).path != nullptr) {
            named.push_back(i);
        }
    }
    REQUIRE(named.size() == 2);
    const std::string one = images.at(named.at(0)).path;
    const std::string two = images.at(named.at(1)).path;
    std::array<sq::raw::Image, table_room> tight{};

    // Room for the first name and its NUL: kept, at the room's start.
    std::vector<char> exact(one.size() + 1);
    REQUIRE(sq::raw::loaded_images(tight, exact) == count);
    CHECK(tight.at(named.at(0)).path == exact.data());
    CHECK(std::string(tight.at(named.at(0)).path) == one);
    CHECK(tight.at(named.at(1)).path == sq::raw::names_full.data());

    // One byte less, no room for its NUL: marked.
    std::vector<char> short_one(one.size());
    REQUIRE(sq::raw::loaded_images(tight, short_one) == count);
    CHECK(tight.at(named.at(0)).path == sq::raw::names_full.data());

    // Room for both names and their NULs: both kept, the second after the
    // first.
    std::vector<char> both(one.size() + 1 + two.size() + 1);
    REQUIRE(sq::raw::loaded_images(tight, both) == count);
    CHECK(tight.at(named.at(0)).path == both.data());
    CHECK(std::string(tight.at(named.at(1)).path) == two);
    CHECK(tight.at(named.at(1)).path == std::next(both.data(), std::ssize(one) + 1));
}

namespace {

/// The calling thread's alternate signal stack.
/// @return What sigaltstack(2) reports; disabled when it fails.
stack_t current_signal_stack() {
    stack_t now{};
    if (::sigaltstack(nullptr, &now) != 0) {
        now.ss_flags = SS_DISABLE;
    }
    return now;
}

/// Whether `stack` is in use, not disabled.
/// @param stack What sigaltstack(2) reported.
/// @return True when enabled.
bool enabled(const stack_t &stack) {
    return (static_cast<unsigned>(stack.ss_flags) & static_cast<unsigned>(SS_DISABLE)) == 0;
}

/// Turn the calling thread's alternate signal stack off. macOS refuses
/// (ENOMEM) unless the size is at least MINSIGSTKSZ, though unused.
/// @return True when it is off.
bool disable_signal_stack() {
    stack_t off{};
    off.ss_size = MINSIGSTKSZ;
    off.ss_flags = SS_DISABLE;
    return ::sigaltstack(&off, nullptr) == 0;
}

/// Run `body` on a new thread and return what it gives, the thread's
/// alternate signal stack put back after. No assertion runs on that
/// thread: Catch2's throw from one would end the program.
/// @param body What to run; it returns what the test checks.
/// @return What `body` returned.
template <typename Body> auto on_a_new_thread(Body body) {
    decltype(body()) seen{};
    std::thread([&] {
        const stack_t before = current_signal_stack();
        seen = body();
        (void)(enabled(before) ? ::sigaltstack(&before, nullptr) == 0 : disable_signal_stack());
    }).join();
    return seen;
}

/// What a thread saw of use_signal_stack.
struct Seen {
    bool first = false;          ///< The first call's result.
    bool second = false;         ///< The second call's result.
    stack_t after_first{};       ///< The stack in place after the first.
    stack_t after_second{};      ///< The stack in place after the second.
    const void *spare = nullptr; ///< The spare memory's address.
    std::size_t size = 0;        ///< Its size.
};

} // namespace

TEST_CASE("a thread without a big enough signal stack is given the spare one", "[raw]") {
    // The first call asks for more than any stack in place, so the spare
    // one replaces it; the second finds the spare one in place and big
    // enough, and keeps it.
    const Seen seen = on_a_new_thread([] {
        std::vector<std::byte> spare(spare_room);
        std::vector<std::byte> other(spare_room);
        Seen out;
        out.spare = spare.data();
        out.size = spare.size();
        out.first = sq::raw::use_signal_stack(spare, std::numeric_limits<std::size_t>::max());
        out.after_first = current_signal_stack();
        out.second = sq::raw::use_signal_stack(other, spare_room);
        out.after_second = current_signal_stack();
        (void)disable_signal_stack();
        return out;
    });
    CHECK(seen.first);
    CHECK(enabled(seen.after_first));
    CHECK(seen.after_first.ss_sp == seen.spare);
    CHECK(seen.after_first.ss_size == seen.size);
    CHECK(seen.second);
    CHECK(seen.after_second.ss_sp == seen.spare);
}

TEST_CASE("a thread with no signal stack and no spare memory has none", "[raw]") {
    const Seen seen = on_a_new_thread([] {
        Seen out;
        if (disable_signal_stack()) {
            out.first = sq::raw::use_signal_stack({}, 1);
            out.after_first = current_signal_stack();
            out.second = true;
        }
        return out;
    });
    REQUIRE(seen.second);
    CHECK_FALSE(seen.first);
    CHECK_FALSE(enabled(seen.after_first));
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

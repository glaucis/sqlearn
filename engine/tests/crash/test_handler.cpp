/// @file
/// The crash group's program: a fatal signal after install() leaves a local
/// report, and the handler that was there before still runs. Each crash is
/// a forked child's, so the test program lives on.
#include "core/version.hpp"
#include "crash/handler.hpp"

#include <catch2/catch_test_macros.hpp>
#include <cpptrace/basic.hpp>
#include <cpptrace/forward.hpp>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <atomic>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
// std::hex, which include-what-you-use finds through <sstream> and
// misc-include-cleaner asks for by its own header.
#include <ios> // IWYU pragma: keep
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

#if defined(SQ_COVERAGE)
/// The coverage runtime's writer of this process's profile, which runs at
/// exit: a child that dies by a signal or leaves by _exit calls it first.
/// @return 0 when written.
// NOLINTNEXTLINE(bugprone-reserved-identifier,readability-identifier-naming): LLVM's own name
extern "C" int __llvm_profile_write_file(void);
#endif

namespace {

namespace fs = std::filesystem;

/// Write the coverage profile of a child about to end, in the coverage
/// flavour; nothing elsewhere. Async-signal-safe enough for a test: the
/// child is single-threaded and dying.
void flush_coverage() {
#if defined(SQ_COVERAGE)
    (void)__llvm_profile_write_file();
#endif
}

/// End a child with `code`, its coverage written first.
/// @param code The exit code.
[[noreturn]] void exit_child(int code) {
    flush_coverage();
    ::_exit(code);
}

/// The exit code of a child whose body returned instead of dying.
constexpr int returned = 99;
/// The exit code the test's own previous handler leaves.
constexpr int previous_code = 7;

/// A scratch directory, removed with everything in it at the end of a test.
class ScratchDir {
public:
    /// Make a fresh, empty directory under the system's temporary one.
    ScratchDir() {
        static std::atomic<int> count{0};
        path_ = fs::temp_directory_path() /
                ("sq-crash-" + std::to_string(::getpid()) + "-" + std::to_string(count++));
        fs::remove_all(path_);
        fs::create_directories(path_);
    }
    ScratchDir(const ScratchDir &) = delete;
    ScratchDir &operator=(const ScratchDir &) = delete;
    ScratchDir(ScratchDir &&) = delete;
    ScratchDir &operator=(ScratchDir &&) = delete;
    /// Remove the directory and its files.
    ~ScratchDir() {
        std::error_code ignored;
        fs::remove_all(path_, ignored);
    }
    /// The directory's path.
    /// @return It.
    [[nodiscard]] const fs::path &path() const { return path_; }

private:
    fs::path path_;
};

/// How a child process ended.
struct Ending {
    pid_t pid = -1;      ///< The child's process id.
    bool killed = false; ///< True when a signal ended it.
    int signal = 0;      ///< That signal, when killed.
    int code = -1;       ///< Its exit code, when it exited.
};

/// Run `body` in a forked child and wait for it to end.
/// @param body What the child does; it should not return.
/// @return How the child ended.
template <typename Body> Ending in_child(Body body) {
    const pid_t pid = ::fork();
    if (pid == 0) {
        body();
        exit_child(returned);
    }
    Ending ending;
    ending.pid = pid;
    int status = 0;
    if (pid > 0 && ::waitpid(pid, &status, 0) == pid) {
        ending.killed = WIFSIGNALED(status);
        ending.signal = ending.killed ? WTERMSIG(status) : 0;
        ending.code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    }
    return ending;
}

/// Set `signo`'s handler to `handler` (SIG_DFL or a function).
/// @param signo The signal.
/// @param handler What it does.
void set_handler(int signo, void (*handler)(int)) {
    struct sigaction action{};
    action.sa_handler = handler;
    sigemptyset(&action.sa_mask);
    ::sigaction(signo, &action, nullptr);
}

/// Write through a null pointer, which the compiler cannot see is null.
/// The sanitizers are off here, so the store itself faults.
[[gnu::noinline]] [[clang::no_sanitize("address", "undefined")]] void write_through_null() {
    static volatile std::uintptr_t zero = 0;
    // The crash under test: an address made from a number, then stored to.
    // NOLINTBEGIN(cppcoreguidelines-pro-type-reinterpret-cast,performance-no-int-to-ptr,clang-analyzer-core.NullDereference)
    auto *target = reinterpret_cast<volatile int *>(zero);
    *target = 1;
    // NOLINTEND(cppcoreguidelines-pro-type-reinterpret-cast,performance-no-int-to-ptr,clang-analyzer-core.NullDereference)
}

/// The test's own previous handler: it says so and exits.
/// @param signo The signal it handles.
extern "C" void previous_handler(int signo) {
    (void)signo;
    constexpr std::string_view said = "the previous handler ran\n";
    (void)::write(STDERR_FILENO, said.data(), said.size());
    exit_child(previous_code);
}

/// The previous handler of the tests that die by the signal: the default
/// action, once the coverage is written (in the coverage flavour).
/// @param signo The signal it handles.
extern "C" void default_handler(int signo) {
    flush_coverage();
    set_handler(signo, SIG_DFL);
    (void)::raise(signo);
}

/// Read the report a crashed child left in `dir`.
/// @param dir The directory install() was given.
/// @param pid The child's process id.
/// @return The report's text, empty when there is no report.
std::string report(const fs::path &dir, pid_t pid) {
    const auto path = dir / ("sqlearn-crash-" + std::to_string(pid) + ".txt");
    std::ifstream in(path);
    if (!in) {
        return {};
    }
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

/// Return the addresses of a report's faulting instruction and stack,
/// innermost first: each line "pc 0x<address> ..." or "#<n> 0x<address>
/// ..." gives one.
/// @param text The report.
/// @return Its frames' addresses.
std::vector<cpptrace::frame_ptr> stack(const std::string &text) {
    std::vector<cpptrace::frame_ptr> frames;
    std::istringstream lines(text);
    for (std::string line; std::getline(lines, line);) {
        const auto at = line.find(" 0x");
        if (!(line.starts_with('#') || line.starts_with("pc ")) || at == std::string::npos) {
            continue;
        }
        std::istringstream hex(line.substr(at + 3));
        cpptrace::frame_ptr address = 0;
        if (hex >> std::hex >> address) {
            frames.push_back(address);
        }
    }
    return frames;
}

/// Return the names of `frames`, resolved in this process: a child of fork
/// has this process's images at the same addresses.
/// @param frames Addresses from a child's report.
/// @return Each frame's symbol, demangled.
std::vector<std::string> names(const std::vector<cpptrace::frame_ptr> &frames) {
    cpptrace::raw_trace raw;
    raw.frames = frames;
    std::vector<std::string> out;
    for (const auto &frame : raw.resolve().frames) {
        out.push_back(frame.symbol);
    }
    return out;
}

/// Return whether one of `names` contains `part`.
/// @param all The names.
/// @param part What to look for.
/// @return True when one does.
bool any_names(const std::vector<std::string> &all, std::string_view part) {
    for (const auto &name : all) {
        if (name.find(part) != std::string::npos) {
            return true;
        }
    }
    return false;
}

} // namespace

TEST_CASE("a null write leaves a report and dies by its signal", "[crash]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGSEGV, default_handler);
        set_handler(SIGBUS, default_handler);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    REQUIRE(ending.killed);
    const bool fault = ending.signal == SIGSEGV || ending.signal == SIGBUS;
    CHECK(fault);
    const std::string text = report(dir.path(), ending.pid);
    REQUIRE_FALSE(text.empty());
    const std::string name = ending.signal == SIGSEGV ? "SIGSEGV" : "SIGBUS";
    CHECK(text.find("signal: " + name + " (" + std::to_string(ending.signal) + ")") !=
          std::string::npos);
    CHECK(text.find("fault address: 0x0\n") != std::string::npos);
    CHECK(text.find("pid: " + std::to_string(ending.pid) + "\n") != std::string::npos);
    CHECK(text.find("build: " + sq::core::describe(sq::core::build_identity()) + "\n") !=
          std::string::npos);
    CHECK(text.ends_with("end of report\n"));
    if (cpptrace::can_signal_safe_unwind()) {
        const auto frames = names(stack(text));
        CHECK(any_names(frames, "sq::crash"));
        CHECK(any_names(frames, "write_through_null"));
    } else {
        CHECK(text.find("stack: none") != std::string::npos);
    }
}

TEST_CASE("the handler that was there before runs after the report", "[crash]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGSEGV, previous_handler);
        set_handler(SIGBUS, previous_handler);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    CHECK_FALSE(ending.killed);
    CHECK(ending.code == previous_code);
    CHECK_FALSE(report(dir.path(), ending.pid).empty());
}

TEST_CASE("a report directory removed after install costs the report, not the crash", "[crash]") {
    const ScratchDir dir;
    const auto below = dir.path() / "reports";
    const auto ending = in_child([&] {
        set_handler(SIGABRT, default_handler);
        if (sq::crash::install(below)) {
            std::error_code ignored;
            fs::remove_all(below, ignored);
            std::abort();
        }
    });
    CHECK(ending.killed);
    CHECK(ending.signal == SIGABRT);
    CHECK_FALSE(fs::exists(below));
}

TEST_CASE("an abort leaves a report naming SIGABRT and still aborts", "[crash]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGABRT, default_handler);
        if (sq::crash::install(dir.path())) {
            std::abort();
        }
    });
    REQUIRE(ending.killed);
    CHECK(ending.signal == SIGABRT);
    const std::string text = report(dir.path(), ending.pid);
    REQUIRE_FALSE(text.empty());
    CHECK(text.find("signal: SIGABRT (" + std::to_string(SIGABRT) + ")") != std::string::npos);
}

TEST_CASE("install refuses a directory it cannot create and leaves the handlers", "[crash]") {
    const ScratchDir dir;
    const auto file = dir.path() / "a-file";
    std::ofstream(file) << "not a directory\n";
    const auto ending = in_child([&] {
        set_handler(SIGSEGV, SIG_DFL);
        const bool installed = sq::crash::install(file / "below");
        struct sigaction now{};
        ::sigaction(SIGSEGV, nullptr, &now);
        exit_child(!installed && now.sa_handler == SIG_DFL ? 0 : 1);
    });
    CHECK_FALSE(ending.killed);
    CHECK(ending.code == 0);
}

TEST_CASE("install creates the report directory when it is missing", "[crash]") {
    const ScratchDir dir;
    const auto below = dir.path() / "a" / "b";
    const auto ending = in_child([&] {
        // A second install changes nothing and says it is installed.
        exit_child(sq::crash::install(below) && sq::crash::install(below) ? 0 : 1);
    });
    CHECK(ending.code == 0);
    CHECK(fs::is_directory(below));
}

TEST_CASE("each handled signal sent by raise is reported by its name", "[crash]") {
    for (const auto &[signo, name] :
         {std::pair{SIGILL, "SIGILL"}, std::pair{SIGFPE, "SIGFPE"}, std::pair{SIGBUS, "SIGBUS"}}) {
        const ScratchDir dir;
        const auto ending = in_child([&] {
            set_handler(signo, default_handler);
            if (sq::crash::install(dir.path())) {
                (void)::raise(signo);
            }
        });
        CHECK(ending.killed);
        CHECK(ending.signal == signo);
        const std::string text = report(dir.path(), ending.pid);
        CHECK(text.find(std::string("signal: ") + name + " (") != std::string::npos);
    }
}

TEST_CASE("install_default puts the reports under the user's home", "[crash]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        // NOLINTBEGIN(concurrency-mt-unsafe,misc-include-cleaner): the child alone
        ::setenv("HOME", dir.path().c_str(), 1);
        ::unsetenv("XDG_STATE_HOME");
        // NOLINTEND(concurrency-mt-unsafe,misc-include-cleaner)
        exit_child(sq::crash::install_default() ? 0 : 1);
    });
    CHECK(ending.code == 0);
#if defined(__APPLE__)
    CHECK(fs::is_directory(dir.path() / "Library" / "Logs" / "sqlearn"));
#else
    CHECK(fs::is_directory(dir.path() / ".local" / "state" / "sqlearn"));
#endif
}

TEST_CASE("install_default installs nothing without a home", "[crash]") {
    const auto ending = in_child([&] {
        // NOLINTBEGIN(concurrency-mt-unsafe,misc-include-cleaner): the child alone
        ::unsetenv("HOME");
        ::unsetenv("XDG_STATE_HOME");
        // NOLINTEND(concurrency-mt-unsafe,misc-include-cleaner)
        exit_child(sq::crash::install_default() ? 1 : 0);
    });
    CHECK(ending.code == 0);
}

TEST_CASE("the report directory is the platform's place for logs", "[crash]") {
    using sq::crash::report_directory;
    CHECK(report_directory("/home/a", "", true) == fs::path("/home/a/Library/Logs/sqlearn"));
    CHECK(report_directory("/home/a", "/state", true) == fs::path("/home/a/Library/Logs/sqlearn"));
    CHECK(report_directory("/home/a", "/state", false) == fs::path("/state/sqlearn"));
    CHECK(report_directory("/home/a", "", false) == fs::path("/home/a/.local/state/sqlearn"));
    // XDG's rule: a relative XDG_STATE_HOME is invalid and is ignored.
    CHECK(report_directory("/home/a", "rel", false) == fs::path("/home/a/.local/state/sqlearn"));
    CHECK_FALSE(report_directory("", "", true).has_value());
    CHECK_FALSE(report_directory("", "", false).has_value());
    CHECK(report_directory("", "/state", false) == fs::path("/state/sqlearn"));
}

/// @file
/// The crash group's program: a fatal signal after install() leaves a local
/// report, and the handler that was there before still runs. Each crash is
/// a forked child's, so the test program lives on.
///
/// The cases tagged [signals] test how the handler chains a signal
/// (delivery, masks, SA_NODEFER, SA_RESETHAND, re-entry); the tsan flavour
/// runs the group with `~[signals]` (engine/CMakeLists.txt), since
/// ThreadSanitizer intercepts signals and delivers them late.
#include "core/version.hpp"
#include "crash/handler.hpp"

#include <catch2/catch_test_macros.hpp>
#include <cpptrace/basic.hpp>
#include <cpptrace/forward.hpp>

#include <sys/mman.h>
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
/// The longest a child may take before SIGALRM ends it. The alarm guards
/// the ordinary builds only: ThreadSanitizer defers signals, and a child
/// hung under it outlived the alarm. CTest's TIMEOUT on test_crash
/// (sq_test_timeout, engine/cmake/groups.cmake) is the guard for every
/// build.
constexpr unsigned child_seconds = 20;

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
        // A child that hangs (a fault inside the handler, with its signal
        // blocked, hangs on macOS) dies by SIGALRM, failing its test,
        // rather than stalling the run.
        ::alarm(child_seconds);
        // The default action ends a child before the coverage runtime
        // writes its profile at exit: write it first.
        sq::crash::detail::before_default = flush_coverage;
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

/// Return the reports a child left in `dir`: each named
/// sqlearn-crash-<pid>-<seconds>.txt.
/// @param dir The directory install() was given.
/// @param pid The child's process id.
/// @return Their paths.
std::vector<fs::path> reports(const fs::path &dir, pid_t pid) {
    const std::string prefix = "sqlearn-crash-" + std::to_string(pid) + "-";
    std::vector<fs::path> found;
    std::error_code error;
    for (const auto &entry : fs::directory_iterator(dir, error)) {
        const std::string name = entry.path().filename().string();
        if (name.starts_with(prefix) && name.ends_with(".txt") &&
            name.find_first_not_of("0123456789", prefix.size()) == name.size() - 4) {
            found.push_back(entry.path());
        }
    }
    return found;
}

/// Read the one report a crashed child left in `dir`.
/// @param dir The directory install() was given.
/// @param pid The child's process id.
/// @return The report's text, empty when there is not exactly one report.
std::string report(const fs::path &dir, pid_t pid) {
    const auto found = reports(dir, pid);
    if (found.size() != 1) {
        return {};
    }
    std::ifstream in(found.front());
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

TEST_CASE("the handler that was there before runs after the report", "[crash][signals]") {
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

namespace {

/// Return whether `info` is the kernel's for a memory fault: SIGSEGV's or
/// SIGBUS's own codes, never a signal a process sent (whose code is
/// SI_USER, SI_QUEUE or, from raise() on macOS, 0).
/// @param signo The signal.
/// @param info Its siginfo.
/// @return True for a fault's.
bool a_fault(int signo, const siginfo_t *info) {
    const int code = info->si_code;
    if (signo == SIGSEGV) {
        return code == SEGV_MAPERR || code == SEGV_ACCERR;
    }
    return signo == SIGBUS && (code == BUS_ADRALN || code == BUS_ADRERR || code == BUS_OBJERR);
}

/// The guard page the next test faults on, and what its handler saw.
struct Guard {
    void *page = nullptr;              ///< The PROT_NONE page.
    std::size_t size = 0;              ///< Its size.
    volatile sig_atomic_t calls = 0;   ///< How often the handler ran.
    volatile sig_atomic_t genuine = 0; ///< 1 when the kernel's siginfo came.
};

// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables): a signal handler's
Guard guard;

/// A runtime's guard-page handler, as a JVM's or wasm's: it opens the page
/// the fault was on and returns, so the store runs again and succeeds. It
/// needs the kernel's siginfo: a fault, not a signal sent, at the page.
/// @param signo The signal.
/// @param info What the kernel says of it.
/// @param context Unused.
extern "C" void guard_handler(int signo, siginfo_t *info, void *context) {
    (void)context;
    guard.calls = guard.calls + 1;
    if (a_fault(signo, info) && info->si_addr == guard.page) {
        guard.genuine = 1;
    }
    ::mprotect(guard.page, guard.size, PROT_READ | PROT_WRITE);
}

/// Store to `target`, past the sanitizers, so the store itself faults.
/// @param target Where to store.
[[gnu::noinline]] [[clang::no_sanitize("address", "undefined")]] void store_to(void *target) {
    *static_cast<volatile int *>(target) = 1;
}

} // namespace

TEST_CASE("a fault reaches a previous SA_SIGINFO handler as the kernel's, once",
          "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        guard.size = static_cast<std::size_t>(::getpagesize());
        guard.page = ::mmap(nullptr, guard.size, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
        struct sigaction action{};
        action.sa_sigaction = guard_handler;
        action.sa_flags = SA_SIGINFO;
        sigemptyset(&action.sa_mask);
        ::sigaction(SIGSEGV, &action, nullptr);
        ::sigaction(SIGBUS, &action, nullptr);
        if (guard.page == MAP_FAILED || !sq::crash::install(dir.path())) {
            exit_child(3);
        }
        store_to(guard.page);
        // Back here: the runtime's handler opened the page, once, with the
        // kernel's siginfo.
        exit_child(guard.calls == 1 && guard.genuine == 1 ? 0 : 1);
    });
    CHECK_FALSE(ending.killed);
    CHECK(ending.code == 0);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
}

TEST_CASE("a null write reaches a previous SA_SIGINFO handler with address 0", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        struct sigaction action{};
        action.sa_sigaction = [](int signo, siginfo_t *info, void *) {
            exit_child(a_fault(signo, info) && info->si_addr == nullptr ? 0 : 1);
        };
        action.sa_flags = SA_SIGINFO;
        sigemptyset(&action.sa_mask);
        ::sigaction(SIGSEGV, &action, nullptr);
        ::sigaction(SIGBUS, &action, nullptr);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    CHECK_FALSE(ending.killed);
    CHECK(ending.code == 0);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
}

TEST_CASE("a default previous action still ends the process by the fault", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGSEGV, SIG_DFL);
        set_handler(SIGBUS, SIG_DFL);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    CHECK(ending.killed);
    const bool fault = ending.signal == SIGSEGV || ending.signal == SIGBUS;
    CHECK(fault);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
}

TEST_CASE("a default action that says SA_SIGINFO still ends the process", "[crash][signals]") {
    // Python leaves SIGSEGV's default action with SA_SIGINFO set and no
    // handler: the flag must not make the handler call a null function.
    const ScratchDir dir;
    const auto ending = in_child([&] {
        struct sigaction action{};
        action.sa_handler = SIG_DFL;
        action.sa_flags = SA_SIGINFO;
        sigemptyset(&action.sa_mask);
        ::sigaction(SIGSEGV, &action, nullptr);
        ::sigaction(SIGBUS, &action, nullptr);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    CHECK(ending.killed);
    const bool fault = ending.signal == SIGSEGV || ending.signal == SIGBUS;
    CHECK(fault);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
}

namespace {

/// A previous handler like CPython's faulthandler (SA_NODEFER): it puts
/// the default back, then faults itself, which must end the process.
/// @param signo The signal.
/// @param info Unused.
/// @param context Unused.
extern "C" void faulting_handler(int signo, siginfo_t *info, void *context) {
    (void)info;
    (void)context;
    flush_coverage();
    set_handler(SIGSEGV, SIG_DFL);
    set_handler(SIGBUS, SIG_DFL);
    (void)signo;
    write_through_null();
}

/// A previous handler installed with SA_RESETHAND: the kernel would have
/// put the default back before calling it.
/// @param signo The signal.
extern "C" void resethand_handler(int signo) {
    struct sigaction now{};
    ::sigaction(signo, nullptr, &now);
    exit_child(now.sa_handler == SIG_DFL ? 0 : 2);
}

} // namespace

TEST_CASE("a fault in a previous SA_NODEFER handler ends the process", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        struct sigaction action{};
        action.sa_sigaction = faulting_handler;
        action.sa_flags = SA_SIGINFO | SA_NODEFER;
        sigemptyset(&action.sa_mask);
        ::sigaction(SIGSEGV, &action, nullptr);
        ::sigaction(SIGBUS, &action, nullptr);
        if (sq::crash::install(dir.path())) {
            write_through_null();
        }
    });
    CHECK(ending.killed);
    const bool fault = ending.signal == SIGSEGV || ending.signal == SIGBUS;
    CHECK(fault);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
}

TEST_CASE("a fault inside sqlearn's report ends the process", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGSEGV, default_handler);
        set_handler(SIGBUS, default_handler);
        sq::crash::detail::fault_in_report = write_through_null;
        if (sq::crash::install(dir.path())) {
            (void)::raise(SIGSEGV);
        }
    });
    CHECK(ending.killed);
    const bool fault = ending.signal == SIGSEGV || ending.signal == SIGBUS;
    CHECK(fault);
}

TEST_CASE("a previous SA_RESETHAND handler runs with the default back", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        struct sigaction action{};
        action.sa_handler = resethand_handler;
        action.sa_flags = SA_RESETHAND;
        sigemptyset(&action.sa_mask);
        ::sigaction(SIGILL, &action, nullptr);
        if (sq::crash::install(dir.path())) {
            (void)::raise(SIGILL);
        }
    });
    CHECK_FALSE(ending.killed);
#if defined(__APPLE__)
    // macOS does not report SA_RESETHAND back through sigaction(2) (its
    // sa_flags come back 0), so the handler cannot honour it there: the
    // previous handler runs, and stays in place.
    CHECK(ending.code == 2);
#else
    CHECK(ending.code == 0);
#endif
}

TEST_CASE("an ignored signal stays ignored after the report", "[crash][signals]") {
    const ScratchDir dir;
    const auto ending = in_child([&] {
        set_handler(SIGFPE, SIG_IGN);
        if (sq::crash::install(dir.path())) {
            (void)::raise(SIGFPE);
        }
    });
    CHECK_FALSE(ending.killed);
    CHECK(ending.code == returned);
    CHECK(reports(dir.path(), ending.pid).size() == 1);
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

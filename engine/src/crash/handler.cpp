/// @file
/// The crash handler. Everything it reads in a signal is prepared by
/// install(): the report's path up to the process id, the build's line and
/// the images' table, each in fixed storage, so the handler allocates
/// nothing, takes no lock and calls only async-signal-safe functions:
/// getpid, clock_gettime, open, write, close, sigaction, pthread_sigmask,
/// raise and cpptrace's
/// safe_generate_raw_trace.
#include "crash/handler.hpp"

#include "core/version.hpp"
#include "raw/fd_writer.hpp"
#include "raw/fixed_text.hpp"
#include "raw/images.hpp"

#include <cpptrace/basic.hpp>
#include <cpptrace/forward.hpp>

#include <fcntl.h>
#include <sys/types.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstddef> // IWYU pragma: keep
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <mutex>
#include <optional>
#include <span>
// The std::string describe() returns and path::native() gives, which
// include-what-you-use counts as a use of <string>, misc-include-cleaner
// does not.
#include <string> // IWYU pragma: keep
#include <string_view>
#include <system_error>

namespace sq::crash {

namespace {

namespace fs = std::filesystem;

/// The deepest stack a report prints.
constexpr std::size_t max_frames = 128;
/// The most images a report can name; a Python process with DuckDB loads
/// a few hundred.
constexpr std::size_t max_images = 1024;
/// The longest directory path a report can go to, with its file's name.
constexpr std::size_t max_path = 1024;
/// Room for the file name after that prefix: a process id, "-", the
/// seconds and ".txt", each number at most 20 digits, so the path is never
/// cut.
constexpr std::size_t max_name = 48;
/// The longest build line core::describe gives that a report keeps whole.
constexpr std::size_t max_build = 512;
/// How many signals the handler takes: SIGSEGV, SIGBUS, SIGILL, SIGFPE and
/// SIGABRT.
constexpr std::size_t handled = 5;
/// The report's file mode: the user alone reads and writes it.
constexpr mode_t report_mode = 0600;

/// A fatal signal and the action it had before install().
struct Previous {
    int signo = 0;             ///< The signal.
    std::string_view name;     ///< Its name, such as "SIGSEGV".
    struct sigaction action{}; ///< What it did before.
};

/// What the handler reads, prepared by install(). Trivially destructible,
/// so a crash during the process's exit still finds it.
struct State {
    raw::FixedText<max_path> prefix;           ///< "<dir>/sqlearn-crash-".
    raw::FixedText<max_build> build;           ///< core::describe's line.
    std::array<raw::Image, max_images> images; ///< The images at install.
    std::size_t image_count = 0;               ///< How many of them.
    /// The signals handled, and what each did before.
    std::array<Previous, handled> previous{{{SIGSEGV, "SIGSEGV"},
                                            {SIGBUS, "SIGBUS"},
                                            {SIGILL, "SIGILL"},
                                            {SIGFPE, "SIGFPE"},
                                            {SIGABRT, "SIGABRT"}}};
};

// The handler's state is process-wide by nature: a signal handler reaches
// nothing else.
// NOLINTBEGIN(cppcoreguidelines-avoid-non-const-global-variables)
// NOLINTNEXTLINE(bugprone-throwing-static-initialization): constinit, so nothing runs
constinit State state{};

static_assert(std::atomic<bool>::is_always_lock_free, "the handler's flags must be lock-free");

/// Set once the handlers are installed.
constinit std::atomic<bool> installed{false};
/// Set by the first crash to report, so a second crash (another thread, or
/// a fault while reporting) writes nothing and goes to the previous handler.
constinit std::atomic<bool> reporting{false};
// NOLINTEND(cppcoreguidelines-avoid-non-const-global-variables)

/// Return the entry of `signo` among the handled signals.
/// @param signo A signal number.
/// @return Its entry, or null for a signal the handler was not set for.
const Previous *entry_of(int signo) noexcept {
    for (const Previous &previous : state.previous) {
        if (previous.signo == signo) {
            return &previous;
        }
    }
    return nullptr;
}

/// Write `address` and the image it falls in, then end the line.
/// @param out The report.
/// @param address A code address.
void write_place(raw::FdWriter &out, std::uintptr_t address) noexcept {
    out.hex(address);
    const raw::Image *image =
        raw::image_of(std::span(state.images).first(state.image_count), address);
    if (image == nullptr) {
        out.text(" (in no image loaded when the handler was installed)\n");
        return;
    }
    out.text(" ").text(image->path != nullptr ? std::string_view(image->path) : "(the program)");
    out.text(" (load address ").hex(image->load).text(")\n");
}

/// Write the faulting instruction and the stack, innermost frame first,
/// each address with the image it falls in, to symbolise outside the crash.
/// @param out The report.
/// @param context The handler's context, or null.
void write_stack(raw::FdWriter &out, const void *context) noexcept {
#if defined(__APPLE__)
    out.text("symbolise an address with atos -o <image> -l <load address> <address>\n");
#else
    out.text("symbolise an address with addr2line -f -C -e <image> <address - load address>\n");
#endif
    if (const std::uintptr_t pc = raw::context_pc(context); pc != 0) {
        out.text("pc ");
        write_place(out, pc);
    }
    if (!cpptrace::can_signal_safe_unwind()) {
        out.text("stack: none (cpptrace has no signal-safe unwinding on this platform)\n");
        return;
    }
    std::array<cpptrace::frame_ptr, max_frames> buffer{};
    const std::size_t count = cpptrace::safe_generate_raw_trace(buffer.data(), buffer.size());
    out.text("stack, innermost first:\n");
    std::uintmax_t index = 0;
    for (const cpptrace::frame_ptr address : std::span(buffer).first(count)) {
        out.text("#").decimal(index++).text(" ");
        write_place(out, address);
    }
}

/// Write the report of a signal to `out`.
/// @param out The report's file.
/// @param signal The signal's entry.
/// @param info What the kernel says of it, or null.
/// @param context The handler's context, or null.
void write_report(raw::FdWriter &out, const Previous &signal, const siginfo_t *info,
                  const void *context) noexcept {
    out.text("sqlearn crash report\n");
    out.text("signal: ").text(signal.name).text(" (").decimal(signal.signo).text(")\n");
    out.text("fault address: ")
        .hex(info != nullptr ? raw::address_of(info->si_addr) : 0)
        .text("\n");
    out.text("pid: ").decimal(static_cast<std::uintmax_t>(::getpid())).text("\n");
    out.text("build: ").text(state.build.view()).text("\n");
    out.text("This file stays on this machine: sqlearn sends nothing anywhere.\n");
    out.text("The handler that was there before sqlearn's runs after this report and may\n"
             "have handled the signal: if the process went on, this was no crash.\n"
             "sqlearn's handler is unhooked after this, its first report.\n");
    write_stack(out, context);
    out.text("end of report\n");
}

/// Write the report to `<dir>/sqlearn-crash-<pid>-<seconds>.txt` and say
/// where on standard error.
/// @param signal The signal's entry.
/// @param info What the kernel says of it.
/// @param context The handler's context.
void report(const Previous &signal, const siginfo_t *info, const void *context) noexcept {
#if defined(SQ_CRASH_TEST_HOOKS)
    if (detail::fault_in_report != nullptr) {
        detail::fault_in_report();
    }
#endif
    raw::FixedText<max_path + max_name> path;
    // The time as well as the pid, so a pid the system reuses never writes
    // over an earlier report. clock_gettime is async-signal-safe.
    struct timespec now{};
    (void)::clock_gettime(CLOCK_REALTIME, &now);
    path.append(state.prefix.view())
        .append_number(static_cast<std::uintmax_t>(::getpid()))
        .append("-")
        .append_number(static_cast<std::uintmax_t>(now.tv_sec < 0 ? 0 : now.tv_sec))
        .append(".txt");
    constexpr int flags = O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW;
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg): open(2) is variadic
    const int fd = ::open(path.c_str(), flags, report_mode);
    if (fd < 0) {
        return;
    }
    raw::FdWriter file(fd);
    write_report(file, signal, info, context);
    ::close(fd);
    if (file.ok()) {
        raw::FdWriter(STDERR_FILENO)
            .text("sqlearn: ")
            .text(signal.name)
            .text(" reached sqlearn's handler; a report is in ")
            .text(path.view())
            .text("\n");
    }
}

/// Put back the action a signal had before install(), and run it, with the kernel's own
/// siginfo and context, once. Its handler is called here, as the kernel
/// would call it, rather than through raise(): raise() would hand it a
/// signal sent, not the fault, and a handler that returns (a runtime's
/// guard page) would then run twice (ADR 0046). The previous action is
/// back in place first, so what happens next is what would have happened
/// without sqlearn: a fault whose handler returns runs its instruction
/// again. macOS gives a signal sent a fault's si_code, so the handler
/// cannot be told which it is; calling it covers both.
/// @param signal The signal's entry.
/// @param info What the kernel says of it.
/// @param context The interrupted context.
void run_previous(const Previous &signal, siginfo_t *info, void *context) noexcept {
    const int signo = signal.signo;
    const struct sigaction &action = signal.action;
    ::sigaction(signo, &action, nullptr);
    const auto flags = static_cast<unsigned>(action.sa_flags);
    const bool with_info = (flags & static_cast<unsigned>(SA_SIGINFO)) != 0;
    // SIG_DFL and SIG_IGN whatever the flags say: Python leaves SIGSEGV's
    // default action with SA_SIGINFO set and no handler, and a call
    // through that null pointer, with the signal blocked, hangs on macOS.
    if (action.sa_handler == SIG_DFL) {
        // Not blocked (this handler has SA_NODEFER): the default action
        // ends the process by the signal here.
#if defined(SQ_CRASH_TEST_HOOKS)
        if (detail::before_default != nullptr) {
            detail::before_default();
        }
#endif
        ::raise(signo);
        return;
    }
    if (action.sa_handler == SIG_IGN) {
        return;
    }
    if ((flags & static_cast<unsigned>(SA_RESETHAND)) != 0) {
        struct sigaction reset{};
        reset.sa_handler = SIG_DFL;
        sigemptyset(&reset.sa_mask);
        ::sigaction(signo, &reset, nullptr);
    }
    // The mask the kernel would give the call: its sa_mask, and the signal
    // itself blocked unless SA_NODEFER, which CPython's faulthandler sets
    // so that a fault while it dumps ends the process. Its action is back
    // in place, so that fault reaches it, or the default, at once.
    sigset_t mask = action.sa_mask;
    sigset_t self{};
    sigemptyset(&self);
    sigaddset(&self, signo);
    const bool nodefer = (flags & static_cast<unsigned>(SA_NODEFER)) != 0;
    if (!nodefer) {
        sigaddset(&mask, signo);
    }
    sigset_t before{};
    ::pthread_sigmask(SIG_BLOCK, &mask, &before);
    if (nodefer) {
        ::pthread_sigmask(SIG_UNBLOCK, &self, nullptr);
    }
    if (with_info) {
        action.sa_sigaction(signo, info, context);
    } else {
        action.sa_handler(signo);
    }
    ::pthread_sigmask(SIG_SETMASK, &before, nullptr);
}

/// The handler: report once, then put back the previous action and run it,
/// with the kernel's siginfo (run_previous).
/// @param signo The signal.
/// @param info What the kernel says of it.
/// @param context The interrupted context.
void on_signal(int signo, siginfo_t *info, void *context) {
    const int saved = errno;
    const Previous *signal = entry_of(signo);
    // Installed with SA_NODEFER, so a fault inside the report comes back
    // here at once: the report is skipped, and the previous action ends
    // the process, rather than a blocked signal hanging it (macOS).
    if (signal != nullptr && !reporting.exchange(true)) {
        report(*signal, info, context);
    }
    errno = saved;
    if (signal != nullptr) {
        run_previous(*signal, info, context);
    }
}

/// Make the lazily bound functions the handler calls bound now: their
/// first call may allocate (cpptrace's docs/signal-safe-tracing.md).
void warm_up() noexcept {
    std::array<cpptrace::frame_ptr, 4> buffer{};
    (void)cpptrace::safe_generate_raw_trace(buffer.data(), buffer.size());
    (void)cpptrace::can_signal_safe_unwind();
    (void)::getpid();
}

/// Serialises install().
// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables): install()'s lock
std::mutex installing;

/// Fill the state the handler reads, for reports in `dir`.
/// @param dir The report directory, which this creates when missing.
/// @return False when it cannot be created or its path is too long.
/// @throws std::bad_alloc when the paths or the build's line cannot be
///         made.
bool prepare(const fs::path &dir) {
    std::error_code error;
    const fs::path absolute = fs::absolute(dir, error);
    if (error) {
        return false;
    }
    fs::create_directories(absolute, error);
    if (error || !fs::is_directory(absolute, error)) {
        return false;
    }
    state.prefix = {};
    state.prefix.append((absolute / "sqlearn-crash-").native());
    state.build = {};
    state.build.append(core::describe(core::build_identity()));
    state.image_count = raw::loaded_images(state.images);
    warm_up();
    return !state.prefix.truncated();
}

/// Set the handler for every handled signal, keeping what each did before.
/// sigaction(2) fails only for a signal that cannot be caught or does not
/// exist, or for a bad pointer, none of which these are.
/// @return True when all are set.
bool set_handlers() noexcept {
    struct sigaction action{};
    action.sa_sigaction = on_signal;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK | SA_NODEFER;
    sigemptyset(&action.sa_mask);
    bool all = true;
    for (Previous &previous : state.previous) {
        all = ::sigaction(previous.signo, &action, &previous.action) == 0 && all;
    }
    return all;
}

} // namespace

#if defined(SQ_CRASH_TEST_HOOKS)
// NOLINTBEGIN(cppcoreguidelines-avoid-non-const-global-variables): the tests' hooks
void (*detail::fault_in_report)() = nullptr;
void (*detail::before_default)() = nullptr;
// NOLINTEND(cppcoreguidelines-avoid-non-const-global-variables)
#endif

std::optional<fs::path> report_directory(std::string_view home, std::string_view xdg_state_home,
                                         bool macos) {
    if (macos) {
        if (home.empty()) {
            return std::nullopt;
        }
        return fs::path(home) / "Library" / "Logs" / "sqlearn";
    }
    if (!xdg_state_home.empty() && fs::path(xdg_state_home).is_absolute()) {
        return fs::path(xdg_state_home) / "sqlearn";
    }
    if (home.empty()) {
        return std::nullopt;
    }
    return fs::path(home) / ".local" / "state" / "sqlearn";
}

bool install(const fs::path &dir) noexcept {
    try {
        const std::scoped_lock lock(installing);
        if (installed.load()) {
            return true;
        }
        if (!prepare(dir) || !set_handlers()) {
            return false;
        }
        installed.store(true);
        return true;
    } catch (...) {
        // An allocation for the paths or the build's line failed: no
        // handler is better than failing the import.
        return false;
    }
}

bool install_default() noexcept {
    try {
        // NOLINTBEGIN(concurrency-mt-unsafe): read once, at the module's load
        const char *home = std::getenv("HOME");
        const char *state_home = std::getenv("XDG_STATE_HOME");
        // NOLINTEND(concurrency-mt-unsafe)
#if defined(__APPLE__)
        constexpr bool macos = true;
#else
        constexpr bool macos = false;
#endif
        const auto dir = report_directory(home != nullptr ? home : "",
                                          state_home != nullptr ? state_home : "", macos);
        return dir.has_value() && install(*dir);
    } catch (...) {
        return false;
    }
}

} // namespace sq::crash

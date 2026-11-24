/// @file
/// The crash report: on a fatal signal, sqlearn writes what it knows of the
/// crash to a file on this machine, then lets the handler that was there
/// before run (Python's faulthandler, the user's own, or the default that
/// ends the process). The report is never sent anywhere (ADR 0006).
#pragma once

#include <filesystem>
#include <optional>
#include <string_view>

namespace sq::crash {

/// Return the directory crash reports go to: on macOS
/// `<home>/Library/Logs/sqlearn`; elsewhere `<xdg_state_home>/sqlearn`
/// when it is an absolute path (XDG's rule: a relative one is ignored),
/// else `<home>/.local/state/sqlearn`.
/// @param home The user's home directory ($HOME), or empty.
/// @param xdg_state_home $XDG_STATE_HOME, or empty.
/// @param macos True on macOS.
/// @return The directory, or nothing when there is no home to put it in.
/// @throws std::bad_alloc when there is no memory for the path.
[[nodiscard]] std::optional<std::filesystem::path>
report_directory(std::string_view home, std::string_view xdg_state_home, bool macos);

/// Install the crash handler for SIGSEGV, SIGBUS, SIGILL, SIGFPE and
/// SIGABRT, writing to `dir`, which is created when missing. On one of
/// them it writes `<dir>/sqlearn-crash-<pid>-<seconds>.txt` (once a
/// process): the signal, the faulting address, the process, sqlearn's and
/// DuckDB's versions and build, and the stack (cpptrace's signal-safe
/// trace, each address with the image it falls in, to symbolise later).
/// Then it restores the handler that was there before and runs it once,
/// with the kernel's own siginfo and context: a handler of the user's or a
/// runtime's is called as the kernel would call it, the default action is
/// raised again, so it ends the process by the signal, and an ignored
/// signal is ignored. The handler allocates nothing and calls only
/// async-signal-safe functions.
///
/// It reports once a process and then unhooks: the previous action stays
/// in place, so a later signal goes to it alone. The report and its line
/// on standard error say the signal reached sqlearn's handler, since the
/// previous handler may have handled it. Installed with SA_NODEFER, so a
/// fault inside the report, or inside a previous handler that sets
/// SA_NODEFER (CPython's faulthandler), ends the process instead of
/// hanging it.
///
/// Installing happens once in a process: a later call changes nothing.
/// @param dir The directory for the reports.
/// @return True when the handler is installed (now or before); false when
///         `dir` could not be created, in which case no handler of the
///         process is changed.
[[nodiscard]] bool install(const std::filesystem::path &dir) noexcept;

/// Install the crash handler into report_directory() for this user ($HOME
/// and $XDG_STATE_HOME). What the module does when it is loaded.
/// @return What install() returns; false when there is no directory.
[[nodiscard]] bool install_default() noexcept;

#if defined(SQ_CRASH_TEST_HOOKS)
namespace detail {

/// Tests only (SQ_CRASH_TEST_HOOKS, which a preset's build sets and the
/// wheel's never does): when set, the report calls it before it writes
/// anything, so a test can fault inside the report.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables): a test's hook
extern void (*fault_in_report)();

/// Tests only: when set, called just before the default action is raised,
/// so the coverage flavour writes a dying child's profile.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables): a test's hook
extern void (*before_default)();

} // namespace detail
#endif

} // namespace sq::crash

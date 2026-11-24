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
/// them it writes `<dir>/sqlearn-crash-<pid>.txt`: the signal, the faulting
/// address, the process, sqlearn's and DuckDB's versions and build, and
/// the stack (cpptrace's signal-safe trace, each address with the image it
/// falls in, to symbolise later); then it restores the handler that was
/// there before and raises the signal again, so that handler runs. The
/// handler allocates nothing and calls only async-signal-safe functions.
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

} // namespace sq::crash

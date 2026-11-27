---
type: adr
tags: [engine, crash, signals, macos, linux, safety, architecture-decision]
summary: "Records that sqlearn's crash handler, after its report, calls the previous handler once with the kernel's own siginfo and context, on macOS and Linux alike, rather than re-raising the signal or returning to let the fault recur."
related: [docs/adr/0065-safety-rules-for-the-cpp.md, docs/adr/0006-local-and-offline.md, docs/specs/native-engine-phase-1.md]
---
# 0069: The crash handler hands the fault on

Status: accepted (2026-11-26). Decided by Tomas on 2026-11-26.
Departs from the Phase 1 build plan's Task 11, which said "restores and
re-raises the previous handler".

## Context

sqlearn's crash handler (`engine/src/crash/handler.cpp`,
[ADR 0065](0065-safety-rules-for-the-cpp.md)) writes a local report on
SIGSEGV, SIGBUS, SIGILL, SIGFPE and SIGABRT, then must let the handler that
was there before it run: Python's `faulthandler`, the user's own, or the
default that ends the process. Three ways to do that were weighed:

1. **Re-raise** (the plan): put the previous action back and `raise()` the
   signal. The previous handler then sees a signal sent, not the fault: the
   faulting address and the faulting instruction's context are lost.
2. **Return and let the fault recur** (Breakpad, Crashpad on Linux): put
   the previous action back and return. A hardware fault runs its
   instruction again, faults again, and the kernel itself delivers it to
   the previous handler, exactly as without sqlearn. A signal that was only
   sent does not recur, so this needs telling the two apart, and re-raising
   the sent ones.
3. **Hand the fault on**: put the previous action back and call its handler
   once, with the kernel's own siginfo and context and the mask the kernel
   would give it.

A probe on macOS 27.2.1 (arm64, 2026-11-26) showed that macOS cannot tell
way 2 which signals were sent. A null write, `raise(SIGSEGV)`,
`pthread_kill`, `kill` from the process itself and `kill` from another
process all arrive with the same siginfo: `si_code` 2, `si_pid` 0,
`si_addr` 0. The exception syndrome register in the context (`__es.__esr`)
is stale for a sent signal: a process taking page faults, sent SIGSEGV by
`kill`, shows a data abort (EC 0x24) as a real fault does. Linux marks a
sent signal (`si_code` `SI_USER` or `SI_TKILL`, at most 0) and reports
`SA_RESETHAND` back from `sigaction`, but sqlearn takes one way for both.

Telling a real fault from a sent one on macOS needs Mach exception ports
(Crashpad's way there): a thread of its own, a handler that runs before
every signal handler, and conflicts with debuggers and the system's crash
reporter. That was left out as more code and risk than its gain.

## Decision

- After its report, the crash handler hands the fault on (way 3), on macOS
  and Linux alike: one way, tested on both.
- A previous `SIG_DFL` is raised again, so the process ends by the signal;
  a previous `SIG_IGN` is ignored.
- The handler reports once a process and leaves the previous action in
  place, so a fault that recurs goes to the previous handler alone.
- Mach exception ports are not used.

## Consequences

- The previous handler sees the real fault: its address, its siginfo and
  the faulting instruction's context.
- On macOS `sigaction` does not report `SA_RESETHAND` back, so it cannot be
  honoured there: a previous handler that relies on it and returns from a
  hardware fault can loop. Linux honours it.
- The previous handler runs on the stack sqlearn's handler runs on, not
  necessarily the one the kernel would have chosen for it.
- Windows has no POSIX signals: it needs its own crash handler, written
  when the Windows build starts.

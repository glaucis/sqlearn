---
type: architecture
tags: [crash, signals, reports, engine, safety]
summary: "What sqlearn's crash report holds, where it goes, that nothing is sent, and the crashes it cannot report."
related: [docs/adr/0069-the-crash-handler-hands-the-fault-on.md, docs/adr/0006-local-and-offline.md, engine/src/crash/handler.hpp, engine/src/crash/handler.cpp, docs/architecture/testing.md]
---
# Crash reports

When sqlearn's C++ crashes, its handler (`engine/src/crash/handler.cpp`)
writes a report before the crash goes on as it would have without sqlearn
(ADR 0069). It is there so a crash leaves something to debug, not only
"Python quit".

## What a report holds and where it goes

One file a process, `sqlearn-crash-<pid>-<seconds>.txt`: on macOS in
`~/Library/Logs/sqlearn/`, elsewhere in `$XDG_STATE_HOME/sqlearn/` or
`~/.local/state/sqlearn/`. It names the signal (`SIGSEGV`, `SIGBUS`, `SIGILL`,
`SIGFPE` or `SIGABRT`), the faulting address, the process, sqlearn's and
DuckDB's versions and build, and the stack: each frame's address with the
image (library) it falls in and that image's load address. The handler runs
in the middle of a crash, so it writes addresses, not function names: it may
allocate nothing and take no lock. The report says how to turn them into
names (`atos` on macOS, `addr2line` on Linux), with the same build.

The report holds no data from the user's tables, only where in the code the
crash happened. It stays on the machine: sqlearn sends nothing anywhere (ADR
0006). A user who wants a crash fixed attaches the file to an issue.

## What it covers

- A crash on any thread: a bad memory access, an illegal instruction, a
  division fault, an abort.
- A stack overflow on the thread that installed the handler, the one that
  imported sqlearn (Python's main thread, as a rule): that thread gets a
  spare signal stack of 256 KiB to run the handler on, unless it has one of
  64 KiB or more already (Python's faulthandler and AddressSanitizer bring
  their own, which are kept). Without one, the handler has no stack left to
  run on, and macOS ends the process by `SIGILL` with no report.
- An image unloaded after sqlearn was imported: each image's path is copied
  when the handler is installed, so the report never reads the loader's
  freed copy.
- Two threads crashing at once: the first writes the report, and the second
  waits for it, at most five seconds, before its own crash goes on, so the
  report is never cut short.

## What it cannot report

- A stack overflow on any other thread, DuckDB's worker threads among them:
  they have no spare stack (Tomas, 2026-11-28), since DuckDB starts them and
  its code is never edited. Such an overflow ends the process with no
  report.
- A process stopped from outside, with no chance to run any code: `kill -9`,
  the system ending it for using too much memory, a power loss.
- A crash that has already damaged the handler's own memory.

The tests (`engine/tests/crash/test_handler.cpp`, each crash in a forked
child) cover each case above that a report covers.

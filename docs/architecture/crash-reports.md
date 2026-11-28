---
type: architecture
tags: [crash, signals, reports, engine, safety]
summary: "What sqlearn's crash report holds, where it goes, that nothing is sent, the crashes it cannot report, and how just crash-report reads one and tells sqlearn's crash from DuckDB's."
related: [docs/adr/0069-the-crash-handler-hands-the-fault-on.md, docs/adr/0006-local-and-offline.md, engine/src/crash/handler.hpp, engine/src/crash/handler.cpp, docs/architecture/testing.md, validation/_crash_report.py]
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

## Reading a report

`just crash-report <file>` (`validation/_crash_report.py`) prints each frame
with whose code it is and its function, then which code most likely crashed:

```text
SIGSEGV, sqlearn 0.1…, DuckDB 2.0.1 (8d78114e90), AppleClang 21…, Release
pc system  _platform_strlen
#0 sqlearn sq::crash::(anonymous namespace)::on_signal(int, __siginfo*, void*)
#1 system  _sigtramp
#2 Python  string_at
…

Neither sqlearn's nor DuckDB's code crashed: the fault is in
_platform_strlen (system), and no frame below the crash handler is theirs.
```

It needs the build that wrote the report: the report's build line must be
the installed sqlearn's, or it refuses, naming the build to check out. A
user's report is read with the map of the release that wrote it instead:
each release attaches `sqlearn-<version>-<platform>.map` and its build line,
`sqlearn-<version>-<platform>.map.build`, beside the wheels. Download both
into one folder, then

```sh
just crash-report ~/sqlearn-crash-20261128-101500-4242.txt --map ~/sqlearn-1.0.0-macosx_15_0_arm64.map
```

The reader checks the report's build line against the `.build` file and
refuses a map of another build, which would name the frames wrongly. It
reads reports on macOS and on Linux.

**Where the names come from.** The module is linked with nanobind's `-x -S`,
which drops every local symbol, so none of sqlearn's functions (hidden by
design) is named in the binary, and `atos` would name each after the DuckDB
symbol before it. The link writes a map of the module beside the build
(`build/<cache tag>/_duckdb.map`, never in the wheel): every symbol's address
and the object file it came from. The reader names the module's frames from
it, and takes their owner from that object: sqlearn's groups and extension,
DuckDB's library, extensions and Python module, nanobind, cpptrace. Other
images are named by `atos` on macOS and `addr2line` on Linux, and owned by
Python (its library, program or extension modules) or the system. ld64 writes
the map on macOS and GNU ld (manylinux's GCC) on Linux, each in its own
format; the reader takes both. A library of the system's shared cache is
named through the reader's own process (`atos -p`), where it sits at the
same address until the next boot: its file on disk is not the copy that
ran, and `atos -o` on it gives wrong names. After a reboot those frames may
go unnamed. The map gives no file and line; a separate debug-symbols file
(`.dSYM`) would, if that is wanted later.

**Whose bug it is.** The reader skips the crash handler's own frames
(`sq::crash`, cpptrace, `_sigtramp`) and takes the nearest frame to the
fault that is sqlearn's or DuckDB's: the faulting instruction itself, else
its nearest caller, since a fault in a system function (`memcpy`, say) is
its caller's. Where it stops says the code that crashed, not always whose
mistake it was: sqlearn can hand DuckDB something wrong that only fails
inside DuckDB. So for a crash in DuckDB's code, reproduce it in plain
DuckDB 2.0.1, the official `duckdb` package in an environment of its own,
with the SQL sqlearn ran and made-up data shaped like the user's, never
their data:

- It crashes there too: DuckDB's bug. Report it on DuckDB's issue tracker
  with that SQL, and tell the user it is DuckDB's, reported upstream.
- It does not: sqlearn's calls reached DuckDB in a state it does not
  expect, and it is sqlearn's to fix.

sqlearn's DuckDB is DuckDB's release unchanged (the submodules are never
edited, and the configure refuses one with local edits), so plain DuckDB is
a fair comparison.

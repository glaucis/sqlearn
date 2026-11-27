---
type: question
tags: [python, threading, free-threaded, gil, nanobind, bindings]
summary: "Open question on whether sqlearn should support free-threaded Python (3.14t, no GIL): what it would change, what it would cost, and what it depends on."
related: [docs/specs/native-engine-phase-1.md, docs/specs/native-engine.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/archived/0067-how-computation-moves-to-the-engine.md]
---
# Should sqlearn support free-threaded Python?

Open since 2026-11-22 (Tomas). To decide in Phase 1 step 2, once the
bindings exist; a yes needs an ADR.

## What it is

Python normally has a global interpreter lock (the GIL): one thread runs
Python code at a time, so eight threads on eight cores still take turns.
Free-threaded Python is a separate build without that lock (`python3.14t`),
where threads run Python code at the same time. It was experimental in 3.13
and is supported from 3.14, as a build one installs on purpose; the usual
`python3.14` keeps the lock. It chooses no thread count: the program still
starts its own threads.

## What it would change for sqlearn

Little, as far as known today. sqlearn's work runs in DuckDB, in C++,
which uses every core itself and releases the GIL while it works, so one
pipeline is already parallel. Free-threading would help only a user who
runs several sqlearn calls from several Python threads at once, and then
only in the thin Python layer between them.

## What it would cost

- Bindings safe without the lock: nanobind supports free-threaded builds,
  but every value shared between threads then needs its own locking,
  checked by ThreadSanitizer and `-Wthread-safety`.
- One more wheel per platform (`cp314t`), and the tests run on that build.

## What it depends on

sqlearn is compiled into DuckDB's Python package (spec §3.3), so it can be
free-threaded only if DuckDB's Python package is. Not yet checked.

## Open points

- Does DuckDB's Python package build and pass its tests free-threaded?
- Does any user need several sqlearn calls in parallel threads, beyond what
  DuckDB's own parallelism gives?
- Would the stable ABI (one wheel for every Python from 3.12) still hold,
  or does the free-threaded build need its own wheel?

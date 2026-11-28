---
type: spec
tags: [benchmarks, profiling, queue, samply, process]
summary: Spec for a just bench-queue command that runs due benchmarks and samply profiles on an idle machine and writes summaries and comparisons.
related: [docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md, validation/_bench.py, docs/specs/native-engine-phase-1.md, docs/architecture/testing.md, docs/architecture/setup.md]
mdindex: [type=d4f02e, summary=6411b4]
---
# The benchmark and profiling queue

Status: built on 2026-11-28 (issue #88); approved by Tomas that day, from the
design talk. Where this spec makes a call of its own, it says "(spec's call)".

## 1. Why

Tomas prepares everything before the rewrite starts, for a clear path
(HANDOFF, 2026-11-28). Each rewritten group is timed, and the numbers so
far came from a loaded machine (ADR 0072's context: load averages up to 145
on 8 cores). Tomas, on who the profiles are for: "that would be for you to
see all profiling and decide what is good and bad… rerun profiling and
etc."

So the reader of every profile is the agent, not Tomas: it reads them,
compares each with the last run, and reports what got faster, slower, and
where the time goes. Tomas gives one go-ahead; the machine must be idle
while anything is measured.

## 2. Goals

- `just benchmarks-due` lists the profiles due beside the benchmarks.
- One command, `just bench-queue`, runs everything due (benchmarks and
  profiles), on Tomas's go-ahead, only while the machine is idle.
- Every profile leaves a text summary an agent can read and compare with
  the previous one, plus a short comparison against that previous run.
- The raw recording stays on disk for drilling into.

## 3. Non-goals and anti-goals

- **Never a gate.** No check runs the queue, a profile never fails a
  check, and a slower number is a finding to report, not an error
  (phase-1 spec §3.7: "Profiling explains a number; it is never a gate").
- **Nothing starts by itself.** No schedule, no hook, no watcher: the
  queue runs only when started by hand after Tomas's go-ahead.
- Not a viewer or a dashboard for Tomas.
- Not `just tune` (flag variants, PGO): that is Phase 1 step 4.
- Not the baseline-and-noise-bound gate of `just bench [group]` (spec
  §3.7); this queue records and compares, it gives no verdict.
- Anti-goal: numbers measured under load presented as clean. Every
  record carries its load, and a run measured on a loaded machine says so.

## 4. Constraints

- ADR 0072 holds except for its "small batches" rule, which this spec
  amends (§7).
- Nothing needs the network (ADR 0006). samply is a development tool,
  never in the wheel; its licence (MIT/Apache-2.0) is fine. Tomas installs
  it (`brew install samply`); `just doctor` names it as optional.
- macOS only, built and checked (spec's call). samply runs on Linux too,
  so nothing here may rule it out, but Linux's owner rules wait for
  Linux's linker map and `addr2line`, which are Phase 1 step 3 (HANDOFF).
- Everything through `just` (ADR 0008), Python through `uv run`.

## 5. Approaches

- **A. Text summaries from samply (chosen by Tomas).** samply records a
  profile as JSON the agent can parse on macOS and Linux; a summary is
  written from it and compared with the previous summary.
- B. `xctrace` (Instruments): installed already, but macOS only, and its
  exported XML is heavy to read.
- C. DuckDB's per-operator profile only: no install, but it cannot see
  time inside sqlearn's own C++ functions, where the rewrite's time goes.

A was chosen; DuckDB's operator profile joins it where a benchmark runs
SQL (§6.3).

## 6. Design

### 6.1 What is due

Every benchmark has a profile. A profile is due when no clean record (below)
has its identity: computed as `validation/_bench.py`'s `_identity` is,
recorded under its own key (`profile-<name>`) beside `bench-<name>`. A
profile measures the `profile` preset's build (release with `-g` and frame
pointers), so a C++ program's profile is of
`engine/build/profile/bench/<name>`, and its identity hashes that binary
(spec's call: each identity hashes the binary it ran). So a profile can be
due while its benchmark is not, as `bench_buffer`'s is today; the two
usually change together, since both follow the same sources.

**Clean and loaded records** (spec's call): a record is marked `"loaded":
true` when the machine was not idle just before the run started (§6.2's
threshold), or when the load after the run, less the run's own share of it, is
at or above that threshold. The 1-minute load average takes in a run of `W`
seconds on `c` cores as only about `c * (1 - e^(-W/60))`, so that is the share
taken off (`c` is user plus system time over the wall time). The record is
kept. A loaded record does not clear "due": the next
queue reruns the item. It is never the "previous run" a comparison (§6.4)
uses; only clean records are. This applies to benchmarks too, so
`just bench <name>` marks a loaded run the same way.

`just benchmarks-due` prints one line per benchmark, as now, and a second
kind of line for each due profile (spec's call: `profile bench_buffer
never run`).

### 6.2 The queue

`just bench-queue`:

1. Builds what the due items need first (`release` for benchmarks,
   `profile` for profiles), before any waiting, so building never happens
   while measuring.
2. Waits for the machine to be idle: the 1-minute load average below a
   quarter of the cores (`os.getloadavg()`, `os.cpu_count()`), checked
   every 30 s, for at most 30 minutes; if it never gets there, it stops
   with nothing run and says the load it saw.
3. Runs each due item in turn; when a benchmark and its profile are both due,
   the benchmark then its profile (spec's call: consecutive, so both see the
   same machine). One that alone is due runs alone. Before each item it checks
   the load again; above the threshold, it stops, keeps what it recorded, and
   lists what is left.
4. Ends with a report: what ran, each one's time and load, and the
   comparisons (§6.4).

`just bench <name>` stays for one item; `just profile <name>` runs one
profile, the same way.

### 6.3 A profile

- samply records the item's process (`samply record --save-only`) into
  `build/profiles/<name>/<timestamp>/`, symbolicated on the spot so the
  summary has function names (the builder finds samply's option for that).
- **Now, only the C++ programs** (spec's call): today the one benchmark is
  `bench_buffer`, and the page scripts are in `old_python/`. Profiling a
  page script waits for the first script to land, like `validate`'s other
  deferred items; then the summary gains a `python` owner for the
  interpreter's frames, and a script that runs SQL may write DuckDB's
  per-operator profile (JSON) into the directory the queue hands it
  (`SQ_PROFILE_DIR`), which the summary includes. Until then a script's
  profile is not listed as due.
- The summary, `summary.json` beside the recording, holds: the wall time;
  the load before and after; the top 30 functions by self time and by
  total time, each with its share of samples and whose code it is
  (sqlearn, DuckDB, the standard library, the benchmark program's own code
  in its image, Python, the system), read from its image and symbol names
  as `just crash-report` does; the share of time per
  owner; and DuckDB's operators, when present.
- The record (`profile-<name>`) keeps the identity, the summary's path and
  its headline numbers; the recordings themselves are never committed
  (`build/` is ignored).

### 6.4 The comparison

After a profile, `compare.md` beside it compares its summary with the
previous one for the same name: wall time, each owner's share, and the
functions whose share moved most (spec's call: more than 2 percentage
points or new in the top 30). It states both runs' loads, so a reader sees
when a difference may be the machine. No verdict, no threshold that fails.
The queue's report lists each comparison's path; the agent reads them and
tells Tomas what is good and bad, and opens issues for what is worth
fixing.

### 6.5 Retention

The last five recordings per name are kept; older ones are deleted, their
summaries too (spec's call). Records stay as the checks' records do.

## 7. ADR 0072 amended

A new ADR amends 0072's "small batches" rule: one go-ahead can cover the
queue, because the queue measures only on an idle machine and stops when
the load rises. The rest of 0072 holds: no check runs a benchmark, an
agent asks first (naming what is due, its last times, and that the queue
waits for idle), and the load is recorded.

## 8. Left to the builder

- samply's exact options for saving without opening a viewer and for
  symbolicating, and how its JSON names images and frames.
- How owners are told apart, reusing `just crash-report`'s rules where
  they fit.
- Tests: the idle wait, the stop on load, what is due, the summary and the
  comparison, all with a fake sampler and a fake load, so no test runs
  samply or times anything.
- The docs: `docs/architecture/testing.md` (or the page that describes
  `benchmarks-due`), `docs/architecture/setup.md` for samply, HANDOFF.

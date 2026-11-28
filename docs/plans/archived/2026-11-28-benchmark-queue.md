---
type: task
tags: [benchmarks, profiling, queue, samply, load, implementation-plan]
summary: "Implementation plan for a benchmark and profiling queue that runs due items only on an idle machine, with samply summaries and comparisons."
related: [docs/specs/archived/benchmark-queue.md, docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md, docs/adr/index.md, docs/architecture/testing.md, docs/architecture/setup.md]
mdindex: [tags=9aaf32, summary=b5d1c9]
---
# The benchmark and profiling queue: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `just bench-queue` runs every due benchmark and profile on one
go-ahead, only while the machine is idle, and each profile leaves a text
summary and a comparison with its last clean run for the agent to read.

**Architecture:** `validation/_bench.py` keeps the benchmarks and gains the
clean/loaded rule and the profiles' due list. Three new modules, each with
one job: `_load.py` (is the machine idle, wait for it), `_profile.py` (record
with samply, summarise, compare, keep five), `_queue.py` (build, wait, run in
turn, stop on load, report). The just recipes are thin.

**Tech Stack:** Python 3.12 under `uv run`, pytest, just, samply (a
development tool Tomas installs, never in the wheel).

**Spec:** `docs/specs/archived/benchmark-queue.md` (approved 2026-11-28).

## Global Constraints

- No check runs a benchmark or a profile; nothing starts by itself (ADR
  0072, spec §3). No test runs samply or times sqlearn: the sampler and the
  load are seams the tests replace.
- Idle: the 1-minute load average below a quarter of the cores
  (`os.getloadavg()[0] < os.cpu_count() / 4`).
- The queue waits at most 30 minutes, checking every 30 s.
- A record with `"loaded": true` never clears "due" and is never the
  previous run of a comparison.
- Summaries: the top 30 functions by self time and by total time; a
  comparison names functions whose share moved more than 2 percentage points
  or that are new in the top 30.
- Keep the last 5 recordings per name under `build/profiles/<name>/`.
- Only C++ programs (`bench_*`) get profiles for now; macOS only, nothing
  ruling Linux out.
- Messages that ask the user to act carry a `Fix:` line (ADR 0046's style).
- Before each commit: `just fmt`, `just check`, `just test`; name every
  failure. Never `--no-verify`. British English in prose, American spelling
  in identifiers. Tests named in `GLOSSARY.md` terms where it has them.
- Docs: `docs/architecture/testing.md` §Benchmarks and
  `docs/architecture/setup.md` describe what changes, in the task that
  changes it.

## Review Focus

1. **samply missing**: `just profile` and `just bench-queue` say so with
   `Fix: brew install samply` and run nothing (Task 5 test).
2. **The profile build older than its sources**: refused with a `Fix:`
   line, as `run` refuses a stale release program (Task 5 test).
3. **No previous clean summary** (first profile, or only loaded ones): the
   comparison says there is nothing to compare with, it does not fail
   (Task 4 test).
4. **The load never drops**: the queue stops after its wait with nothing
   run, saying the load it last saw (Task 6 test).
5. **A sampler that fails or writes no profile**: no record is saved, the
   item stays due, and the queue goes on to report it as failed (Task 6
   test).

---

### Task 1: ADR 0081 amends 0072's small batches

**Files:**
- Create: `docs/adr/0081-one-go-ahead-runs-the-queue-on-an-idle-machine.md`
- Modify: `docs/adr/0072-benchmarks-run-on-tomass-go-ahead.md` (status
  line only: "Amended by ADR 0081"), `docs/adr/index.md`

- [ ] **Step 1:** Write ADR 0081 from spec §7, in the house format (see
  0072): decided by Tomas on 2026-11-28; the "small batches" rule is
  replaced for the queue only, because it measures only on an idle machine
  and stops when the load rises; the rest of 0072 holds. Considered: one
  item per go-ahead (Tomas's time for every item), running regardless of
  load (the numbers of 0072's context).
- [ ] **Step 2:** `just fmt && just links` pass.
- [ ] **Step 3:** Commit: `docs: let one go-ahead run the benchmark queue`.

### Task 2: idle, and loaded records

**Files:**
- Create: `validation/_load.py`, `tests/validation/test__load.py`
- Modify: `validation/_bench.py` (`run`, `due`),
  `tests/validation/test__bench.py`

**Interfaces:**
- Produces: `_load.threshold(cores: int) -> float` (`cores / 4`);
  `_load.now() -> float` (the 1-minute load; the seam tests patch);
  `_load.idle() -> bool`; `_load.wait_for_idle(limit: float = 1800, every:
  float = 30, sleep: Callable[[float], None] = time.sleep) -> bool`
  (True as soon as idle; False after `limit` seconds); `_bench.clean(record)
  -> bool` (`not record.get("loaded", False)`).
- `run` adds `"loaded": not _load.idle()` read after the child ends.

- [ ] **Step 1: Write the failing tests** in `test__load.py`:
  `test_idle_is_a_load_below_a_quarter_of_the_cores` (`threshold(8) == 2.0`;
  `now` patched to 1.9 → `idle()`; to 2.0 → not);
  `test_wait_for_idle_returns_once_the_load_drops` (loads 5, 5, 1 → True
  after two `sleep(30)` calls); `test_wait_for_idle_gives_up_at_its_limit`
  (load always 5, `limit=90` → False, slept 90 s in all). In
  `test__bench.py`: `test_a_run_under_load_is_recorded_as_loaded` (patch
  `_load.now` to 99: record has `"loaded": True`);
  `test_a_loaded_record_leaves_the_benchmark_due` (after that run, `due`
  still lists it, with no last numbers: loaded records give none).
- [ ] **Step 2:** `uv run --locked pytest tests/validation/test__load.py
  tests/validation/test__bench.py -q`: the new tests fail (no module
  `_load`; `"loaded"` missing).
- [ ] **Step 3:** Implement `_load.py`; in `_bench.py`, `due` matches and
  reports only clean records.
- [ ] **Step 4:** The same command passes, the old bench tests too.
- [ ] **Step 5:** Update testing.md §Benchmarks (loaded records); commit
  `feat: record a benchmark run under load as loaded`.

### Task 3: profiles are listed as due

**Files:**
- Modify: `validation/_bench.py`, `tests/validation/test__bench.py`

**Interfaces:**
- Produces: `PROFILE_BUILD = Path("engine/build/profile")`,
  `PROFILE_BINARIES = PROFILE_BUILD / "bench"`; `Due` gains a last field
  `kind: str = "bench"` (`"bench"` or `"profile"`); `_bench.profile_identity(
  root, name) -> str` (as `_identity`, hashing the profile binary);
  `_bench.programs(root) -> list[str]` (the `bench_*` names). `due` lists,
  after the benchmarks, one `Due(kind="profile")` per program whose
  `profile-<name>` records have no clean one with that identity. Its line:
  `profile bench_buffer  never run` or `profile bench_buffer  last 1.2 s`.

- [ ] **Step 1: Write the failing tests**, reusing the file's program
  fixture (`test_a_program_a_group_claims_is_listed_by_its_group`'s set-up):
  `test_a_program_never_profiled_has_its_profile_due`;
  `test_a_profile_is_due_while_its_benchmark_is_not` (a clean
  `bench-<name>` record saved, no `profile-` one: only the profile listed);
  `test_a_profile_is_due_again_when_its_binary_changes`;
  `test_a_script_has_no_profile_due` (the stand-in script lists only its
  benchmark).
- [ ] **Step 2:** Run them: they fail (no `kind`, no profile listed).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Whole `test__bench.py` passes.
- [ ] **Step 5:** Commit `feat: list the profiles due beside the benchmarks`.

### Task 4: a summary and its comparison

**Files:**
- Create: `validation/_profile.py`, `tests/validation/test__profile.py`,
  `tests/validation/data/samply-small.json` (a fixture)

**Interfaces:**
- Produces: `@dataclass(frozen=True) Function(name: str, owner: str,
  self_share: float, total_share: float)`; `@dataclass(frozen=True)
  Summary(seconds: float, load_before: str, load_after: str, owners:
  dict[str, float], by_self: tuple[Function, ...], by_total: tuple[Function,
  ...])` with `to_json() -> dict` and `from_json(dict) -> Summary`;
  `owner(name: str, image: str) -> str`; `summarise(profile: Path, seconds:
  float, load_before: str, load_after: str) -> Summary`;
  `compare(previous: Summary | None, current: Summary) -> str` (Markdown).
- Owners: `sq::` → `sqlearn`, `duckdb::` → `DuckDB`, `std::` or an image
  named `libc++*` → `standard library`, otherwise
  `_crash_report.owner_of_image(image)` (`Python` or `system`).

- [ ] **Step 1: The fixture.** Once Tomas has installed samply, profile a
  throwaway two-second C++ loop compiled in the scratchpad (not a sqlearn
  benchmark: one core, two seconds; say so to Tomas before running it) with
  `samply record --save-only` and its symbolication option; trim it to a few
  functions in `sq::`, `std::` and the system, and commit it. Note in the
  module's docstring which samply version wrote the format.
- [ ] **Step 2: Write the failing tests:**
  `test_a_summary_names_each_function_with_its_owner` (from the fixture:
  shares sum to 1 per ranking within 1e-9, at most 30 entries, the `sq::`
  function's owner `sqlearn`); `test_a_summary_round_trips_through_json`;
  `test_owner_reads_the_namespace_then_the_image` (table of the four cases);
  `test_a_comparison_names_a_function_that_moved_over_two_points` (1.0 pp:
  absent, 2.5 pp: present, with both shares);
  `test_a_comparison_names_a_function_new_in_the_top_thirty`;
  `test_a_comparison_states_both_loads`;
  `test_with_no_previous_summary_the_comparison_says_so`.
- [ ] **Step 3:** Run: they fail (no module).
- [ ] **Step 4:** Implement: a sample's stack is read root to leaf; self
  time counts the leaf, total time every distinct function on the stack
  once.
- [ ] **Step 5:** `test__profile.py` passes.
- [ ] **Step 6:** Commit `feat: summarise a samply profile and compare it`.

### Task 5: one profile, `just profile <name>`

**Files:**
- Modify: `validation/_profile.py`, `tests/validation/test__profile.py`,
  `justfile` (recipe `profile name`, and `doctor` naming samply as
  optional: printed, never failing), `docs/architecture/testing.md`,
  `docs/architecture/setup.md`

**Interfaces:**
- Consumes: `_bench.profile_identity`, `_bench.PROFILE_BINARIES`,
  `_bench._out_of_date` (generalised to take the build directory),
  `_load.now`, `_load.idle`, `summarise`, `compare`.
- Produces: `SAMPLER: Callable[[list[str], Path], list[str]]`, the seam
  that returns samply's argv for a program argv and an output file;
  `run(root: Path, name: str) -> int` (0 recorded, 1 refused or failed, 2
  no such program); recordings in
  `build/profiles/<name>/<YYYYMMDD-HHMMSS>/` with `profile.json(.gz)`,
  `summary.json`, `compare.md`; record `profile-<name>` with `digest`,
  `seconds`, `loaded`, `uptime_before`, `uptime_after`, `summary` (the
  path); `KEEP = 5`.
- Recipe: `just profile name` builds the `profile` preset
  (`just build-engine profile`), then `uv run --locked python -m
  validation._profile run {{name}}`. Header comment says it runs only after
  Tomas's go-ahead (ADR 0072).

- [ ] **Step 1: Write the failing tests**, the sampler replaced by a fake that
      copies the fixture to the output file:
      `test_a_profile_writes_its_summary_comparison_and_record`;
      `test_the_comparison_uses_the_last_clean_profile` (an older loaded one is
      skipped); `test_only_five_recordings_are_kept` (seven runs → five
      directories, the newest);
      `test_without_samply_nothing_runs_and_the_fix_is_named` (`shutil.which`
      patched to None: exit 1, output has `Fix: brew install samply`, no
      directory); `test_a_stale_profile_build_is_refused_with_a_fix`;
      `test_a_failed_sampler_saves_no_record`.
- [ ] **Step 2:** Run: they fail.
- [ ] **Step 3:** Implement `run` and the `cli` (`run <name>`).
- [ ] **Step 4:** `test__profile.py` and `test__bench.py` pass; `just
  --list` shows `profile`.
- [ ] **Step 5:** Docs: testing.md §Benchmarks (profiles, their files,
  owners, retention), setup.md (the recipe table, samply optional in
  `doctor`). Commit `feat: profile one benchmark with samply`.

### Task 6: the queue, `just bench-queue`

**Files:**
- Create: `validation/_queue.py`, `tests/validation/test__queue.py`
- Modify: `justfile` (recipe `bench-queue`), docs as Task 5

**Interfaces:**
- Consumes: `_bench.due`, `_bench.run`, `_profile.run`,
  `_load.wait_for_idle`, `_load.idle`, `_load.now`.
- Produces: `run(root: Path, wait: Callable[[], bool] =
  _load.wait_for_idle) -> int` (0 all ran, 1 stopped or one failed, 3 never
  idle). Order: for each name in `due`, its benchmark then its profile when
  both are due. Before each item `_load.idle()`; when not, stop and list
  what is left. The report prints each item: ran / failed / not run, its
  time, its load, and each comparison's path.
- Recipe: `just bench-queue` builds `release` and `profile`
  (`just build-engine release`, `just build-engine profile`) only when a
  program is due, then `uv run --locked python -m validation._queue`; with
  nothing due it says `nothing is due` and builds nothing. Header comment:
  one go-ahead covers it (ADR 0081).

- [ ] **Step 1: Write the failing tests**, `_bench.run`, `_profile.run` and
  the load replaced by fakes recording calls:
  `test_the_queue_runs_a_benchmark_then_its_profile`;
  `test_an_item_due_alone_runs_alone`;
  `test_the_queue_stops_when_the_load_rises_and_lists_what_is_left`;
  `test_a_machine_never_idle_runs_nothing_and_says_the_load` (exit 3, the
  load in the output); `test_a_failed_item_is_reported_and_the_queue_goes_on`;
  `test_nothing_due_runs_nothing`.
- [ ] **Step 2:** Run: they fail (no module).
- [ ] **Step 3:** Implement `run` and `__main__`.
- [ ] **Step 4:** `uv run --locked pytest tests/validation -q` passes.
- [ ] **Step 5:** Docs (the recipe, the order, the stop rule); commit
  `feat: run the due benchmarks and profiles on an idle machine`.

### Task 7: close

- [ ] **Step 1:** `just done` passes; name every failure.
- [ ] **Step 2:** HANDOFF: the queue item to "Just finished" with its
  commits; "Waiting on the user" asks for the first `just bench-queue`
  (today: `bench_buffer` and its profile, seconds, one core) and samply's
  install if not done. `git mv` this plan to `docs/plans/archived/`; the
  spec to `docs/specs/archived/`, its links fixed.
- [ ] **Step 3:** Commit `docs: close the benchmark queue`; issues per
  github-pm (the queue's issue, if one is opened at the start, closed here).

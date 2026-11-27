---
type: task
tags: [native-engine, benchmarks, profiling, duckdb, inventory]
summary: "Implementation plan for Phase 0b of the native engine: a DuckDB profiling script, its published benchmark page, and the inventory that gives every module its phase in the port."
related: [docs/specs/native-engine.md, docs/plans/2026-11-21-native-engine-phase-0a-decisions.md, docs/benchmarks/gram-batches.md, docs/benchmarks/engine-profile.md, docs/architecture/engine-inventory.md, docs/architecture/index.md, docs/architecture/overview.md, docs/benchmarks/index.md]
mdindex: [type=0ebb42, tags=88654e, related=38bf87]
---
# Native engine, Phase 0b: the inventory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** measure where sqlearn's heavy paths spend their time and memory
today, publish the numbers as a benchmark page, write the inventory that gives
every module of `src/sqlearn` its phase in the port, and close Phase 0.

**Architecture:** one benchmark script under `validation/benchmarks/`, in the
manner of `gram_batches.py`. DuckDB writes the data as Parquet from a fixed
seed; each probe runs in a subprocess of its own; the script prints Markdown
tables. A profiled probe turns on DuckDB's JSON profiling. With no output file
set, DuckDB 2.0 prints one JSON profile per statement to standard output
(checked on 2.0.0), so the parent reads every statement's time and operators
from the probe's stdout, while the probe writes its own result to a file. The
inventory is a page under `docs/architecture/`, with a test that keeps it
complete.

**Tech Stack:** Python 3.12, DuckDB 2.0 (JSON profiling), `cProfile`,
`resource`, `subprocess`; pytest; MyST on the Sphinx site; `just`.

**Spec:** `docs/specs/native-engine.md` (approved 2026-11-21), §5.3, §5.7
and §8. Phase 0's issue is #78. Plan 0a
(`docs/plans/2026-11-21-native-engine-phase-0a-decisions.md`) runs first on
the same branch, `engine-phase-0`; this plan continues in its worktree.

## Global Constraints

- Everything in plan 0a's Global Constraints holds here too: `just` and
  `uv run`, the prose rules, the commit rules with `(#78)`, staging only the
  task's files, the docs tagger's edits left out, no bare `git stash`.
- Before every commit: `just fmt`, `just check`, `just test`, and
  `just build-docs` when a page changes. Name every failure.
- Benchmark rules (HANDOFF):
  - print `uptime` before and after;
  - run one probe per subprocess;
  - write large data as Parquet with `COPY`, into a temporary directory
    removed after;
  - read peak memory twice, with two timing runs, each a subprocess of its
    own;
  - print the machine and DuckDB's settings;
  - label every number on the page as measured, with the load.
- Every probe leaves DuckDB at its defaults (threads, `memory_limit`) and
  prints what they were.
- The probes call sqlearn's public API only. Nothing under `src/` changes in
  this plan.
- The script measures and decides nothing. The inventory's phases start from
  spec §5.3's draft order and change only where a number says so; each
  change names its number.
- TDD for the script's pure parts and for the inventory's completeness: watch
  each test fail for the right reason first.

## Review Focus

1. **DuckDB's profiles mixed with the probe's own output.** The probe writes
   its result to the file it is given, so stdout carries only DuckDB's
   profiles. Task 1 tests a profiled probe end to end.
2. **A probe that fails, runs out of memory, or never ends.** For example,
   `impute.median` at 500 columns sorts 4 GB. It is reported as failed, with
   the last line of its stderr or "timed out", and the run goes on. Task 1
   tests a failed probe.
3. **`ru_maxrss` units:** bytes on macOS, kilobytes on Linux. Use
   `validation.benchmarks.gram_reach._peak`, which converts.
4. **A module missing from the inventory, or a stale row.** A test compares
   the inventory's rows with `src/sqlearn/**/*.py` both ways, and checks
   every row's phase (Task 3).
5. **Python's share measured wrongly.** It comes from the profiled run only: its
   wall time less the sum of DuckDB's statement times. The timing runs carry
   no profiling and no `cProfile`.

---

### Task 1: The profiling script

**Files:**
- Create: `validation/benchmarks/engine_profile.py`
- Test: `tests/validation/benchmarks/test_engine_profile.py`

**Interfaces:**
- Consumes: `validation.benchmarks.gram_batches._write(path, rows,
  columns)`, `validation.benchmarks.category_lookup._machine()`,
  `validation.benchmarks.gram_reach._peak() -> int` (bytes).
- Produces, in `engine_profile.py`:
  - `ROWS = 1_000_000`, `TIMEOUT = 1800` (seconds a probe may take).
  - `CASES: tuple[tuple[str, int], ...]`, the call and the width, in this
    order: `("pca", 50)`, `("pca", 200)`, `("pca", 500)`,
    `("spearman", 50)`, `("spearman", 200)`, and `scale`, `median`,
    `variance`, `profile`, each at 200 and 500.
  - `CALLS: dict[str, Callable[[str], object]]`, each taking the Parquet path:
    - `"pca"`: `sq.Pipeline([sq.decompose.pca()]).learn(path)`;
    - `"spearman"`: `sq.explore.correlations(path,
      method="spearman").fetchall()`;
    - `"scale"`: `sq.Pipeline([sq.scale.standard()]).learn(path)`;
    - `"median"`: `sq.Pipeline([sq.impute.median()]).learn(path)`;
    - `"variance"`: `sq.Pipeline([sq.select.variance()]).learn(path)`;
    - `"profile"`: `sq.explore.profile(path).fetchall()`.
  - `Statement`, a `TypedDict`: `sql: str`, `seconds: float` (the profile's
    `query.total_time`), `cpu_seconds: float` (`query.cpu_time`),
    `peak_buffer_bytes: int` (`system.peak_buffer_memory`), `temp_bytes: int`
    (`system.peak_temp_dir_size`), `operators: list[tuple[str, float]]` (each
    operator `type` with its `timing` summed over the profile's `operator`
    tree, largest first, ties by name).
  - `parse_profiles(text: str) -> list[Statement]`: every JSON object in
    `text` that holds a `"query"` key, in order; any other text or JSON is
    skipped.
  - `probe(call: str, path: str, result: str, profiled: bool) -> None`, which
    runs in the subprocess. It opens a connection and passes it with
    `sq.set_config(connection=con)`; when profiled, it first runs
    `SET enable_profiling = 'json'` and wraps the call in `cProfile`. It
    times the call and writes JSON to `result` with these keys:
    - `s` (wall seconds) and `peak_gb` (`_peak() / 1e9`);
    - `threads` and `memory_limit` (from `current_setting`);
    - when profiled, `python_top`: the five `cProfile` entries with the
      largest `tottime` that are not methods of `duckdb` objects, as
      `[name, seconds]`.
  - `run(call: str, path: Path, profiled: bool) -> dict`: runs
    `sys.executable -m validation.benchmarks.engine_profile probe <call>
    <path> <result file> <0|1>` with `timeout=TIMEOUT`. It reads the result
    file; when profiled, it adds `statements` (`parse_profiles` of stdout),
    `duckdb_s` (their summed `seconds`) and `python_s` (`s - duckdb_s`). A
    probe that exits non-zero gives `{"s": "failed", "error": <last stderr
    line, at most 80 characters>}`; one past `TIMEOUT` gives
    `{"s": "failed", "error": "timed out"}`.
  - `main(argv: list[str]) -> None`: the `probe` subcommand, else the whole
    run:
    1. print the machine and `uptime`;
    2. for each width in 50, 200 and 500, write the data once with `_write`
       and run that width's cases: two timing runs and one profiled run;
    3. print one Markdown table row per case;
    4. write every result as JSON to the path given by `--json PATH`;
    5. print `uptime` again.

    The row's columns: path, columns, seconds (both runs), peak GB (both
    runs), DuckDB s, Python s, the number of statements, the longest
    statement's seconds, and its three largest operators.
  - A module docstring saying what it measures, how to run it, and that on a
    loaded machine the times are estimates, as `gram_batches.py`'s does.

- [ ] **Step 1: Write the failing tests** in `test_engine_profile.py`:
  - `test_profiles_are_read_in_order_with_their_operators`: `text` is
    `"noise\n" + json.dumps(a) + "\nmore\n" + json.dumps(b)`, where `a` is
    `{"query": {"sql": "SELECT 1", "total_time": 0.5, "cpu_time": 0.4},
    "system": {"peak_buffer_memory": 10, "peak_temp_dir_size": 0},
    "operator": [{"type": "RESULT_COLLECTOR", "timing": 0.01, "children":
    [{"type": "HASH_GROUP_BY", "timing": 0.3, "children": [{"type":
    "TABLE_SCAN", "timing": 0.1, "children": []}]}]}]}` and `b` is the same
    with `"SELECT 2"`. Then `parse_profiles(text)` has length 2, its first
    `sql` is `"SELECT 1"`, `seconds` 0.5, `peak_buffer_bytes` 10,
    `operators` `[("HASH_GROUP_BY", 0.3), ("TABLE_SCAN", 0.1),
    ("RESULT_COLLECTOR", 0.01)]`, and its second `sql` is `"SELECT 2"`.
  - `test_json_without_a_query_is_skipped`: `parse_profiles('{"a": 1}')` is
    `[]`.
  - `test_a_profiled_probe_reports_every_statement(tmp_path)`: write
    `tmp_path / "d.parquet"` with `_write(path, 1000, 3)`. Then
    `run("scale", path, profiled=True)` gives `s > 0`, at least one
    statement, `0 <= duckdb_s <= s`, and a `python_top` of at most five
    entries.
  - `test_a_failed_probe_is_reported_not_raised(tmp_path)`:
    `run("scale", tmp_path / "missing.parquet", profiled=False)` gives `s`
    equal to `"failed"` and a non-empty `error`.

  Run `uv run pytest tests/validation/benchmarks/test_engine_profile.py -q`;
  expected FAIL with `ModuleNotFoundError` for
  `validation.benchmarks.engine_profile`.
- [ ] **Step 2: Implement** `engine_profile.py` to the interfaces above.
  - `parse_profiles` walks the text with `json.JSONDecoder.raw_decode` from
    each `{`, keeping the objects that hold `"query"`.
  - Prints carry `# noqa: T201`, as in `gram_batches.py`.
- [ ] **Step 3:** Run the tests; expected PASS. Run `just test`.
- [ ] **Step 4:** `just fmt`, `just check` pass. Commit
  `test: profile where sqlearn's heavy paths spend their time (#78)`.

### Task 2: Run the profiling and publish the page

**Files:**
- Create: `docs/benchmarks/engine-profile.md`
- Modify: `docs/benchmarks/index.md` (toctree: `engine-profile` after
  `explore-larger-than-memory`)

- [ ] **Step 1: Check the machine.** Record `uptime`, and look for other
  heavy work with `pgrep -fl pytest` and `pgrep -fl python`. Never kill a
  stray run; note it. The run needs about 10 GB of free disk at 500 columns.
- [ ] **Step 2: Run it in the background:**
  `uv run python -m validation.benchmarks.engine_profile --json
  <scratch>/engine_profile.json > <scratch>/engine_profile.out 2>&1`.
  `<scratch>` is the session's scratch directory, never the repository. Wait
  on its PID until it exits; never wait on a `grep` of its log (HANDOFF). An
  estimate: 30 to 60 minutes.
- [ ] **Step 3: Write the page** in the house style of
  `docs/benchmarks/gram-batches.md`, with these sections:
  - **What was measured:** the data, the cases, the three runs per case, and
    what each column means.
  - **Reproduce:** the command and its time.
  - **Environment:** the machine, DuckDB's settings, the load before and
    after.
  - **Results:** one table each for the Gram learn, Spearman, and the widest
    steps.
  - **What it shows:** per path, Python's share against DuckDB's, and the
    operators that dominate; failed probes listed as failed.

  Every number is labelled measured, with the load.
- [ ] **Step 4:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: where sqlearn's heavy paths spend their time (#78)`.

### Task 3: The inventory

**Files:**
- Create: `docs/architecture/engine-inventory.md`
- Modify: `docs/architecture/index.md` (toctree: `engine-inventory` after
  `overview`), `docs/architecture/overview.md` (3.10: link the inventory)
- Test: `tests/docs/test_engine_inventory.py`

**Interfaces:**
- Produces: the inventory's table (spec §5.3). Each row starts `| `, then
  a module path in backticks, relative to `src/sqlearn/` (`` `_compose.py` ``,
  `` `explore/profile.py` ``, `` `_saving/__init__.py` ``), then a phase
  column that is exactly one of `2`, `3`, `4`. The further columns, in this
  order: the C++ that replaces it (a kernel, a numeric function, or a part
  of the C++ library); what stays in the bindings; what it depends on among
  the other modules; the evidence, linked to the profiling page's rows where
  there is a number.

- [ ] **Step 1: Write the failing test**
  `test_the_inventory_gives_every_module_its_phase`. The set of module paths
  in the table equals the set of `src/sqlearn/**/*.py` paths relative to
  `src/sqlearn/`, compared both ways; no path is listed twice; every row's
  phase is one of `2`, `3`, `4`. Run it; expected FAIL with
  `FileNotFoundError`.
- [ ] **Step 2: Write the page.**
  - Its purpose: the port's map (ADR 0067).
  - The table, one row per module, with the columns above.
  - **The groups of Phase 4:** each named, with its modules and its place in
    the order, the order argued from the dependencies (a module is ported
    after what it calls, or the bindings carry the seam) and from the
    profiling page.
  - **The heavy paths, measured:** the numbers from Task 2's page, linked.
  - **What the numbers change:** compared with spec §5.3's draft order,
    kept, or changed with the number that changes it.
- [ ] **Step 3: Link it.** In `docs/architecture/index.md`'s toctree, put
  `engine-inventory` after `overview`. In the overview's 3.10, turn "the
  inventory of every module" into a link to
  [engine-inventory](../architecture/engine-inventory.md).
- [ ] **Step 4:** Run the test; expected PASS. `just fmt`, `just check`,
  `just test`, `just build-docs` pass. Commit
  `docs: the native engine's inventory of sqlearn's modules (#78)`.

### Task 4: Close Phase 0

**Files:**
- Modify: `CLAUDE.md` (the opening paragraph's state), `HANDOFF.md`,
  `validation/results/tests.json` (rewritten by `just verify`), and the
  leftovers of plan 0a named in Step 3

- [ ] **Step 1: `CLAUDE.md`.** In the opening paragraph, after the sentence
  ending "ADR 0059, issue #74.", add: "The native engine (part 3.10:
  sqlearn as a C++ library embedding DuckDB, Python its bindings): spec
  `docs/specs/native-engine.md`, ADRs 0060–0068, the port's inventory
  `docs/architecture/engine-inventory.md`, milestone "Native engine" (#78 to
  #84). Phase 0 is done; the port comes before any new area."
- [ ] **Step 2: `HANDOFF.md`.**
  - "In progress": None.
  - "Just finished": Phase 0 of the native engine (#78), with its commits:
    ADRs 0060 to 0068, the profiling page, the inventory, the revised spec,
    the phase issues #79 to #84. The backup branch and tag are already
    pushed (listed there).
  - "Next up", first: the one-line `profile` fix, #75 and #76, then Phase
    1's spec (#79), brainstormed with Tomas. Its topics, from spec §4: the
    checks redesigned for two languages and for speed, the review of the
    libraries sqlearn and its tooling use, and how the C++ is documented.
  - "Waiting on the user": keeps the benchmarks item; drops the backup push
    (done, pushed with `main`).
  - The DuckDB-profiling trap (under "Dead ends and traps") says profiles
    go to stdout; Task 1 found DuckDB 2.0 prints them to stderr. Correct
    the line.
  - Update the "Updated:" line.
- [ ] **Step 3: The three cosmetic leftovers of plan 0a.**
  - ADR 0062's Context names Tomas twice in one line ("Three points from
    Tomas (Tomas, 2026-11-21)."): name him once.
  - Spec §3.3's "Why Apple silicon leads" bullet repeats the first bullet
    above it: cut the repetition, keeping what only it says (the priority,
    exactness, no `-ffast-math`).
  - The overview's §2 has one line over 80 columns (about line 79: "passes
    through Python in no other learn."): rewrap it. If `just fmt` has
    already wrapped it, drop this item.
- [ ] **Step 4: The docs tagger's frontmatter** for the files this branch
  created: ADRs 0060 to 0068, `docs/benchmarks/engine-profile.md`, plans 0a,
  0b and 0c, and `docs/architecture/engine-inventory.md`. Several (0060,
  0061, 0067) carry a stale `summary` or `tags` after the spec's revision:
  commit the tagger's refresh for these files. Files that existed on `main`
  before the branch keep the rule: their tagger edits stay out. Read each
  new file's frontmatter first (a `related:` path that does not exist is a
  known fault).
- [ ] **Step 5: `just verify`.** The full validation took about 47 minutes
  under load. Name every failure, fix, rerun. Discard ULP-only changes to
  `*.results.json`; keep `tests.json`, since tests were added (ADR 0043,
  HANDOFF).
- [ ] **Step 6:** Commit `docs: close Phase 0 of the native engine (#78)`,
  with `tests.json`.
- [ ] **Step 7: Review the whole branch** with
  subagent-driven-development's final reviewer, against the spec and the
  plans. Fix what it finds, with `just verify` again after any fix.
- [ ] **Step 8: Hand the branch to Tomas** with
  superpowers:finishing-a-development-branch, and merge on his approval.
  - Before merging on `main`, deal with the docs tagger's uncommitted
    frontmatter edits in `main`'s working tree, which block a merge: save
    them as a patch, `git checkout` those files, merge, then `git apply` the
    patch. A file the branch changed may no longer take its hunk; drop that
    hunk.
  - Merge as `Merge branch 'engine-phase-0': the native engine's Phase 0
    (#78)`.
  - `gh issue close 78 --comment "Done in <merge sha>."`, then check that the
    board shows it as Done.
  - Push nothing until Tomas says.

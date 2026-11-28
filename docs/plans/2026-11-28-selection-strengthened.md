---
type: task
tags: [testing, selection, cmake, layering, just]
summary: "Implementation plan to make sqlearn's checks run exactly what a change affects, with a layering check, just affected report, and sweep verification."
related: [docs/adr/0080-the-engine-stays-on-cmake-for-now.md, HANDOFF.md, docs/questions/archived/bazel-prototype.md, docs/questions/test-selection.md, docs/architecture/testing.md, docs/adr/0001-uv-for-python-packaging.md, docs/adr/0008-just-task-runner.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
mdindex: [type=0ebb42, tags=7e9068, summary=a4767e]
---
# The selection, strengthened: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** sqlearn's checks run exactly what a change affects, say why, and
are proved right by a full run now and then. This is step 1 of the
preparation in `HANDOFF.md`.

**Architecture:** Four independent pieces on today's tools (CMake, `just`,
`validation/`):
- The groups' test programs link static archives, so a program holds only
  the objects it uses.
- A layering check compares each group's `DEPENDS` with the headers it
  includes.
- `just affected` prints, for every check, whether it would run and why,
  running nothing.
- `just sweep` runs every check in full and compares the result with what
  the selection chose. `just done` warns when the last sweep is too old.

**Tech Stack:** CMake 4 and Ninja, Python 3.12 under uv, pytest,
`validation/_checks.py`, `validation/_ctest.py`,
`validation/_pytest_sets.py`, `validation/_groups.py`.

**Spec:**
- [ADR 0080](../adr/0080-the-engine-stays-on-cmake-for-now.md): the decision
  and the four pieces.
- Tomas's aim of 2026-11-28, quoted in ADR 0080: never run a check on what
  already passed, never when nothing changed, and always when something it
  uses changed. Accuracy is the criterion, not speed.
- The evidence: the
  [Bazel report](../questions/archived/bazel-prototype.md) items 2 and 6,
  and the research in [test selection](../questions/test-selection.md),
  A §9 and B §7.
- How selection works today: [testing](../architecture/testing.md).

## Global Constraints

- Every task runs through `just`; Python through `uv run --locked`, never pip
  or a bare `python` (ADR 0001, 0008).
- Behaviour inside the checks is tested in Python under `tests/checks/` and
  `tests/validation/`. Name tests in `GLOSSARY.md` terms.
- A refusal or warning carries a `Fix:` line (ADR 0046). A warning never
  changes what runs.
- No check runs a benchmark (ADR 0072): `just sweep` runs the checks of
  `just done` in full, never `bench`, `fuzz`, `mutate-engine` or the other
  parts of the release tier.
- C++ flags unchanged: C++23, warnings as errors, no `-ffast-math`, FMA
  contraction off (ADR 0063, 0071).
- Before each commit `just check` and `just test` pass; at the end
  `just done`. Commit messages are Conventional Commits, with no scope except
  `hooks`, `site` or `deps`, lines at most 72 characters, and no attribution.
- British English in prose, American spelling in identifiers (ADR 0010).

## Review Focus

1. **The wheel losing a group.** The module must still get every group's
   objects once the test programs link archives. Task 1's Step 4 pins it.
2. **Includes written in other forms.** The layering check must find
   `#include <core/x.hpp>` as well as `#include "core/x.hpp"`, and an
   include inside a comment counts (a stale dependency, never a missed one).
   Task 2's tests pin both.
3. **A fresh clone, or a tree with no records.** `just affected` reports
   "never passed here" for each check and does not crash. Task 3 pins it.
4. **A check that fails for a reason other than a missed input** (a flaky
   test, a tool missing) during `just sweep`. It is reported as a failure,
   not as a missed rerun, unless the selection said "unchanged" for it.
   Task 4 pins it.
5. **`just done` with an old sweep.** It warns once, with a `Fix:` line, and
   still runs only what the selection chose. Task 4 pins it.

---

### Task 1: The test programs link static archives

**Files:**
- Modify: `engine/cmake/groups.cmake` (`sq_add_group`)
- Modify: `tests/validation/conftest.py` (`engine_scratch`), only if its
  stand-in groups need a `core` object `raw` does not use
- Test: `tests/checks/test_engine_groups.py`
- Docs: `docs/architecture/testing.md` (the selecting-by-group section)

**Interfaces:**
- Produces: for each group, `sq_<name>` keeps its objects for the module
  (`sq_add_to_module`), and its test program `test_<name>` links the group
  and its `DEPENDS` as static archives.

- [ ] **Step 1: Write the failing test**

  `test_a_change_to_a_core_object_raw_does_not_use_leaves_raw_alone`, in
  `tests/checks/test_engine_groups.py`, on `engine_scratch`:
  - after a passed `_ctest.run("dev", root)`, edit the body of a `core`
    function that no `raw` source calls;
  - `_ctest.run` again returns 0;
  - the output holds `raw: unchanged since a passed run`, and `core` ran.
- [ ] **Step 2:** `uv run --locked pytest
      tests/checks/test_engine_groups.py -q`. Expect the new test to fail
      with `raw` rerun, because the object library links every `core` object
      into `test_raw`.
- [ ] **Step 3:** In `sq_add_group`, link each test program to static
      archives of its group and its `DEPENDS` (the objects of `sq_<name>`,
      archived). Keep `sq_<name>`'s usage requirements reaching the program
      (`sq_crash` carries `cpptrace::cpptrace` and `SQ_CRASH_TEST_HOOKS`).
      Keep `sq_stable_link`.
- [ ] **Step 4:** `uv sync --locked`, then `just test`. Expect every C++ and
      Python test to pass, and `tests/engine` to import the rebuilt module,
      which proves the module still holds every group.
- [ ] **Step 5:** `just coverage-engine`. Expect it to pass. Its
      `unmeasured` check fails if any source is now linked into no test
      program. Name every failure.
- [ ] **Step 6:** In `testing.md`, say that test programs link archives, so a
      program holds only the objects it uses, and an edit reruns only the
      programs whose bytes change.
- [ ] **Step 7:** `just check`, `just test`: PASS. Commit:
      `build: link the groups' test programs from static archives`.

### Task 2: The layering check

**Files:**
- Create: `validation/_layering.py`
- Test: `tests/validation/test__layering.py`
- Modify: `validation/_checks.py` (the `tidy` task gains a step)
- Docs: `docs/architecture/testing.md`; `engine/cmake/groups.cmake`'s
  comment on `DEPENDS`

**Interfaces:**
- Consumes: `validation._groups.load(build) -> (dict[str, Group], shared)`
  and `validation._groups.closure(groups, names) -> set[str]`.
- Produces:
  - `included(path: Path, groups: Iterable[str]) -> set[str]`: the groups
    whose headers `path` includes;
  - `problems(root: Path, groups: dict[str, Group]) -> list[str]`, each one
    message with a `Fix:` line;
  - `cli(argv: Sequence[str]) -> int`, run as
    `uv run --locked python -m validation._layering`.

The rules, from the manifest alone (no new list of allowed layers):
1. A group's files (`engine/src/<name>/`) and its tests
   (`engine/tests/<name>/`) include only their own group and the groups in
   its `DEPENDS`.
2. `DEPENDS` names every group in the closure of the groups it names, as
   `sq_add_group`'s comment already requires ("DEPENDS is not transitive").
3. Every `DEPENDS` entry is in the closure of the groups the group's files
   include. Otherwise it is stale, and makes a change rerun what it cannot
   affect.
4. `DEPENDS` has no cycle.
5. No group includes the shared directories (`engine/src/bindings`).

- [ ] **Step 1: Write the failing tests**, in
      `tests/validation/test__layering.py`, on files written to `tmp_path`:
  - `test_an_include_of_a_group_not_depended_on_is_refused`:
    `raw/a.cpp` includes `"crash/h.hpp"`, raw depends on `core` only. One
    problem names `raw`, `crash` and the include's line, with
    `Fix: add crash to DEPENDS`.
  - `test_an_angle_include_counts`: `#include <core/x.hpp>` gives `{"core"}`.
  - `test_an_include_in_a_comment_counts`: `// #include "core/x.hpp"` gives
    `{"core"}`.
  - `test_a_dependency_of_a_dependency_must_be_named`: `crash` depends on
    `raw`, `raw` on `core`, `crash` does not name `core`. One problem,
    `Fix: add core to DEPENDS of crash`.
  - `test_a_dependency_nothing_includes_is_stale`: `raw` depends on `core`
    and includes nothing of it. One problem saying `stale`.
  - `test_a_cycle_is_refused`.
  - `test_a_group_including_the_bindings_is_refused`.
  - `test_the_real_engine_has_no_problems`:
    `problems(REPO, load(<llvm-dev build>)[0]) == []`, skipped with a reason
    when no configured build exists.
- [ ] **Step 2:** `uv run --locked pytest tests/validation/test__layering.py
      -q`. Expect every test to fail on the missing module.
- [ ] **Step 3:** Write `included`, `problems` and `cli` in
      `validation/_layering.py`. An include names a group when its path's
      first part is a group's name. The manifest is
      `engine/build/llvm-dev/sq_groups.json`, which `just tidy-engine`
      configures first.
- [ ] **Step 4:** Run the tests: PASS. Then run it on the real engine. If it
      names a real problem (the Bazel report's `layering_check` found
      `test_raw` reaching `core/error.hpp` through `raw`, which rule 1
      allows), fix the declaration, not the rule.
- [ ] **Step 5:** Add `Step(("uv", "run", "--locked", "python", "-m",
      "validation._layering"))` to the `tidy` task after `tidy-engine`.
      Describe the rules in `testing.md` and in `sq_add_group`'s comment.
- [ ] **Step 6:** `just check`, `just test`, `just full tidy`: PASS. Commit:
      `test: check that each group's DEPENDS matches what it includes`.

### Task 3: `just affected`

**Files:**
- Create: `validation/_affected.py`
- Test: `tests/validation/test__affected.py`
- Modify: `validation/_checks.py` (`run` keeps a whole task's `files` too),
  `validation/_ctest.py`, `validation/_pytest_sets.py`, `justfile`
- Docs: `docs/architecture/testing.md`

**Interfaces:**
- Produces:
  - `validation._checks.why(task: Task, root: Path) -> list[str]`: empty
    when the task would not run. Otherwise its reasons:
    `"never passed here"`, `"its settings, tools or the C++ module changed"`,
    or one `"<path>: added|changed|removed"` per file against the newest
    record under today's configuration.
  - `validation._ctest.due(preset: str, root: Path) -> dict[str, list[str]]`:
    builds the preset and runs no test; each label with its reasons, empty
    when unchanged.
  - `validation._pytest_sets.due(root: Path) -> dict[str, list[str]]`: each
    set with its reasons, empty when unchanged.
  - `validation._affected.report(root: Path) -> list[Verdict]`, where
    `Verdict` is a frozen dataclass: `check: str`, `runs: bool`,
    `reasons: tuple[str, ...]`.
  - `just affected`, which prints one line per check, then its reasons
    indented, and exits 0.

- [ ] **Step 1: Write the failing tests** in
      `tests/validation/test__affected.py`:
  - `test_an_unchanged_tree_runs_nothing`: after a passed task on a scratch
    repository, `why` is `[]`.
  - `test_an_edited_file_is_named`: after editing `a.py`, `why` gives
    `["a.py: changed"]`.
  - `test_a_tree_with_no_records_says_never_passed_here`.
  - `test_a_settings_change_is_reported_as_such`.
  - `test_the_report_runs_nothing`: `report` leaves the records unchanged
    and starts no step.
  - In `tests/checks/test_engine_groups.py`:
    `test_due_names_the_label_a_change_reruns`, on `engine_scratch`. After
    a passed run and an edit of `raw`, `_ctest.due` gives a reason for
    `raw` and none for `core`, and runs no test.
- [ ] **Step 2:** Run them. Expect each to fail on the missing function.
- [ ] **Step 3:** In `_checks.run`, save `files` for a whole task as for a
      per-file one. A record read without them stays valid: `why` then says
      `"its inputs changed"` without naming files. Write `why`,
      `_ctest.due`, `_pytest_sets.due` and `_affected.report`. `due` shares
      `run`'s identity code, not a copy of it.
- [ ] **Step 4:** Add the `affected` recipe to `justfile` under `[check]`:
      "Print, for each check, whether `just done` would run it and why; runs
      no check".
- [ ] **Step 5:** Run the tests: PASS. Then on this tree, after `just done`:
      `just affected` says no check would run. After editing a comment in
      `engine/src/core/parse_version.cpp`, it names that file.
- [ ] **Step 6:** Document `just affected` in `testing.md`. `just check`,
      `just test`: PASS. Commit:
      `feat: say what a change reruns and why, with just affected`.

### Task 4: `just sweep`, and its cadence

**Files:**
- Create: `validation/_sweep.py`
- Test: `tests/validation/test__sweep.py`
- Modify: `justfile` (`sweep`; `done` warns when the sweep is old)
- Docs: `docs/architecture/testing.md`; `HANDOFF.md`

**Interfaces:**
- Consumes: `validation._affected.report(root) -> list[Verdict]`.
- Produces:
  - `validation._sweep.run(root: Path) -> int`. It takes `report` first,
    then runs every check of `just done` in full (`just full <task>`),
    every one even when another fails.
    - It exits 1 when a check the report called unchanged fails: a missed
      rerun. The message names the check and says
      `Fix: run just affected, find the input the check reads but does not
      declare, and add it`.
    - It exits with the failing code, and no missed-rerun message, when
      only checks the report said would run fail.
    - After a pass it saves `{"tree": <tree>, "date": <ISO date>}` as
      `sweep.json` in `record_dir(root)`.
  - `validation._sweep.stale(root: Path, today: date) -> str | None`: the
    warning when the last sweep is older than `CADENCE_DAYS` or missing,
    else `None`.
  - `CADENCE_DAYS: int = 7`. Set by Tomas on 2026-11-28 (the research gives
    no number, A §9). The value stays a constant here.

- [ ] **Step 1: Write the failing tests** in `tests/validation/test__sweep.py`,
      with `just full` and `report` replaced by stand-ins:
  - `test_a_check_called_unchanged_that_fails_is_a_missed_rerun`: exit 1,
    and the message names the check and holds `Fix:`.
  - `test_a_failure_of_a_check_that_would_run_is_no_missed_rerun`: the
    failing code, and no "missed rerun" in the output.
  - `test_every_check_runs_even_after_a_failure`.
  - `test_a_passed_sweep_is_remembered_with_its_date`.
  - `test_an_old_sweep_warns_and_a_recent_one_does_not`: `stale` at
    `CADENCE_DAYS + 1` days gives a message holding `Fix: run just sweep`;
    at `CADENCE_DAYS - 1` it gives `None`; with no sweep it gives a message.
- [ ] **Step 2:** Run them. Expect each to fail on the missing module.
- [ ] **Step 3:** Write `validation/_sweep.py`. Add the `sweep` recipe
      ("Run every check of just done in full and compare with what the
      selection chose; minutes to an hour, no benchmark"). Have `done` print
      `stale`'s warning first when it is not `None`, then run as before.
- [ ] **Step 4:** Run the tests: PASS. Then `just sweep` on this tree,
      in the background, waiting for its notification. Expect exit 0, no
      missed rerun, and `sweep.json` written.
- [ ] **Step 5:** In `testing.md`, describe the sweep, its cadence and the
      warning. In `HANDOFF.md`, move step 1 of the preparation to
      "Just finished" with each task's commit.
- [ ] **Step 6:** `just fmt`, `just check`, `just test`, `just done`: PASS.
      Commit: `feat: compare a full run with the selection, with just
      sweep`. Then the tagger's frontmatter on its own, if any.

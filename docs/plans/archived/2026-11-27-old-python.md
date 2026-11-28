---
type: spec
tags: [python-migration, cpp-rewrite, repo-layout, old-python, sqlearn]
summary: "Implementation plan to move the frozen Python sqlearn library into old_python/ and keep only the C++ engine, bindings and tooling active."
related: [docs/questions/test-selection.md, engine/src/bindings/module.cpp, tests/public_api.txt, tests/engine/test_package.py, HANDOFF.md, CLAUDE.md]
mdindex: [type=d4f02e, tags=a39fc4, summary=28888d, related=6e2e5f]
---
# The old Python moves to `old_python/`: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every piece of the frozen Python library (its code, tests,
validation runners, development data, examples and API docs) moves into
`old_python/` at the root, where nothing runs, imports or checks it; what
stays active is the C++ engine, its thin bindings and the tooling.

**Architecture:** One `git mv` per tree into `old_python/` keeping each tree's
path below it (`src/sqlearn/...` becomes `old_python/src/sqlearn/...`), so a
piece can be read beside the C++ that replaces it and deleted on its own.
`src/sqlearn/` keeps only what the bindings need. Every check, recipe and
config that named a moved path is repointed or loses that path, and
`old_python/` is excluded from every tool.

**Tech Stack:** git, `just`, uv, pytest, ruff, ty, mypy, rumdl, typos,
Sphinx.

**Spec:** Tomas's decision of 2026-11-27: sqlearn is rebuilt from scratch in
C++ (Python only where C++ cannot do it); the old Python is kept as
reference only, never run. Research behind the selection side:
`docs/questions/test-selection.md`.

## Global Constraints

- Python packaging uses uv: `uv run`, `uv sync`; never pip or a bare
  `python`.
- Every task runs through `just`. Before each commit `just check` and
  `just test` pass; before the work is called done, `just done` passes.
- Never `--no-verify`. `just fmt` before each commit.
- British English in prose, American spelling in identifiers.
- Commit messages: Conventional Commits, scopes only `hooks`, `site`, `deps`;
  lines at most 72 characters; no AI or tool attribution, no trailers.
- `git mv`, never copy-and-delete, so history follows each file.
- Nothing under `old_python/` is edited, beyond its one `README.md`.
- The C++ under `engine/` and its tests are not touched.

## Review Focus

1. **A leftover reference to a moved path.** Any file outside `old_python/`
   naming `tests/src`, `devdata`, `examples/`, `validation/sqlearn`,
   `validation/pipelines`, `validation/devdata`, `validation/benchmarks`,
   `docs/guide`, `docs/learn` or `docs/reference` is a bug, except in
   history docs (ADRs, specs, plans, `HANDOFF.md`'s history). Task 6's grep
   pins it.
2. **The bindings losing their exception class.**
   `engine/src/bindings/module.cpp:22` imports
   `sqlearn.errors.InternalError`; an import of `sqlearn` must still give
   it, as a subclass of `sqlearn.errors.SqlearnError`. Task 2's test pins it.
3. **A check that silently runs nothing and reports green for the wrong
   reason**, such as `just validate` with no runners, or a Python set that
   collects nothing. Task 4 pins that an empty runner list passes with a line
   saying so, and that the tooling and engine sets still collect.
4. **A tool reading `old_python/`**: ruff, ty, mypy, rumdl, typos, pytest or
   Sphinx linting, collecting or building it. Task 3's checks pin each.
5. **The docs site still pointing at moved pages** (`docs/index.md`'s
   toctree, `related:` frontmatter). Task 5's `just build-docs` with
   warnings as errors pins it.

---

### Task 1: Commit the research page, then move the trees

**Files:**

- Add: `docs/questions/test-selection.md` (already written, untracked)
- Move (`git mv`), each to `old_python/<same path>`:
  - `src/sqlearn/*` except `__init__.py`, `_native.py`, `_native.pyi`,
    `py.typed`
  - `tests/src/`
  - `validation/sqlearn/`, `validation/pipelines/`, `validation/devdata/`,
    `validation/benchmarks/`, `validation/_cases.py`
  - `tests/validation/test__cases.py`, `tests/validation/benchmarks/`
  - `devdata/`, `tests/devdata/`
  - `examples/`
  - `docs/guide/`, `docs/learn/`, `docs/reference/`
- Create: `old_python/README.md`

**Interfaces:**

- Produces: the layout every later task repoints to.

- [ ] **Step 1:** Commit `docs/questions/test-selection.md` alone:
      `docs: research how to choose the tests a change runs`.
- [ ] **Step 2:** `git mv` each tree above. Before moving
      `validation/_cases.py`, confirm with `git grep -n "_cases"` that only
      runners, `tests/validation/test__cases.py` and docs import it; if a
      tooling module does, keep `_cases.py` and note it.
- [ ] **Step 3:** Write `old_python/README.md`, one paragraph: the frozen
      Python library and everything that tested or documented it, kept as
      reference while sqlearn is rebuilt in C++; never run, imported or
      checked; each piece deleted when what replaces it lands.
- [ ] **Step 4:** Do not commit yet: the tree does not pass the checks until
      Task 5. Run `git status --short | wc -l` and expect the moved count
      (about 260 files).

### Task 2: A minimal `sqlearn` package

**Files:**

- Modify: `src/sqlearn/__init__.py`
- Create: `src/sqlearn/errors.py`
- Test: `tests/engine/test_package.py`

**Interfaces:**

- Produces: `sqlearn.__version__: str`, `sqlearn.version() -> str`,
  `sqlearn.errors.SqlearnError(Exception)`,
  `sqlearn.errors.InternalError(SqlearnError)`; `sqlearn.__all__ ==
  ["__version__", "errors", "version"]`.

- [ ] **Step 1: Write the failing test** in `tests/engine/test_package.py`:

```python
import sqlearn as sq


def test_the_package_gives_only_the_bindings_names():
    """sqlearn is the bindings alone until the C++ brings the rest."""
    assert sq.__all__ == ["__version__", "errors", "version"]


def test_an_internal_error_is_a_sqlearn_error():
    """The class the bindings raise for a broken precondition."""
    assert issubclass(sq.errors.InternalError, sq.errors.SqlearnError)
```

- [ ] **Step 2:** `uv run --locked pytest tests/engine/test_package.py -q`:
      expect it to fail on import (the package imports moved modules).
- [ ] **Step 3:** Rewrite `src/sqlearn/__init__.py`: keep its docstring, the
      `_native` load and `MISSING` refusal, `__version__` and `version()`
      as they are; drop every import of a moved module; import `errors`.
      Write `src/sqlearn/errors.py` with `SqlearnError` and `InternalError`,
      their docstrings and doctests as in the old `_errors.py`, nothing
      else.
- [ ] **Step 4:** Run the test again and `uv run --locked pytest tests/engine
      -q`: expect PASS, `test_bindings.py`'s `sq.errors.InternalError` case
      included.
- [ ] **Step 5:** `just api-snapshot` (the recipe that writes
      `tests/public_api.txt`), then check the file lists only
      `__version__`, `errors`, `errors.InternalError`,
      `errors.SqlearnError` and `version`.

### Task 3: Tools leave `old_python/` alone

**Files:**

- Modify: `pyproject.toml`

- [ ] **Step 1:** In `pyproject.toml`: add `old_python` to
      `[tool.ruff] extend-exclude`, `old_python/**` to `[tool.rumdl]
      exclude`, `old_python/` to `[tool.typos.files] extend-exclude`; set
      `[tool.ty.src] include = ["src", "tests", "docs"]`; set
      `[tool.pytest.ini_options] pythonpath = ["."]` (drop
      `tests/src/sqlearn`, the moved helper's home) and keep
      `testpaths = ["tests"]`; drop the `examples/**` and
      `src/sqlearn/__init__.py` E402 per-file ignores only if ruff then
      reports them unused (`RUF100`).
- [ ] **Step 2:** `just check`: expect PASS for lint, types, Markdown and
      spelling, with no finding under `old_python/`. `check-mirror` fails
      here; Task 4 removes it.

### Task 4: The checks lose what moved

**Files:**

- Modify: `justfile` (`check-mirror`, `check`, `done`, `build-docs`,
  `benchmarks-due`), `validation/_checks.py` (`TOOLING_INPUTS`, the `docs`
  task's inputs), `validation/_pytest_sets.py` (`LIBRARY`, the tooling list),
  `validation/__main__.py` (`RUNNERS`), `validation/_bench.py` (page scripts)
- Modify tests: `tests/checks/test_tasks.py`,
  `tests/checks/test_passed_tree.py`, `tests/validation/test___main__.py`,
  `tests/validation/test__pytest_sets.py`, `tests/validation/test__audit.py`,
  `tests/validation/test__record.py`, `tests/validation/test__tests_report.py`
  (each only where it names a moved path)

**Interfaces:**

- Produces: `validation.__main__.RUNNERS == ()`; `just validate` exits 0
  with no runner run.

- [ ] **Step 1: Write the failing test** in
      `tests/validation/test___main__.py`:

```python
def test_no_runners_passes_and_says_so(capsys, tmp_path):
    """With every runner in old_python/, a validation run passes, naming why."""
    assert main((), tmp_path) == 0
    assert "no validation runners" in capsys.readouterr().out
```

- [ ] **Step 2:** Run it: expect FAIL (no such line today).
- [ ] **Step 3:** In `validation/__main__.py` set `RUNNERS = ()`, and in
      `main` print `no validation runners: nothing to validate` and return
      0 when given none.
- [ ] **Step 4:** Delete the `check-mirror` recipe and its name from `check`
      and from both lists in `done`: its rule mirrored the Python library.
      Keep `check-no-devdata` (it still guards `src/sqlearn`).
- [ ] **Step 5:** `validation/_checks.py`: drop `tests/devdata` and
      `devdata` from `TOOLING_INPUTS`; the `docs` task's inputs become
      `("docs", "src")`. `validation/_pytest_sets.py`: drop `devdata` from
      the tooling list; with `tests/src` gone the `group:` and `unclaimed`
      sets collect nothing, which `_pytest_sets` already accepts while the
      tooling set collects. `validation/_bench.py`: page scripts come from
      `validation/benchmarks/`, now empty; keep the code, expect
      `just benchmarks-due` to list only the `engine/bench` programs.
      `justfile` `build-docs`: drop `docs/examples` and
      `docs/reference/generated` from its clean line.
- [ ] **Step 6:** `uv run --locked pytest tests -q`: fix each failing test
      whose expectation names a moved path, changing the expectation only,
      never the code under test, unless the code itself names the path.
      Name every failure before fixing it.
- [ ] **Step 7:** `just check` and `just test`: expect PASS.

### Task 5: The docs site without the library

**Files:**

- Modify: `docs/index.md` (toctree), `docs/conf.py`, `tests/docs/test_conf.py`
  (only where it names the gallery or the reference)

- [ ] **Step 1:** `docs/index.md`: drop `guide/index`, `reference/index`,
      `examples/index` and `learn/index` from the toctree and from
      `related:`; rewrite its first paragraph to say sqlearn is being rebuilt
      in C++ and its API returns as the port brings it.
- [ ] **Step 2:** `docs/conf.py`: drop `sphinx_gallery.gen_gallery` from the
      extensions and `sphinx_gallery_conf`; keep autodoc and the doctest
      extension (they still read `sqlearn`'s docstrings).
- [ ] **Step 3:** `rm -rf docs/reference/generated docs/_build && just
      build-docs`: expect `build succeeded` with no warning, and doctests
      `0 failures`. Fix any page that links a moved one.
- [ ] **Step 4:** `just fmt`, `just check`, `just test`: expect PASS. Commit
      Tasks 1 to 5 together (the tree passes only as a whole):
      `refactor: move the frozen Python library to old_python/`, its body
      listing what moved and that nothing under `old_python/` runs.

### Task 6: No reference left, and the docs say so

**Files:**

- Modify: `CLAUDE.md`, `HANDOFF.md`, `docs/architecture/layout.md`,
  `docs/architecture/testing.md`, `docs/architecture/validation.md`,
  `docs/architecture/overview.md` (only where it names moved paths)
- Create: `docs/adr/00NN-the-old-python-moves-to-old-python.md` (next free
  number)

- [ ] **Step 1:** Run, from the root:

```bash
git grep -n -E "tests/src|devdata/|examples/|validation/(sqlearn|pipelines|devdata|benchmarks)|docs/(guide|learn|reference)/" -- ':!old_python' ':!docs/adr' ':!docs/specs' ':!docs/plans' ':!docs/questions'
```

      Expect only lines that describe history; repoint or delete each other.
- [ ] **Step 2:** The ADR: context (the port rewrites every group from
      scratch; the frozen Python's tests and 24 runners reran on every real
      C++ change, about 47 minutes, proving nothing new), decision (this
      plan's Goal; `old_python/` is reference only; each piece is deleted
      when its replacement lands; new validation is written per group for
      the C++), what it supersedes (ADR 0070's deletion of a group's Python
      and its tests in the group's merge; ADR 0053's `devdata/` at the
      root). No reason the spec line above does not give.
- [ ] **Step 3:** `CLAUDE.md`: the rules from ADRs 0053 and 0070 say what
      the new ADR says; the "Checks" section drops `check-mirror`.
      `HANDOFF.md`: remove the "Next up" items about the runners' 47
      minutes (`release()`'s move, the runners' wall time, moving the
      validation to C++ runner by runner) and the audit's run, which has no
      runner or claimed set left to audit; add the Bazel plan
      (`docs/plans/2026-11-27-bazel-prototype.md`) as next; "Just finished"
      gets this move.
- [ ] **Step 4:** `just fmt`, `just done`: expect PASS. Commit:
      `docs: record the move of the old Python to old_python/`.
- [ ] **Step 5:** `git status --short` empty. Then the docs tagger's
      frontmatter, if it wrote any: check each `related:` path exists, and
      commit it alone as `docs: refresh the docs index frontmatter`.

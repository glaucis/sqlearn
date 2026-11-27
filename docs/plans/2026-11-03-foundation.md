---
type: task
tags: [foundation, packaging, uv, hatch-vcs, just, git-hooks]
summary: "Implementation plan for sqlearn's repository skeleton: installable package, just recipes, git hooks, and an offline Sphinx site, split into tasks."
related: [docs/specs/foundation.md, docs/adr/0001-uv-for-python-packaging.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/adr/0010-british-prose-american-identifiers.md, CLAUDE.md]
mdindex: [type=0ebb42, tags=1374fc, summary=8cdb73, related=31198d]
---
# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sqlearn's repository skeleton: an installable, versioned,
empty package; every quality gate behind `just`; git hooks that hold each
commit to them; and a skeleton Sphinx site that builds offline.

**Architecture:** One Python package under `src/`, built by hatchling with
hatch-vcs, managed by uv. Every tool's settings in `pyproject.toml`; every job
a `just` recipe; two bash git hooks in `.githooks/`; a Sphinx site built from
`docs/`. No product code.

**Tech Stack:** uv, hatchling + hatch-vcs, duckdb, ruff, ty, mypy, pytest +
pytest-cov, numpydoc, rumdl, typos, just, commitlint, bash, Sphinx +
pydata-sphinx-theme + MyST-NB + sphinx-gallery + sphinxcontrib-bibtex,
MathJax 4.

**Spec:** [`docs/specs/foundation.md`](../specs/foundation.md). Every "§N"
below is a section of it. The spec holds the exact configuration blocks; the
plan says which task writes them and how each is proven. Read both.

## Global Constraints

- Work on the branch `foundation` in the worktree `.claude/worktrees/foundation`
  (`superpowers:using-git-worktrees`). Merge only on Tomas's word.
- Python floor 3.12; matrix 3.12, 3.13, 3.14 (§6).
- The one runtime dependency is `duckdb`; nothing NumPy-shaped at runtime
  (ADR 0005). Dev tools go in the `test`, `lint` and `docs` groups.
- uv only: `uv add`, `uv run`, `uv sync`. Never pip or a bare `python`
  (ADR 0001), except where §2 explicitly builds a pip venv to test an install.
- Nothing needs the network at runtime or at docs build, once MathJax and the
  inventories are fetched (ADR 0006).
- British English in prose, American spelling in identifiers (ADR 0010).
- Markdown prose wraps at 80 columns; Python lines at 88.
- Commits: Conventional Commits, subject ≤72 characters, no AI or tool
  attribution of any kind (`CLAUDE.md`, "Commit conventions"). Never
  `--no-verify`.
- Do not edit `CLAUDE.md`, `.claude/settings.json` or `.mdindex/config.json`.
  §14's `CLAUDE.md` block is written after the merge, not by this plan.
- Every configuration block the spec gives is written as given, comments
  included, except the version numbers Task 1 refreshes.

## Review Focus

The inputs the spec implies that no criterion of §2 exercises, most likely
first. Each has its test in the owning task.

1. **A linked worktree.** This plan itself commits from
   `.claude/worktrees/foundation`. Both hooks must run there, find the
   worktree's `.venv` and the rules file, and refuse or pass as in the main
   checkout. Tests: Task 7 and Task 8, `..._in_a_linked_worktree`.
2. **A path with spaces and non-ASCII characters.** Tomas's folders have
   them (an earlier clone sat under `Desktop - Tomas’s MacBook Air/`). Every
   path in both hooks is quoted. Tests: Task 7 and Task 8,
   `..._under_a_path_with_spaces`.
3. **A partial commit** (`git commit -- <paths>`, the form the
   commit-message skill uses). The pre-commit hook must check the temporary
   index git hands it, not the real one. Test: Task 7,
   `test_a_partial_commit_checks_only_the_named_paths`.
4. **A commit typed from a subfolder.** The commit-msg hook must find
   `commitlint.config.mjs` from its own path, not the working directory.
   Test: Task 8, `test_a_commit_from_a_subfolder_finds_the_rules`.
5. **A commit that deletes a file.** The export of the index must not
   resurrect it or fail on it. Test: Task 7,
   `test_a_commit_that_deletes_a_file_passes`.

---

### Task 1: The installable package

Writes the package, its metadata and tool configuration, refreshes every
version to today's, and proves a fresh environment imports it.

**Files:**

- Create: `pyproject.toml` (§5, and every `[tool.*]` table of §7.1–§7.7)
- Create: `.python-version` (`3.12`), `LICENSE` (§4.2), `README.md` (§4.2)
- Create: `src/sqlearn/__init__.py` (§4.2, exact copy), `src/sqlearn/py.typed`
  (empty)
- Create: `uv.lock` (generated)
- Test: `tests/src/sqlearn/test_init.py`, `tests/test_environment.py`

**Interfaces:**

- Produces: the importable package `sqlearn` with `sqlearn.__version__: str`;
  the dependency groups `test`, `lint`, `docs`; a synced `.venv` on 3.12. Every
  later task runs tools as `uv run --locked <tool>`.

- [ ] **Step 1: Write the tests of §12**

In `tests/src/sqlearn/test_init.py`, each with a one-line docstring:

```python
def test_the_package_imports():
    import sqlearn

    assert sqlearn.__name__ == "sqlearn"


def test_the_version_is_a_string():
    import sqlearn
    from importlib.metadata import version

    assert isinstance(sqlearn.__version__, str)
    assert sqlearn.__version__
    assert sqlearn.__version__ == version("sqlearn")


def test_the_package_ships_py_typed():
    from importlib.resources import files

    assert files("sqlearn").joinpath("py.typed").is_file()
```

In `tests/test_environment.py`: `test_duckdb_answers_a_query` asserts
`duckdb.sql("select sum(range) from range(1000)").fetchone() == (499500,)`;
`test_duckdb_spills_a_query_larger_than_its_memory_limit`, marked
`@pytest.mark.slow`, takes `tmp_path`, and on one connection with
`memory_limit = '64MB'` and `threads = 1` groups
`select i % 10000000 as k from range(20000000) t(i)` by `k`, returning
`count(*)` of groups and `sum` of the group counts. With
`temp_directory = ''` it asserts `pytest.raises(duckdb.OutOfMemoryException)`;
with `temp_directory` set to `str(tmp_path)` it asserts the result is
`(10000000, 20000000)`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --python 3.12 --with pytest --with duckdb pytest tests -m "" -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'sqlearn'`.

- [ ] **Step 3: Write the files**

`pyproject.toml` as §5 gives it, followed by §7.1–§7.7's tables in that
order. `LICENSE` is the Apache-2.0 text fetched from
`https://www.apache.org/licenses/LICENSE-2.0.txt`, unchanged. `README.md` per
§4.2, under 40 lines. `__init__.py` exactly as §4.2 shows.

- [ ] **Step 4: Refresh the versions (§17, item 1)**

Run `uv lock --upgrade`, then read each locked version
(`uv tree --depth 1 --all-groups`). Raise every lower bound in
`pyproject.toml` to the locked version (hatchling and hatch-vcs included),
and `required-version` to the installed uv's minor series (`>=0.13`). If the
locked duckdb is 2.x, keep it and note the version in the commit body. Run
`uv lock` again.

- [ ] **Step 5: Check what duckdb gives the type checkers (§17, item 4)**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run --locked python -c "import duckdb, pathlib; p = pathlib.Path(duckdb.__file__).parent; print(sorted(x.name for x in p.iterdir() if x.suffix in {'.pyi', '.typed'} or x.name == 'py.typed'))"`
Typed: nothing to do. Untyped: add the narrowest override (a
`[[tool.mypy.overrides]]` for `duckdb` with `ignore_missing_imports`, or ty's
equivalent) with a comment giving the reason, and say so in the commit body.

- [ ] **Step 6: Run the tests and the checks that apply**

Run: `uv sync --locked && uv run --locked pytest -m "" -q` Expected: 5 passed.
Run: `uv run --locked pytest -q` Expected: 4 passed, 1 deselected. Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run --locked ruff check && uv run --locked ruff format --check && uv run --locked mypy && uv run --locked ty check`
Expected: all exit 0. Run:
`uv run --locked numpydoc lint src/sqlearn/__init__.py` Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .python-version LICENSE README.md src tests
git commit -m "build: package sqlearn with hatch-vcs and its tool settings"
```

---

### Task 2: The root files and the justfile

**Files:**

- Create: `.editorconfig`, `.gitattributes` (§7.8, exact copies)
- Modify: `.gitignore` (append §7.8's block, less the two worktree lines,
  which are already there)
- Create: `justfile` (§8)

**Interfaces:**

- Consumes: Task 1's package and groups.
- Produces: the recipes `default`, `setup`, `fmt-python`, `fmt-markdown`,
  `fmt`, `lint-python`, `check-types`, `check-types-mypy`, `lint-markdown`,
  `check-spelling`, `check-lockfile`, `test`, `test-hooks`, `test-all`,
  `test-python-versions`, `check-docstrings`, `build-package`,
  `upgrade-dependencies`, `clean`, `check`, `pre-commit`, and `verify`
  (docs recipes join in Task 4). A variable `matrix := "3.12 3.13 3.14"`.

- [ ] **Step 1: Write the files**

`set shell := ["bash", "-euo", "pipefail", "-c"]`. Each recipe has a one-line
comment above it (its `just --list` description) and a `[group]`: `setup`,
`format`, `check`, `test`, `docs`, `build`, `maintain`. Tools run through
`uv run --locked`; `setup`, `check-lockfile`, `build-package` and
`upgrade-dependencies` call `uv` directly.

- `setup`: `git config core.hooksPath .githooks`, then `uv sync --locked`.
- `test`: `uv run --locked pytest --cov --ignore=tests/githooks`.
- `test-hooks`: `uv run --locked pytest tests/githooks -m ""`.
- `test-all`: `uv run --locked pytest --cov -m ""`.
- `test-python-versions`: for each `v` in `matrix`,
  `UV_PROJECT_ENVIRONMENT=.venvs/py$v uv run --locked --python $v pytest -m "" --ignore=tests/githooks`.
- `check-docstrings`:
  `uv run --locked numpydoc lint $(git ls-files 'src/*.py')`.
- `clean`: `rm -rf` exactly the build outputs, `.venvs/` and caches of §7.8;
  never `.venv/` or a worktree.
- `upgrade-dependencies`: `uv lock --upgrade`, then `just verify`
  (`fetch-inventories` is inserted in Task 4).
- `verify`: `check`, `check-types-mypy`, `test-python-versions`, `test-hooks`,
  `check-docstrings` (`build-docs` is appended in Task 4).

- [ ] **Step 2: Verify the recipes**

Run: `just --list` Expected: every recipe above, each with its description,
under its group. Run:
<!-- markdownlint-disable-next-line MD013 -->
`just lint-python check-types check-types-mypy check-lockfile test test-all check-docstrings build-package`
Expected: all exit 0; `dist/` holds one `.tar.gz` and one `.whl`. Run:
`just test-python-versions` Expected: 5 passed on each of 3.12, 3.13 and 3.14;
`.venv` still 3.12 (`uv run --locked python -V`). Run:
<!-- markdownlint-disable-next-line MD013 -->
`echo 'import os' >> src/sqlearn/__init__.py; just check; echo $?; git checkout src/sqlearn/__init__.py`
Expected: `just` names `lint-python` as the recipe that failed; exit non-zero.
(`lint-markdown` and `check-spelling` may fail on today's docs: that is Task 3.)

- [ ] **Step 3: Commit**

```bash
git add .editorconfig .gitattributes .gitignore justfile
git commit -m "build: add the justfile and the files no formatter owns"
```

---

### Task 3: Today's Markdown under the gates

Brings `CLAUDE.md` and `docs/` under rumdl and typos (§13) and runs the two
tool checks of §17, items 2 and 3.

**Files:**

- Modify: every tracked `.md` file `rumdl fmt` rewraps
- Modify: `pyproject.toml` (`extend-words` only, if needed)

**Interfaces:**

- Produces: a tree on which `just check` exits 0.

- [ ] **Step 1: Confirm rumdl and typos read their settings (§17, item 2)**

Run: `uv run --locked rumdl config` Expected: `line-length`, `blockquotes` and
`reflow` shown with `[from pyproject.toml]`. Run:
`uv run --locked typos --dump-config - | grep -E 'locale|extend-exclude' -A3`
Expected: `locale = "en"` and the three exclusions of §7.7.

- [ ] **Step 2: Compare rumdl with markdownlint-cli2 once (§17, item 3)**

Write a config outside the repository (`$TMPDIR/mdl/.markdownlint-cli2.jsonc`)
with MD013 alone at `line_length: 80`, `code_blocks: false`, `tables: false`,
and run
<!-- markdownlint-disable-next-line MD013 -->
`npx --yes markdownlint-cli2 --config "$TMPDIR/mdl/.markdownlint-cli2.jsonc" $(git ls-files '*.md')`
and `uv run --locked rumdl check --config 'MD013.reflow = false' .`. Drop
block-quote lines from both and compare by file and line. Expected: the same
findings. If they differ, stop and report the difference to Tomas: the spec's
fallback (markdownlint-cli2 replaces rumdl) is his call.

- [ ] **Step 3: Format, on its own commit**

Run: `just fmt-markdown && git diff --stat`
Expected: only line breaks change. Check with
`git diff --word-diff=porcelain | grep -E '^[-+][^-+]' | head` printing
nothing but whitespace-only changes. mdindex front matter is untouched.

```bash
git add -u '*.md'
git commit -m "style: wrap the Markdown at 80 columns"
```

- [ ] **Step 4: Put right what fmt cannot, then verify**

Run: `just check`
Fix each remaining finding: a long heading reworded, a line that cannot wrap
given `<!-- markdownlint-disable-next-line MD013 -->`, a typo corrected, or a
real word mapped to itself in `extend-words` with a comment.
Run: `just check`
Expected: exit 0.

- [ ] **Step 5: Commit (only if Step 4 changed anything)**

```bash
git add -u
git commit -m "docs: fix the findings the Markdown and spelling checks report"
```

---

### Task 4: The documentation site

**Files:**

- Create: `docs/conf.py` (§11.2, exact copy, plus the MathJax lines of Task
  5 left as the comment), `docs/index.md`, `docs/bibliography.md`,
  `docs/references.bib`, `docs/_static/switcher.json`
- Create: the section indexes of §4.1 (`guide`, `reference`, `learn` and its
  three levels, `validation`, `benchmarks`, `adr`, `architecture`), per §4.3
- Create: `docs/_inventories/python.inv`, `docs/_inventories/duckdb.inv`
- Create: `examples/GALLERY_HEADER.rst`, `examples/show_version.py` (§11.4)
- Modify: `justfile` (`fetch-inventories`, `build-docs`; `build-docs` appended
  to `verify`; `fetch-inventories` inserted in `upgrade-dependencies`)

**Interfaces:**

- Consumes: Task 2's `justfile`.
- Produces: `just build-docs` building `docs/_build/html/` and running the
  doctests; `docs/architecture/index.md` with a `toctree` of `overview`,
  `workflow` and `../adr/index`, which Task 6 extends.

- [ ] **Step 1: Fetch the inventories (§17, item 5)**

`fetch-inventories` downloads `https://docs.python.org/3/objects.inv` and the
DuckDB Python reference's `objects.inv` (the base URL in §11.2's
`intersphinx_mapping` plus `objects.inv`) into `docs/_inventories/`, with
`curl --fail --location`. If DuckDB 2.x moved its Python reference, use the new
base URL in both `conf.py` and the recipe. Run `just fetch-inventories`.
Expected: two non-empty files;
<!-- markdownlint-disable-next-line MD013 -->
`uv run --locked python -m sphinx.ext.intersphinx docs/_inventories/duckdb.inv | grep DuckDBPyConnection`
prints at least one line.

- [ ] **Step 2: Write the pages and `conf.py`**

Each section index per §4.3: title equal to its navigation label, one or two
sentences. `docs/index.md`'s `toctree` lists, in order, `guide/index`,
`reference/index`, `examples/index`, `learn/index`, `validation/index`,
`benchmarks/index`, `architecture/index`. `docs/adr/index.md` uses
`:glob:` over `0*`. `docs/reference/index.md` holds the `autosummary` of
`sqlearn` in an `{eval-rst}` block. `bibliography.md` has `orphan: true`.

- [ ] **Step 3: Write `build-docs` and build**

`build-docs`: `sphinx-build -W --keep-going -b html docs docs/_build/html`,
then `sphinx-build -W --keep-going -b doctest docs docs/_build/doctest`
(`fetch-mathjax` is prepended in Task 5).
Run: `just build-docs`
Expected: exit 0. If mdindex front matter raises a warning (§17, item 7),
fix it in `conf.py` only (for example `myst_heading_anchors` or a
`suppress_warnings` entry with its reason), never by editing the front
matter.

- [ ] **Step 4: Check §2, criterion 3, less MathJax**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run --locked python -c "import re,pathlib; h=pathlib.Path('docs/_build/html/index.html').read_text(); print(re.findall(r'class=\"nav-link[^\"]*\"[^>]*href=\"([^\"]+)\"', h))"`
Expected: the seven links in order, and no `More` in the bar. Run:
`ls docs/_build/html/learn/{beginner,intermediate,advanced}/index.html docs/_build/html/adr/index.html`
Expected: all four exist; `adr/index.html` links every `0*.html`. Run:
<!-- markdownlint-disable-next-line MD013 -->
`grep -c "$(uv run --locked python -c 'import sqlearn; print(sqlearn.__version__)')" docs/_build/html/examples/show_version.html`
Expected: at least 1. Run: `git status --short` Expected: nothing new outside
what this task created; the build outputs are ignored.

- [ ] **Step 5: Commit**

```bash
git add docs examples justfile
git commit -m "feat(site): build the skeleton site with its seven sections"
```

---

### Task 5: Offline MathJax

**Files:**

- Modify: `justfile` (`fetch-mathjax`, prepended to `build-docs`)
- Modify: `docs/conf.py` (`mathjax_path`, `mathjax4_config`)
- Create: `docs/architecture/writing.md` (§11.2's notebook page; its prose
  is Task 6's, this task writes the executed cell and one formula)

**Interfaces:**

- Produces: `docs/_static/mathjax/` filled by `fetch-mathjax`; a site with no
  external script or stylesheet.

- [ ] **Step 1: Pin MathJax (§17, item 6)**

Find the latest 4.x of `mathjax` and its `@mathjax/mathjax-newcm-font`
(`npm view mathjax@4 version`,
`npm view <pkg>@<v> dist.tarball dist.integrity`). Pin both versions and sha512
integrities in `justfile` variables.

- [ ] **Step 2: Write `fetch-mathjax`**

Unless `docs/_static/mathjax/tex-chtml.js` exists: download both tarballs with
`curl --fail`, verify each sha512 (`openssl dgst -sha512 -binary | base64`
against the integrity), unpack, and copy `tex-chtml.js` and only the font
files the CHTML output loads into `docs/_static/mathjax/`. Set `mathjax_path`
to `mathjax/tex-chtml.js` and `mathjax4_config` so fonts and any loader path
resolve to that copy, and disable the speech/assistive extensions that fetch
`speech-rule-engine` from a CDN.

- [ ] **Step 3: Write the notebook page**

`docs/architecture/writing.md` as a MyST-NB text notebook (`file_format:
mystnb` front matter, kernel `python3`) with one `{code-cell}` printing
`sqlearn.__version__` and one `$$` display formula.

- [ ] **Step 4: Verify offline (§2, criterion 3)**

Run: `just clean && just build-docs` Expected: exit 0. Run:
`grep -rlE '<(script|link)[^>]+(src|href)="https?://' --include='*.html' docs/_build/html`
Expected: no output. Run:
`grep -rhoE 'https?://[^"'"'"' )]+' docs/_build/html/_static/mathjax | sort -u`
Expected: no URL MathJax would fetch at runtime (licence and comment URLs are
fine; a CDN host in loader code is not). Then open
`docs/_build/html/architecture/writing.html` with the network off (Wi-Fi off, or
`uv run --locked python -m http.server -d docs/_build/html` with the browser
offline) and confirm the formula renders. If MathJax 4 cannot be made
self-contained, fall back to MathJax 3.2.2 (§11.3) and confirm it carries its
own fonts.

- [ ] **Step 5: Commit**

```bash
git add justfile docs/conf.py docs/architecture/writing.md
git commit -m "feat(site): bundle MathJax so the site reads offline"
```

---

### Task 6: The Development section's pages

**Files:**

- Create: `docs/architecture/setup.md`, `layout.md`, `python-versions.md`,
  `testing.md`
- Modify: `docs/architecture/writing.md` (its prose),
  `docs/architecture/index.md` (`toctree`: `overview`, `workflow`, `setup`,
  `layout`, `python-versions`, `writing`, `testing`, `../adr/index`)

**Interfaces:**

- Consumes: Tasks 1–5's recipes, settings and tree, which these pages
  describe as they are, not as planned.

- [ ] **Step 1: Write the pages from §15's table**

- `setup.md`: `brew install uv just commitlint`, `just setup`, the recipes by
  group as `just --list` shows them, what the two hooks do (§9, §10), and
  that work is laptop-only for now (§16).
- `layout.md`: §4.5's tree and its reasons, `tests/` mirroring the root
  (§12), examples grouped by area (§11.4), what arrives later (§4.4).
- `python-versions.md`: §6's policy word for word, and its three reasons.
- `writing.md`: §11.5's rule word for word, British prose and American
  identifiers, the 80-column wrap and `just fmt`, the disable comment, math
  and text notebooks.
- `testing.md`: one docstring per test, no annotations, no numpydoc
  validation, the `slow` marker and the two tiers, the hook tests and
  `just test-hooks`, coverage reported with no floor yet.

- [ ] **Step 2: Verify**

Run: `just check && just build-docs`
Expected: exit 0; `docs/_build/html/architecture/index.html` links all seven
pages and the decision records.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture
git commit -m "docs: write the Development section's convention pages"
```

---

### Task 7: The pre-commit hook

**Files:**

- Create: `.githooks/pre-commit` (executable)
- Test: `tests/githooks/test_pre_commit.py`

**Interfaces:**

- Consumes: the `pre-commit` recipe (Task 2); `core.hooksPath` set by
  `just setup`.
- Produces: a hook that runs `just pre-commit` on an export of the index.

- [ ] **Step 1: Write the tests**

A fixture builds a scratch repository under `tmp_path` (and a variant under
`tmp_path / "with space ’é"`): `git init -b main`, a local user name and
email, a copy of the hook at `.githooks/pre-commit`, `core.hooksPath` set to
`.githooks`, and a first commit holding the hook copy and one file (so a
linked worktree has the hook too). A stand-in `just` in a `bin/` folder put
first on `PATH` appends `$PWD` and `"$@"` to a log file and exits with
`$FAKE_JUST_EXIT` (default 0). Tests, each with a one-line docstring:

- `test_a_passing_recipe_lets_the_commit_land`: the commit exits 0 and the log
  holds `pre-commit`.
- `test_a_failing_recipe_refuses_the_commit`: with `FAKE_JUST_EXIT=1`, the
  commit exits non-zero, `HEAD` is unchanged, stderr names `just fmt`.
- `test_the_checks_read_the_index_not_the_working_tree`: the stand-in
  asserts a staged file's content in `$PWD`; an unstaged edit to the same file
  is absent from the export; `$PWD` is not the repository.
- `test_a_partial_commit_checks_only_the_named_paths`: two staged files,
  `git commit -m … -- a.txt`; the export holds `a.txt`'s new content and
  `b.txt`'s HEAD content.
- `test_a_commit_that_deletes_a_file_passes`: `git rm` a file and commit;
  exit 0, and the file is absent from the export.
- `test_the_hook_runs_under_a_path_with_spaces`: the fixture's variant;
  exit 0, log holds `pre-commit`.
- `test_the_hook_runs_in_a_linked_worktree`: `git worktree add`, commit there;
  exit 0, and the stand-in saw `UV_PROJECT_ENVIRONMENT` ending in the
  worktree's `.venv`.
- `test_the_environment_is_not_synced_from_the_copy`: the stand-in saw
  `UV_NO_SYNC=1`.
- `test_no_just_refuses_with_the_cure`: `PATH` holds only symlinks to `git`,
  `bash`, `env` and the coreutils the hook uses; exit non-zero, stderr holds
  `brew install just uv`.
- `test_the_hook_is_committed_executable`: in this repository,
  `git ls-files -s .githooks/pre-commit` starts with `100755`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --locked pytest tests/githooks/test_pre_commit.py -q`
Expected: FAIL, the hook file does not exist.

- [ ] **Step 3: Write `.githooks/pre-commit`**

Bash, `set -u`, §9's four steps. Root from `git rev-parse --show-toplevel`;
export with `GIT_INDEX_FILE` honoured (git sets it;
`git checkout-index -a --prefix="$tmp/"` reads it); `trap` removes the temp
folder; run
`(cd "$tmp" && UV_PROJECT_ENVIRONMENT="$root/.venv" UV_NO_SYNC=1 just pre-commit)`.
On failure print the cures of §9 step 3 to stderr and exit 1. Quote every
expansion. `chmod +x`.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --locked pytest tests/githooks/test_pre_commit.py -q`
Expected: all pass.

- [ ] **Step 5: Install it here and check it works (§2, criterion 5, first
  part)**

Run: `just setup`, then
<!-- markdownlint-disable-next-line MD013 -->
`echo 'import os' >> src/sqlearn/__init__.py && git add src/sqlearn/__init__.py && git commit -m "test: break lint"; echo $?`
Expected: refused, naming `lint-python`. Then
`git checkout HEAD -- src/sqlearn/__init__.py`. Run:
`time just check && time just test` Expected: each under 10 seconds (§2,
criterion 7).

- [ ] **Step 6: Commit (through the hook itself)**

```bash
git add .githooks/pre-commit tests/githooks/test_pre_commit.py
git commit -m "feat(hooks): refuse a commit whose files fail just check"
```

---

### Task 8: commitlint and the commit-msg hook

**Files:**

- Create: `commitlint.config.mjs` (§10.1, exact copy)
- Create: `.githooks/commit-msg` (executable)
- Test: `tests/githooks/test_commit_msg.py`

**Interfaces:**

- Consumes: `commitlint` on `PATH` (21.2.4 today); `core.hooksPath`.
- Produces: a hook that refuses messages breaking a level-2 rule.

- [ ] **Step 1: Confirm commitlint's behaviour (§17, item 8)**

In a scratch folder with the config:
`echo 'feat: add x' | commitlint --config commitlint.config.mjs --strict; echo $?`
gives 0; `echo 'Feat: Add x.' | …` gives 3; `echo 'feat: Add x' | …` gives 2;
`echo 'feat!: drop x' | …` gives 3 (no footer).

- [ ] **Step 2: Write the tests**

Module-level `pytestmark = pytest.mark.skipif(shutil.which("commitlint") is
None, reason="commitlint is not installed: brew install commitlint")`, except
the no-commitlint test. A fixture builds a scratch repository with copies of
the hook and the rules, `core.hooksPath` set, and a variant under a path with
spaces and non-ASCII characters. Tests, each with a one-line docstring:

- `test_a_good_message_lands`: `docs: clarify the setup steps`.
- `test_a_rule_at_level_two_refuses` (parametrized): `Updated stuff.`,
  `feat: add x.`, `FEAT: add x`, `feat(Auth): add x`, a 73-character header,
  `wip: add x`; each refused, stderr holds `does not follow the commit
  conventions`.
- `test_a_warning_lets_the_commit_land`: `feat: Add x` lands and stderr holds
  `warning never refuses`.
- `test_a_breaking_change_needs_its_footer`: `feat!: drop x` refused;
  `feat!: drop x` with body and `BREAKING CHANGE: x is gone` footer lands.
- `test_an_empty_message_is_refused`: `git commit --allow-empty-message -m ""`
  refused, stderr holds `empty`.
- `test_a_merge_with_gits_own_message_lands`: a non-fast-forward
  `git merge --no-edit` lands.
- `test_the_scissors_section_is_ignored`: a message file holding a valid
  subject, comment lines and a `# ------------------------ >8` section with
  diff text lands via `git commit -F` with `--cleanup=scissors`.
- `test_a_commit_from_a_subfolder_finds_the_rules`: commit run with
  `cwd=repo/"sub"` lands.
- `test_the_hook_runs_under_a_path_with_spaces`: the variant; a good message
  lands, a bad one is refused.
- `test_the_hook_runs_in_a_linked_worktree`: a bad message is refused there.
- `test_no_commitlint_refuses_with_the_cure` (not skipped): restricted
  `PATH`; refused, stderr holds `brew install commitlint` and `has not been
  looked at`.
- `test_missing_rules_refuse`: config deleted; refused, stderr names the path.
- `test_rules_that_fail_to_load_are_a_tooling_failure`: config replaced with
  `export default {`; refused, stderr holds `could not check this message` and
  `Rewording it will not help`.
- `test_empty_rules_are_a_tooling_failure`: config
  `export default { rules: {} };`; stderr holds `could not check this message`.
- `test_the_hook_is_committed_executable`: mode `100755`.

- [ ] **Step 3: Run them to see them fail**

Run: `uv run --locked pytest tests/githooks/test_commit_msg.py -q`
Expected: FAIL.

- [ ] **Step 4: Write `.githooks/commit-msg`**

Bash, `set -u`, §10.2's seven steps in order. The rules path is
`"$(cd "$(dirname "$0")/.." && pwd)/commitlint.config.mjs"`. Strip with
`LC_ALL=C sed -E -e '/^# -+ >8 -+$/,$d' -e '/^#/d'`. Find commitlint with
`command -v`, then `"$(npm prefix -g)/bin/commitlint"` if npm exists. Run
<!-- markdownlint-disable-next-line MD013 -->
`PATH="$(dirname "$lint"):$PATH" "$lint" --config "$rules" --strict --no-color < "$clean"`
and branch on 0, 2, 3 (checking for `[empty-rules]`), and anything else, with
§10.2's words. `chmod +x`.

- [ ] **Step 5: Run them to see them pass**

Run: `uv run --locked pytest tests/githooks -q -m ""`
Expected: all pass, both files.

- [ ] **Step 6: Check it here (§2, criterion 5, second part)**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`echo >> README.md && git add README.md && git commit -m "Updated stuff."; echo $?`
Expected: refused by commitlint. Then `git checkout HEAD -- README.md`.

- [ ] **Step 7: Commit (through both hooks)**

```bash
git add commitlint.config.mjs .githooks/commit-msg tests/githooks/test_commit_msg.py
git commit -m "feat(hooks): check every commit message with commitlint"
```

---

### Task 9: Acceptance

Runs every criterion of §2 from a fresh clone of the branch. No new files
unless a criterion fails, in which case the fix goes in the task that owns
the file, as a new commit.

**Files:** none.

- [ ] **Step 1: Push the branch**

Run: `git push -u origin foundation`

- [ ] **Step 2: Criteria 1 and 2**

Run §2 criterion 1's three commands with `-b foundation` on the clone, then
`just verify` and `just --list` in it.
Expected: `(3, 12)` and a version; `just verify` exits 0; `just --list`
shows every recipe §8 marks "now".

- [ ] **Step 3: Criterion 3**

In the clone: `just build-docs`, then Task 4 Step 4's checks and Task 5
Step 4's `grep`.
Expected: as there.

- [ ] **Step 4: Criterion 4**

Run §2 criterion 4's commands verbatim. Expected: `0.0.1`;
`License-Expression: Apache-2.0`; `Requires: duckdb`; `py.typed` present under
`/tmp/sqlearn-pip/lib/python3.12/site-packages/sqlearn/`. Repeat without the tag
in a third clone; expected `0.1.devN+g<hash>`. Run:
<!-- markdownlint-disable-next-line MD013 -->
`cd /tmp/sqlearn-done && just build-package && uv venv --python 3.12 /tmp/sqlearn-sdist && uv pip install --python /tmp/sqlearn-sdist dist/*.tar.gz && /tmp/sqlearn-sdist/bin/python -c 'import sqlearn; print(sqlearn.__version__)'`
Expected: a version, not an error: the sdist installs without git.

- [ ] **Step 5: Criteria 5 to 7**

In the clone: `just setup`; the three commits of criterion 5; `just test-hooks`;
`time just check` and `time just test`.
Expected: as §2 says.

- [ ] **Step 6: Report**

Remove the scratch folders. Report to Tomas each criterion with the command
and what it printed, the versions Task 1 locked, and the answers to §17's
checks. Criterion 8 (`CLAUDE.md`'s §14 block) is written after the merge,
once Tomas approves it, from the `justfile` as merged.

---
type: spec
tags: [foundation, repository-layout, tooling, documentation, git-hooks, versioning]
summary: "Spec for sqlearn's repository skeleton: layout, packaging, quality gates, git hooks, docs toolchain, and conventions, with acceptance criteria."
related: ["../architecture/overview.md", "../adr/README.md", "../questions/site-hosting.md", "../adr/0004-apache-2-licence.md", "../adr/0011-curriculum-levels.md"]
mdindex: [type=d4f02e, tags=6ffc41, summary=ed0207, related=8aec34]
---
# Foundation

Part 3.1 of [the overview](../architecture/overview.md): the repository
skeleton every later part is built in.

Status: draft, for Tomas's review. Adapted on 2026-11-03 from the earlier
attempt's foundation spec, which Tomas approved section by section on
2026-10-01. Everything that spec decided carries over unless §19 says
otherwise; this file is now complete on its own, and nothing here depends on
the earlier repository.

How to read it:

- "§N" is a section of this spec. "ADR NNNN" is a record in
  [`docs/adr/`](../adr/README.md).
- **Checked** marks a fact the earlier attempt established by running the named
  tool version on 2026-10-01, on Tomas's laptop (macOS, Apple silicon), in
  scratch folders. Tool versions have moved since (uv 0.13.6 is installed
  today), so the plan repeats every check at the versions it locks before it
  builds on it (§17).
- **To verify in the plan** marks an option or behaviour nobody has run yet.
- Values in configuration blocks are the values the plan writes; comments in
  them are the comments the files carry.

## 1. Purpose

The foundation gives sqlearn its skeleton: the layout, the package and how it
is built and versioned, the quality gates and the recipes that run them, the
git hooks that hold every commit to them, the documentation toolchain with a
skeleton site, and the conventions everyone writes to. It fixes what is
expensive to change later (the folders, the site's URLs, the build backend,
every tool's configuration) and creates nothing a later part owns. It holds no
product code.

There is no CI and no deploy while the repository is private (§16), and site
hosting is open ([questions/site-hosting.md](../questions/site-hosting.md)).

## 2. Done when

Each criterion is something a reviewer runs on Tomas's laptop, which has `uv`,
`just` and `commitlint` from Homebrew and nothing else installed for this
project. The scratch paths are examples; nothing a check creates is pushed.

1. **A fresh clone installs with one command.**

   ```sh
   git clone https://github.com/glaucis/sqlearn.git /tmp/sqlearn-done
   cd /tmp/sqlearn-done && uv sync --locked
   uv run python -c 'import sys, sqlearn; print(sys.version_info[:2], sqlearn.__version__)'
   ```

   `uv sync --locked` exits 0, and the last command prints `(3, 12)` and a
   version string.

2. **The gates pass.** In that clone `just verify` exits 0, and `just --list`
   names every recipe §8 marks as built now, each with its one-line
   description.

3. **The site builds with its seven sections.** In that clone `just build-docs`
   exits 0, and in `docs/_build/html/`:
   - the navigation bar of `index.html` holds exactly seven entries, in this
     order, linking to `guide/index.html`, `reference/index.html`,
     `examples/index.html`, `learn/index.html`, `validation/index.html`,
     `benchmarks/index.html` and `architecture/index.html`, with no "More"
     menu;
   - `learn/beginner/index.html`, `learn/intermediate/index.html` and
     `learn/advanced/index.html` exist;
   - `adr/index.html` lists every decision record;
   - `examples/show_version.html` holds the version string the placeholder
     example printed when the build ran it;
   - no page loads a script or a stylesheet from another host, so this prints
     nothing:

     ```sh
     grep -rlE '<(script|link)[^>]+(src|href)="https?://' --include='*.html' docs/_build/html
     ```

4. **The package is versioned from the git tag.** In a second scratch clone,
   with a tag that is never pushed:

   ```sh
   git clone /tmp/sqlearn-done /tmp/sqlearn-tag && cd /tmp/sqlearn-tag
   git tag v0.0.1
   uv venv --seed --python 3.12 /tmp/sqlearn-pip
   /tmp/sqlearn-pip/bin/python -m pip install .
   /tmp/sqlearn-pip/bin/python -c 'import sqlearn; print(sqlearn.__version__)'
   /tmp/sqlearn-pip/bin/python -m pip show sqlearn
   ```

   The version printed is `0.0.1`; `pip show` lists
   `License-Expression: Apache-2.0` and `Requires: duckdb`; the installed
   package holds `py.typed`. Without the tag the same steps give a version of
   the form `0.1.devN+g<hash>`.

5. **The git hooks guard every commit.** In the first clone, run `just setup`.
   Then:
   - a commit that breaks a check is refused, and the refusal names the recipe
     that failed: append `import os` to `src/sqlearn/__init__.py`, stage it
     and commit, and the commit is refused, naming `lint-python`;
   - a commit whose message breaks the conventions is refused: with that line
     removed, `git commit -m "Updated stuff."` on a one-line change to
     `README.md` is refused by commitlint;
   - the same change committed as `docs: clarify the setup steps` goes
     through.

6. **The hooks' tests pass.** `just test-hooks` exits 0.

7. **The per-commit gates take seconds.** With the environment synced,
   `time just check` and `time just test` each report under 10 seconds.

8. **The conventions are written where every agent reads them.** `CLAUDE.md`
   holds the block of §14, and the site's Development section holds the pages
   of §15.

## 3. What exists, and what stays

The foundation builds on the tree as it is and changes nothing that works.

- **`docs/`** keeps its folders and files: `adr/`, `architecture/`, `specs/`,
  `plans/`, `questions/`, `agents/`. The site builds from `docs/`, so the
  folders that are not on the site are excluded by name (§11.2).
- **`.claude/settings.json`** is not changed.
- **`.mdindex/config.json`** and the docs index are not changed. Every
  Markdown file keeps the front matter mdindex writes.
- **`.gitignore`** keeps its lines and gains those of §7.8.
- **`CLAUDE.md`** is not edited by the plan's tasks; the block of §14 is
  written after the merge, from the `justfile` as it then is.

## 4. The tree

### 4.1 What the foundation creates or changes

    sqlearn/
      .githooks/
        pre-commit                    the per-commit gate, §9
        commit-msg                    the message check, §10
      commitlint.config.mjs           the commit conventions, §10
      docs/
        conf.py                       the Sphinx configuration, §11.2
        index.md                      the site's root page, §4.3
        bibliography.md               the site's one bibliography, §11.2
        references.bib                its BibTeX file: a comment, no entry
        _static/switcher.json         the version switcher's one entry, §11.2
        _inventories/python.inv       intersphinx inventories, §11.3
        _inventories/duckdb.inv
        guide/index.md                one index page per section, §11.1
        reference/index.md
        learn/index.md
        learn/beginner/index.md
        learn/intermediate/index.md
        learn/advanced/index.md
        validation/index.md
        benchmarks/index.md
        adr/index.md                  the decision records' index, §11.1
        architecture/index.md         the Development section, §15
        architecture/setup.md
        architecture/layout.md
        architecture/python-versions.md
        architecture/writing.md
        architecture/testing.md
      examples/
        GALLERY_HEADER.rst            the gallery's index text, §11.4
        show_version.py               the placeholder example, §11.4
      src/sqlearn/
        __init__.py                   a docstring and the version, §4.2
        py.typed                      empty
      tests/
        src/sqlearn/test_init.py      §12
        test_environment.py           §12
        githooks/
          test_pre_commit.py          §9
          test_commit_msg.py          §10
      pyproject.toml                  new, §5 and §7
      uv.lock                         new
      justfile                        new, §8
      .python-version                 new: 3.12
      .editorconfig                   new, §7.8
      .gitattributes                  new, §7.8
      .gitignore                      extended, §7.8
      README.md                       new, §4.2
      LICENSE                         new, §4.2

### 4.2 The root files and the package

- **`LICENSE`** is the Apache License 2.0, word for word as
  `https://www.apache.org/licenses/LICENSE-2.0.txt` gives it, with the
  appendix left as it is ([ADR 0004](../adr/0004-apache-2-licence.md)).
- **`README.md`** is one screen: what sqlearn is, in two or three sentences
  from the overview's purpose; that it is pre-alpha and holds no usable library
  yet; that it needs Python 3.12 or newer, with a link to
  `docs/architecture/python-versions.md`; how to work on it
  (`brew install uv just commitlint`, then `just setup`, then `just --list`);
  and that it is licensed under the Apache License 2.0.
- **`src/sqlearn/__init__.py`** holds a module docstring and the version, and
  nothing else:

  ```python
  """Machine learning computed inside DuckDB, on data larger than memory.

  Examples
  --------
  >>> import sqlearn
  >>> isinstance(sqlearn.__version__, str)
  True
  """

  from importlib.metadata import version

  __all__ = ["__version__"]

  __version__: str = version("sqlearn")
  ```

  The version is read from the installed package's metadata, which hatch-vcs
  wrote from the git tag, so no version file is generated and nothing has to be
  ignored. The Examples section is what the docs build's doctest pass runs
  (§11.2), and what numpydoc's validation asks of every public object (§7.5).
- **`src/sqlearn/py.typed`** is empty. It tells users' type checkers to read
  the package's annotations.

### 4.3 The pages

Every page is short; a section's content belongs to the part that owns it.

- **`docs/index.md`**: the title `sqlearn`, one paragraph saying what it is,
  and the `toctree` of the seven section indexes in navigation order.
- **A section's `index.md`**: its title, which is the navigation bar's label,
  and one or two sentences on what the section will hold. No further pages.
- **`docs/learn/`**: the index holds the `toctree` of the three levels. Each
  level's index says, in a sentence or two from
  [ADR 0011](../adr/0011-curriculum-levels.md), what it assumes and what the
  reader will be able to do at its end; the lessons are the curriculum spec's
  (3.5).
- **`docs/reference/index.md`**: its title, a sentence, and an `autosummary`
  of the package `sqlearn` with `:toctree: generated/`, so the generated page
  for the package shows its docstring.
- **`docs/adr/index.md`**: its title, a sentence, and a `toctree` with
  `:glob:` over `0*`, so every decision record is listed as it lands.
- **`docs/architecture/`**: the Development section's pages, §15. The existing
  `overview.md` and `workflow.md` join its `toctree`.

### 4.4 What the foundation does not create

- **`validation/` and `benchmarks/` at the root.** They arrive with their
  parts: validation with the first page in the core's slice, benchmarks with
  3.9.
- **`CHANGELOG.md`, `NOTICE` and `CITATION.cff`.** The first release brings
  them.
- **`.github/`.** No workflow while the repository is private.
- **`conftest.py` and `__init__.py` files under `tests/`.** pytest imports the
  tests in `importlib` mode (§7.4), which needs neither.
- **Content.** No guide chapter, lesson, validation page or benchmark, and no
  example beyond the placeholder.

### 4.5 The layout as a whole

The tree, with what the later parts bring:

    sqlearn/
      .claude/               Claude Code settings; project agents and skills
                             when they are created
      .githooks/             the git hooks, installed by `just setup`
      docs/                  the Sphinx source root: the whole site
        adr/                 decision records (site: adr/)
        architecture/        how the system is built; the site's
                             Development section
        specs/  plans/       specs and plans; in git, not on the site
        questions/  agents/  open questions and agent configuration;
                             in git, not on the site
        guide/               the user guide
        reference/           API reference configuration; pages generated
        learn/               the tutorials: beginner/, intermediate/,
                             advanced/
        validation/          the validation pages, 3.8, rendered from data
        benchmarks/          the benchmark pages, 3.9, rendered from data
      examples/              sphinx-gallery's sources; the gallery is
                             generated into docs/ and ignored by git
      validation/            the reference implementations and runners,
                             3.8, and their committed results; imported by
                             tests/, never installed
      benchmarks/            the benchmark suite and its committed results
      src/sqlearn/           the package
      tests/                 mirrors the root, dot folders without their dot
      pyproject.toml         the package, and every tool's configuration
      uv.lock                the lockfile
      justfile               the recipes
      commitlint.config.mjs  the commit conventions
      .python-version        3.12, the floor
      .editorconfig          for the files no formatter owns
      .gitattributes         LF line endings everywhere
      .gitignore             what git never sees
      README.md              what sqlearn is, in one screen
      CHANGELOG.md           from the first release, generated from commits
      LICENSE                Apache-2.0
      NOTICE                 Apache's attribution file, from the first release
      CITATION.cff           how to cite, from the first release
      CLAUDE.md              the agents' instructions

`.github/workflows/` arrives when the repository is public, with Actions.

Why `src/`: the package cannot be imported from the checkout by accident, so the
tests run against what users install. Why `docs/` holds everything the site
shows: one site, one build, one deploy. Why `examples/`, `validation/` and
`benchmarks/` sit at the root: they are code a user reads, found without opening
`docs/`, as scikit-learn keeps its examples.

**What never enters the repository**, against GitHub's size limits: datasets
(the package bundles a few small ones; anything larger is fetched only by an
explicit call, and the examples generate big data inside DuckDB); outputs
(executed notebooks, the gallery's figures, rendered HTML, all made by the
build, with lessons stored as text); and the built site in the history, which
runs to hundreds of MB a deploy. The built site is overwritten on every deploy,
never accumulated, wherever the hosting decision puts it. One repository for
everything until a limit comes into view; the source stays text-sized by
construction.

**The library and the whole site, the curriculum included, are one
repository**: the reference is generated from the docstrings, the examples run
the code, and the version switcher shows each release's docs beside it, so
they cannot be built apart. If the curriculum ever has contributors or a rhythm
of its own, it becomes a second site under the same domain and theme, built
from its own repository: a decision for that day.

**Where the applications live** is open
([questions/applications-home.md](../questions/applications-home.md)); either
way the library stays at `src/sqlearn/`, so the foundation does not wait on it.

## 5. Packaging and environments

`hatchling` with `hatch-vcs`, so the version comes from the git tag and nothing
is bumped by hand; `uv` for the environments, the one universal lockfile,
committed, and the dependency groups, which are never published
([ADR 0001](../adr/0001-uv-for-python-packaging.md)). uv's own build backend
was set aside: it builds pure Python only, reads no version from a tag, and has
no build hook to bundle a built front end later. `pyproject.toml` holds:

```toml
[build-system]
requires = ["hatchling>=1.32.4", "hatch-vcs>=0.5.0"]
build-backend = "hatchling.build"

[project]
name = "sqlearn"
dynamic = ["version"]
description = "Machine learning computed inside DuckDB, on data larger than memory."
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE"]
requires-python = ">=3.12"
authors = [{ name = "Tomas Pecukevicius", email = "pecukevicius@gmail.com" }]
classifiers = [
    "Development Status :: 2 - Pre-Alpha",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Typing :: Typed",
]
dependencies = [
    # The engine every computation runs in, and the one runtime dependency.
    "duckdb>=1.5.6",
]

[dependency-groups]
test = ["pytest>=9.1.1", "pytest-cov>=7.1.0"]
lint = ["mypy>=2.3.1", "ruff>=0.16.9", "rumdl>=0.2.78", "ty>=0.0.84", "typos>=1.50.3"]
docs = [
    "ipykernel>=7.4.0",
    "myst-nb>=1.4.0",
    "numpydoc>=1.11.0",
    "pydata-sphinx-theme>=0.22.0",
    "sphinx>=9.1.0",
    "sphinx-gallery>=0.22.1",
    "sphinxcontrib-bibtex>=2.7.0",
]

[tool.uv]
# `uv sync` installs every group; none is ever published.
default-groups = ["test", "lint", "docs"]
# The series that wrote the lockfile; an older uv is refused.
required-version = ">=0.13"
# The version comes from git, so the installed package is rebuilt when the
# commit or the tags change.
cache-keys = [{ file = "pyproject.toml" }, { git = { commit = true, tags = true } }]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.sdist]
# The package's source; hatchling adds pyproject.toml, README.md and LICENSE.
only-include = ["src"]
```

- **Versions.** The lower bounds above are the releases current on
  2026-10-01. The plan's first task raises each to the release current when it
  runs (§17, item 1). `uv.lock` pins the exact versions, `ty`, `rumdl` and
  `typos` among them, and only `just upgrade-dependencies` moves them (§8),
  with `verify` passing before the refresh is committed. Nothing updates
  itself.
- **The runtime dependency.** `duckdb` is the only one, and the comment beside
  it is its written justification
  ([ADR 0005](../adr/0005-runtime-dependencies.md)). DuckDB 2.0.0 was due on
  2026-10-21; whether the floor moves to 2.x is decided in the plan's first
  task. The range of DuckDB versions the library supports, and how that range
  is tested, are the core spec's.
- **Checked** with uv 0.12.19, and the hatchling and hatch-vcs it resolved:
  `default-groups` installs all three groups; `required-version` and
  `cache-keys` are accepted; an untagged commit installs as
  `0.1.dev1+g<hash>`, and after `git tag v0.0.1` the next `uv run` reports
  `0.0.1`; a fresh clone's `pip install .` gives `0.0.1`, ships `py.typed` and
  reports `License-Expression: Apache-2.0`; the sdist holds `src/`,
  `pyproject.toml`, `README.md`, `LICENSE`, `.gitignore` and `PKG-INFO`, and
  not `tests/`.
- **Tags and releases.** Releases are semver on git tags, and the changelog is
  generated from the conventional commits between them; at 0.x, 0.y carries
  breaking changes and 0.y.z fixes, which is written down with the first
  release. PyPI comes first, and a conda-forge recipe follows at the first
  release; it changes nothing in development.

## 6. Python versions

The floor is 3.12 ([ADR 0007](../adr/0007-python-3-12-floor.md)):
`requires-python = ">=3.12"`, and `.python-version` holds `3.12`, so the daily
environment, `.venv`, runs on the floor and what passes at commit time runs on
every supported version. The matrix is 3.12, 3.13 and 3.14. It lives in two
places, the `matrix` variable of the `justfile` and the classifiers in
`pyproject.toml`, and a version joins or leaves both in one commit.

`just test-python-versions` runs each version in an environment of its own,
`.venvs/py<version>`, by setting `UV_PROJECT_ENVIRONMENT` and passing
`--python`. **Checked** with uv 0.12.19: with `.python-version` at 3.12,
`--python 3.13` builds a 3.13 environment in `.venvs/py3.13`, and `.venv` stays
on 3.12. uv fetches an interpreter it lacks on first use; the laptop already
has 3.12, 3.13 and 3.14 installed through uv.

The support policy, word for word, as `docs/architecture/python-versions.md`
carries it:

> sqlearn supports a Python version from the day Python releases it and
> DuckDB publishes wheels for it, until four years after its release or until
> DuckDB stops publishing wheels for it, whichever comes first. Today that is
> Python 3.12, 3.13 and 3.14; 3.15 joins when DuckDB publishes wheels for it.

The page then gives the reasons: four years is what the scientific-Python
projects do, though SPEC 0 says three; 3.12 is what the enterprise
long-term-support distributions ship; and daily work runs on the floor, so that
what passes at commit time runs on every supported version, while the matrix at
`verify` covers the newer ones.

## 7. Tool configuration

Every tool's settings live in `pyproject.toml`. The files that must sit at the
root are §7.8.

### 7.1 ruff

```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = [
    "E", "W",           # pycodestyle
    "F",                # pyflakes
    "I",                # import order, which the formatter leaves alone
    "B",                # likely bugs
    "BLE",              # `except Exception` needs a noqa and a reason
    "UP",               # the floor's syntax
    "SIM", "C4", "PIE", # simpler equivalents
    "PT",               # pytest's idioms
    "RUF",              # ruff's own, RUF100 among them: no stale noqa
    "N",                # naming
    "PYI",              # typing hygiene, which ty's guide pairs with ANN
    "T20",              # no print in the library
    "D",                # docstrings, on the numpy convention
    "ANN",              # every parameter and return annotated, ANN401 included
]
# A composite assertion with a message of its own reads as well as two.
ignore = ["PT018"]

[tool.ruff.lint.pydocstyle]
convention = "numpy"

[tool.ruff.lint.per-file-ignores]
# Tests: no annotations, and a docstring on every test, its form left free.
"tests/**" = ["ANN", "D2", "D3", "D4"]
# Gallery scripts: a reStructuredText title for a docstring, imports between
# text blocks, and output printed for the reader.
"examples/**" = ["ANN", "D", "E402", "T20"]
"docs/**" = ["ANN", "D"]

[tool.ruff.format]
docstring-code-format = true
```

- **The floor.** No `target-version`: ruff reads it from `requires-python`.
  **Checked** with ruff 0.16.9: `--show-settings` reports 3.12.
- **`ANN` on `src/` only**, `ANN401` included: an `Any` carries a `noqa` and its
  reason. ty is silent on an unannotated `def`, so these rules require an
  annotation on every parameter and return, at commit time. `validation/` and
  `benchmarks/` get their lines when their parts create them.
- **Tests' lighter rules:** no `ANN`, no numpydoc validation, and the
  missing-docstring rules (`D1`) on with the format rules (`D2` to `D4`) off.
- **`N`** would flag scikit-learn's `X` for the feature matrix (`N803`,
  `N806`). No code uses it yet; if the core spec adopts the convention, it adds
  the exception with its reason.
- **`docstring-code-format`** formats the code in docstring examples.

### 7.2 ty

```toml
[tool.ty.src]
include = ["src", "tests", "examples", "docs"]

[tool.ty.rules]
# ty's own approximation of a strict mode.
missing-type-argument = "error"
dynamic-function-decorator-return = "error"
unsound-return-statement = "error"
possibly-unresolved-reference = "warn"

[tool.ty.terminal]
# A warning fails the run, whatever ty's default becomes.
error-on-warning = true
```

- ty checks the bodies of unannotated functions, so it covers the tests without
  asking them for annotations.
- **Checked** with ty 0.0.84: the keys and rule names are accepted, and
  `import sqlearn` resolves from `src/` with no install. A run with one warning
  exits 1 by default; the explicit `true` pins the behaviour.
- **To verify in the plan**: that ty skips the gitignored copies the docs build
  writes under `docs/`, and that the rule names still exist at the locked
  version (ty is pre-1.0 and renames rules).
- **Re-evaluated at the core spec**, on real code: ty's stable release, and
  `pyrefly`.

### 7.3 mypy

```toml
[tool.mypy]
strict = true
python_version = "3.12"
files = ["src"]
warn_unreachable = true
```

- `src/` only: the tests carry no annotations by rule, and strict mypy would
  demand them. Where mypy and ty disagree about `src/`, mypy's word is final.
- **Checked** with mypy 2.3.1: the table is accepted, the package of §4.2
  passes, and an unannotated function fails with `no-untyped-def`.
- Whether `duckdb` gives mypy and ty anything to read is §17.

### 7.4 pytest and coverage

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = [
    "-q",
    "--strict-markers",
    "--strict-config",
    "--import-mode=importlib",
    "-m", "not slow",
]
markers = ["slow: the larger-than-memory tier; test-all and test-python-versions run it"]
xfail_strict = true
# A warning is an error: a deprecation is found the day it appears, not at the next major.
filterwarnings = ["error"]

[tool.coverage.run]
source_pkgs = ["sqlearn"]
branch = true

[tool.coverage.report]
show_missing = true
skip_empty = true
# No fail_under: the core spec sets the floor, measured on the full suite.
```

- **Checked** with pytest 9.1.1: the table passes `--strict-config`; a plain
  run deselects the `slow` test; `-m ""` on the command line runs both, and
  `-m slow` runs the slow one alone.
- **To verify in the plan**: that a bare `--cov` takes its source from
  `[tool.coverage.run]`, and that coverage raises no warning that
  `filterwarnings` would turn into an error.

### 7.5 numpydoc validation

```toml
[tool.numpydoc_validation]
# Every check but the extended summary and See Also, which not every object needs.
checks = ["all", "ES01", "SA01"]
# Private names are not validated.
exclude = ['\._']
```

- `EX01` stays on: every public object has an Examples section, and the docs
  build runs it as a doctest. The core spec may switch a check off, with its
  reason.
- **Checked** with numpydoc 1.11.0: `numpydoc lint` reads the table; the
  package of §4.2 passes; an undocumented function fails with `GL08`, exit 1.
  `numpydoc lint` takes files, not folders, so the recipe hands it every `.py`
  file under `src/`.

### 7.6 rumdl

```toml
[tool.rumdl]
# MD013 alone: prose wraps at 80 columns. Another rule joins with its reason.
enable = ["MD013"]

[tool.rumdl.MD013]
line-length = 80
code-blocks = false
tables = false
# Block quotes hold text quoted as found, so they are left alone.
blockquotes = false
# `rumdl fmt` rewraps a paragraph holding a line over the limit. `reflow-mode`
# stays unset: an invalid value silently resets the whole rule to its defaults.
reflow = true
```

- **Checked** with rumdl 0.2.78: it reads `[tool.rumdl]` from
  `pyproject.toml`, and it skips front matter, so the long `summary:` lines
  mdindex writes pass.
- **Reflow.** In its default mode it acts only where a line is over 80
  columns, and then refills the whole paragraph or list item holding that
  line; a paragraph of short lines is left alone. It never touches fenced
  blocks (a `{toctree}` fence among them), tables, block quotes, front matter,
  link reference definitions, a line holding only a URL, an HTML block's
  lines, or the line under the disable comment. It never wraps a heading,
  which `check` reports and `fmt` leaves: `fmt` exits 0 while leaving every
  finding it cannot fix, so `check` stays the gate. An invalid `reflow-mode`
  value silently resets all of MD013 to its defaults and exits 0, so
  `reflow-mode` is never set, and the plan reads `blockquotes` and `reflow`
  back from `rumdl config` as `[from pyproject.toml]` (§17).
- **Why MD013 alone.** With rumdl's defaults (every rule on) a Markdown tree
  like this one gives findings by the hundred, most of them style choices
  nobody made. A rule joins when there is a reason for it.
- **A line that cannot wrap**, and sits in no fenced block, table or block
  quote, gets `<!-- markdownlint-disable-next-line MD013 -->` on the line above
  it, the form rumdl and markdownlint both read.
- rumdl caches in `.rumdl_cache/`, which `.gitignore` lists.

### 7.7 typos

```toml
[tool.typos.files]
# Hidden folders are read, so the hooks and Claude's settings are checked;
# git's objects and the lockfile are not.
ignore-hidden = false
extend-exclude = [".git/", "uv.lock", ".codegraph/"]

[tool.typos.default]
# British prose and American identifiers both pass at `en`.
locale = "en"

[tool.typos.default.extend-words]
# A word typos mistakes for a misspelling goes here once, mapped to itself.
```

- **Checked** with typos 1.50.3: it reads `[tool.typos]` from
  `pyproject.toml`. With hidden folders read and `.git/` not excluded, it reads
  git's object files and reports noise, which is why `.git/` is listed.
- The recipe never passes `--write-changes`: typos reports and never rewrites.
- typos knows misspellings, not words, so identifiers never fire
  ([ADR 0010](../adr/0010-british-prose-american-identifiers.md)). codespell
  joins at `verify` only if typos ever lets real typos through.

### 7.8 The files that sit at the root

**`.python-version`** holds `3.12`.

**`.editorconfig`**, for the files no formatter owns:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 4
insert_final_newline = true
trim_trailing_whitespace = true

[*.{md,json,mjs,yml,yaml,cff,bib,sh}]
indent_size = 2

[.githooks/*]
indent_size = 2

[*.md]
max_line_length = 80

[*.py]
max_line_length = 88
```

**`.gitattributes`**:

```text
# Every text file is stored and checked out with LF line endings.
* text=auto eol=lf
# Sphinx inventories are zlib data: never converted, never diffed as text.
*.inv binary
```

**`.gitignore`** keeps its lines and gains:

```text
# What the build writes: the package, the site, and the pages it generates
dist/
docs/_build/
docs/examples/
docs/reference/generated/
docs/_static/mathjax/
# The test matrix's environments, one per Python version
.venvs/
# Tool caches and reports
.ruff_cache/
.mypy_cache/
.rumdl_cache/
.coverage
.coverage.*
htmlcov/
# Notebooks are generated; lessons are stored as text
*.ipynb
# Worktrees made inside the repository
.claude/worktrees/
.worktrees/
```

`docs/examples/` and `docs/reference/generated/` are what the build writes into
the source tree; `docs/_static/mathjax/` is where `fetch-mathjax` writes
(§11.3). Claude Code creates its worktrees under `.claude/worktrees/`; the
`using-git-worktrees` skill falls back on `.worktrees/`.

## 8. The justfile

Small recipes, one tool each, and composites that stack them: `check` on every
commit, `verify` at every review, merge and release, with more added as the
work needs them ([ADR 0008](../adr/0008-just-task-runner.md)). The pre-commit
hook runs a recipe of its own, `pre-commit`, so what runs on every commit
changes in the `justfile`, never in the hook (§9). The foundation's set:

| Recipe | What it runs | Built |
|---|---|---|
| `default` | `just --list`, so that a bare `just` lists the recipes | now |
| `setup` | `git config core.hooksPath .githooks`, then `uv sync --locked`: run once per clone (§9, §10) | now |
| `fmt-python` | `ruff check --fix-only`, then `ruff format`: the safe fixes and the formatting. `--fix-only` exits 0 whatever it leaves, so `fmt` goes on to the Markdown and `check` refuses the rest | now |
| `fmt-markdown` | `rumdl fmt .`: wraps the Markdown prose at 80 columns (§7.6) | now |
| `fmt` | `fmt-python`, then `fmt-markdown`: run before every commit. With its two parts, the only recipes that edit files | now |
| `lint-python` | `ruff check` and `ruff format --check` | now |
| `check-types` | `ty check` | now |
| `check-types-mypy` | `mypy`: strict, over `src/` | now |
| `lint-markdown` | `rumdl check .` | now |
| `check-spelling` | `typos` | now |
| `check-lockfile` | `uv lock --check`: `uv.lock` still matches `pyproject.toml` | now |
| `test` | the fast tier: pytest over `tests/` except `tests/githooks/`, `slow` deselected, coverage reported | now |
| `test-hooks` | pytest over `tests/githooks/` | now |
| `test-all` | every test, both tiers and the hooks, on the daily Python, coverage reported | now |
| `test-python-versions` | the package's tests, both tiers, once per version in `matrix`, each in `.venvs/py<version>` | now |
| `check-docstrings` | `numpydoc lint` over every `.py` file under `src/` | now |
| `fetch-mathjax` | the pinned MathJax into `docs/_static/mathjax/`, unless it is there (§11.3) | now |
| `build-docs` | `fetch-mathjax`, then `sphinx-build` twice: the HTML with warnings as errors, then the doctests | now |
| `fetch-inventories` | Python's and DuckDB's `objects.inv` into `docs/_inventories/` (§11.3) | now |
| `build-package` | `uv build`: the sdist and the wheel into `dist/` | now |
| `upgrade-dependencies` | `uv lock --upgrade`, `fetch-inventories`, then `verify`; committing is the caller's | now |
| `clean` | removes the build's output, the matrix's environments and the tools' caches §7.8 lists; never `.venv/` or a worktree | now |
| `check` | `lint-python`, `check-types`, `lint-markdown`, `check-spelling` | now |
| `pre-commit` | what the pre-commit hook runs: `check`, then `check-lockfile` | now |
| `verify` | `check`, `check-types-mypy`, `test-python-versions`, `test-hooks`, `check-docstrings`, `build-docs` | now |
| `release X.Y.Z` | `verify`, the sdist and the wheel, the wheel installed clean and tested, the tag, the push | first release |
| `docs-deploy` | publishes the built site | hosting decision |
| `validate` | 3.8's runners, writing `validation/results/` | 3.8 |

- **How each recipe runs.** The shell is `bash -euo pipefail`. Every tool runs
  through `uv run --locked`, so a lockfile that no longer matches
  `pyproject.toml` fails the recipe instead of drifting; `setup`,
  `check-lockfile`, `build-package` and `upgrade-dependencies` call `uv`
  itself. The comment above a recipe is its `just --list` description, and
  `[group]` attributes gather the recipes under headings. **Checked** with just
  1.58.0: comments and groups show in `just --list`, and a composite stops at
  the first recipe that fails and names it:

  ```text
  error: recipe `lint-python` failed on line 15 with exit code 1
  ```

- **Why `check-lockfile`.** Under the hook, `uv run --locked` runs with
  `UV_NO_SYNC` set (§9, step 3) and then no longer compares the lockfile with
  `pyproject.toml`, so `pre-commit` makes the comparison itself, once, after
  `check`. **Checked** with uv 0.12.19: `uv lock --check` exits 0 with the lock
  matching and 1 with it outdated, in tens of milliseconds, offline included.
- **Why the hook tests have a recipe of their own.** They make real commits in
  scratch repositories and run the real commitlint, which takes seconds per
  test. They test the hooks, not the package, and do not depend on the Python
  version, so `verify` runs them once rather than once per version. A change
  to `.githooks/` or `commitlint.config.mjs` runs `just test-hooks` before its
  commit; `docs/architecture/testing.md` says so.
- **No coverage floor.** `test` and `test-all` report coverage; nothing
  enforces a floor until the core spec sets one, and from then on the floor
  only ratchets up.
- **Why three recipes wait.** A recipe that does nothing yet would still be
  listed, and invite a call.
- `docs/architecture/setup.md` lists the recipes by group, as `just --list`
  shows them.

The one-tool recipes carry long, literal names that say what each does. The
five names every agent is told (`fmt`, `check`, `test`, `verify` and
`pre-commit`) stay short and fixed, since `CLAUDE.md` and the hook carry them.
The composition of `check` and `verify` is reviewed once the foundation has
landed and the recipes have real timings.

## 9. The pre-commit hook

`.githooks/pre-commit` is a bash script, committed executable. `just setup`
points `core.hooksPath` at `.githooks` in a clone, and nothing else installs
it; `README.md` and `docs/architecture/setup.md` say to run it once after
cloning. Git runs the hook as soon as it is executable and the path is set.
`git commit --no-verify` would skip it, and `CLAUDE.md` forbids that.

What it does, in order:

1. **It finds `just`** on `PATH`. Where it is not found the commit is refused,
   and the refusal gives the cure: `brew install just uv`.
2. **It exports the commit's files.** It writes the index git hands it (HEAD
   plus the staged paths) to a temporary directory with
   `git checkout-index -a --prefix=`, and deletes the directory when it exits.
   **To verify in the plan**: that a partial commit (`git commit -- <paths>`)
   hands the hook a temporary index through `GIT_INDEX_FILE`; and what the
   export costs in time.
3. **It runs `just pre-commit`** from the root of the exported copy, against
   the repository's real environment: `UV_PROJECT_ENVIRONMENT` points at the
   repository's `.venv` and `UV_NO_SYNC` is set, so nothing is installed from
   the copy. A failure refuses the commit: `just` has already named the recipe
   that failed, and the hook adds that it can be run alone, the cures (`just
   fmt` for the formatting, `uv lock` for the lockfile, `uv sync` for a tool
   the environment lacks), and that the checks read the files going into the
   commit, not the files on disk.
4. **It passes**: exit 0, and nothing printed.

The checks read the files going into the commit and nothing else. Another
agent's unfinished file in the same working tree is not in the commit, so it
refuses nothing. A failure comes from what the commit changes and is the
committer's to put right: `just fmt`, `uv lock`, the fix, or the tool's own
suppression on the line, with the reason beside it. The exception is a failure
HEAD already carries: it refuses every commit on its branch but the one that
mends it.

The hook runs no tests, so "seconds" stays true as the suite grows. The cost:
between reviews a branch can carry a red fast test, which the reviewer's `just
verify` catches. `just test` is every agent's to run before a commit.

**It lands after the tree passes** `just pre-commit` and `just test` (§13).
Before that, it would refuse the plan's own commits.

**Its tests**, in `tests/githooks/test_pre_commit.py`: real commits in scratch
repositories, each carrying a copy of the hook at its own
`.githooks/pre-commit` with `core.hooksPath` set, and a stand-in `just` first on
`PATH` that notes its arguments and exits as it is told. They cover: the recipe
passes and the commit lands, the stand-in having seen `pre-commit` as its
argument; the recipe fails and the commit is refused; a commit lands when an
unstaged file in the working tree would fail the checks, since only the
exported files are read; no `just`, and the refusal gives the cure; and the
executable bit is committed.

## 10. The commit-message hook

Commit messages follow Conventional Commits, checked by commitlint against
`commitlint.config.mjs` at the root. That file is the rules and the one place
they are kept; how to write a good message is the `commit-message` skill's
business. commitlint is installed globally (`brew install commitlint`), and
the repository holds no `package.json` and no `node_modules`.

### 10.1 commitlint.config.mjs

Carried over from the earlier attempt, with its scopes reset for this
repository:

```js
// commitlint.config.mjs - this repository's commit conventions, as commitlint
// checks them. The git hook .githooks/commit-msg hands every commit message to
// commitlint with this file, and refuses the commit on any rule at level 2. A
// rule at level 1 is printed as a warning and never refuses.
//
// This file IS the conventions, and the one place they are kept. Change a rule
// here and the next commit is held to it.
//
// It has no `extends` and names no package, on purpose. commitlint is installed
// globally and this repository holds no package.json and no node_modules, so
// anything named here would have to be found there and would not be. Every rule
// below is one commitlint ships with. A rule of this repository's own can join
// later, in this same file, as a function under `plugins`.
//
// Levels: 0 off, 1 warning, 2 error. Rules: https://commitlint.js.org/reference/rules

export default {
  // The last line of a refusal. A path and not an address: it is printed for
  // whoever was refused to open, and nothing fetches it.
  helpUrl: 'commitlint.config.mjs at the repository root holds the rules',

  // Off, so that a `fixup!`, `squash!` or `amend!` subject is held to the rules
  // like any other. Left on, commitlint passes those subjects unread, and merge
  // and revert subjects with them.
  defaultIgnores: false,

  // How a header is read. Written out because the parser commitlint falls back
  // on has no `!` in its pattern, and reads `feat(auth)!: subject` as a header
  // with no type and no subject at all. These are the options the
  // conventionalcommits preset uses, given here because a preset named as a
  // package is something a global install cannot find.
  parserPreset: {
    parserOpts: {
      headerPattern: /^(\w*)(?:\((.*)\))?!?: (.*)$/,
      breakingHeaderPattern: /^(\w*)(?:\((.*)\))?!: (.*)$/,
      headerCorrespondence: ['type', 'scope', 'subject'],
      noteKeywords: ['BREAKING CHANGE', 'BREAKING-CHANGE'],
    },
  },

  rules: {
    // --- the header: `type(scope): subject` --------------------------------
    // A header that is not of that shape at all parses as no type and no
    // subject, and is refused by the two `-empty` rules.
    'type-empty': [2, 'never'],
    'subject-empty': [2, 'never'],
    'type-case': [2, 'always', 'lower-case'],
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'perf', 'refactor', 'build', 'test', 'ci', 'docs',
       'style', 'chore', 'revert'],
    ],
    'header-max-length': [2, 'always', 72],
    'header-trim': [2, 'always'],
    'subject-full-stop': [2, 'never', '.'],
    // A warning: a subject may open with a proper noun, an acronym or a file
    // name such as CLAUDE.md, and this rule cannot tell those from a sentence
    // that was given a capital.
    'subject-case': [
      1,
      'never',
      ['sentence-case', 'start-case', 'pascal-case', 'upper-case'],
    ],

    // --- the scope: optional, and an open list -----------------------------
    // The scopes in use, kept here so that they are in one place. The list is
    // open: this is a warning, so a scope that is not on it is pointed out and
    // the commit goes through. Reuse one before coining another, and add the
    // new one here when you do. No scope at all always passes.
    'scope-enum': [
      1,
      'always',
      [
        // .githooks/ and this file
        'hooks',
        // the docs build: conf.py, the theme, MathJax, the inventories
        'site',
        // pyproject.toml's dependencies and uv.lock
        'deps',
      ],
    ],
    'scope-case': [2, 'always', 'lower-case'],
    'scope-max-length': [2, 'always', 24],

    // --- the body and the footer -------------------------------------------
    'body-leading-blank': [2, 'always'],
    'body-max-line-length': [1, 'always', 72],
    'footer-leading-blank': [1, 'always'],
    // `!` in the header and a `BREAKING CHANGE:` footer: both, or neither.
    'breaking-change-exclamation-mark': [2, 'always'],
  },
};
```

### 10.2 .githooks/commit-msg

A bash script, committed executable, installed with the pre-commit hook by
`just setup`. What it does, in order:

1. **Replayed messages pass.** With a merge, revert, cherry-pick or rebase in
   progress (`MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `rebase-merge`,
   `rebase-apply` in the git directory) it exits 0: a replayed message was
   accepted when it was written, git's own revert subject is not
   `type: subject`, and a refusal strands the operation half way.
2. **It cleans the message.** After an editor git hands over the raw file:
   comment lines, and under `-v` the whole diff below a scissors line. Both are
   stripped before checking.
3. **An empty message is refused** by the hook itself, since commitlint handed
   nothing prints its usage and exits as if it had crashed.
4. **It finds commitlint** on `PATH`, then in npm's global prefix. Where it is
   not found the commit is refused, saying the message has not been looked at
   and giving the cure: `brew install commitlint`.
5. **It finds the rules** from its own path (`.githooks/../commitlint.config.mjs`),
   so a commit typed from a subfolder or a worktree finds them. A missing file
   refuses the commit.
6. **It runs commitlint with `--strict`**, for its exit codes: 0 is a pass, 2 a
   pass with warnings, 3 a refusal, and anything else is commitlint failing to
   run, never a verdict on the message. The four get different words, since
   they have different cures:
   - 0: exit 0, nothing printed;
   - 2: the warnings, then "accepted: those are warnings, and a warning never
     refuses a commit";
   - 3: the findings, then "refused: the message does not follow the commit
     conventions", with how to read the ✖ and ⚠ lines. One exception: output
     holding `[empty-rules]` means the rules file is at fault, and is reported
     as a tooling failure;
   - anything else: "refused: commitlint could not check this message, so
     nothing has judged it", with what was run (commitlint's path and version,
     node's version, the rules' path), and that rewording will not help.
7. commitlint's own directory goes first on `PATH` for the run, since an npm
   install starts with `env node` and node sits beside it.

**Its tests**, in `tests/githooks/test_commit_msg.py`: real commits in scratch
repositories carrying copies of the hook and the rules, with the real
commitlint, skipped with a reason where commitlint is not installed. They
cover: a good message lands; each level-2 rule refuses; a warning-only message
lands with its warnings shown; `!` without the footer is refused; an empty
message is refused; a merge with git's own message lands; a `-v` commit's
scissors section is ignored; no commitlint, and the refusal gives the cure; a
missing rules file refuses; a rules file that fails to load is reported as a
tooling failure, not a bad message; and the executable bit is committed.

## 11. The documentation site

Sphinx with pydata-sphinx-theme; autosummary and numpydoc for the reference;
sphinx-gallery for executed examples; MyST-Parser and MyST-NB, so that the guide
and the curriculum are written in Markdown; intersphinx to Python's and DuckDB's
documentation; the theme's version switcher, over one directory per version;
and math bundled with the site
([ADR 0009](../adr/0009-sphinx-documentation-site.md)). It is the stack of
scikit-learn and pandas, the only candidate that met all the requirements, and
the one whose executed examples link back to the API pages that use them. Its
costs are time and plumbing: the setup itself, a docs build that imports the
package, one external inventory URL (§11.3), and a written rule for where
Markdown ends and reStructuredText begins (§11.5).

### 11.1 Sections and URLs

| Navigation label | Built from | URL |
|---|---|---|
| Guide | `docs/guide/` | `guide/` |
| Reference | `docs/reference/`; generated pages in `docs/reference/generated/` | `reference/` |
| Examples | `examples/` at the root, generated into `docs/examples/` | `examples/` |
| Learn | `docs/learn/`, with `beginner/`, `intermediate/` and `advanced/` | `learn/`, `learn/beginner/`, `learn/intermediate/`, `learn/advanced/` |
| Validation | `docs/validation/` | `validation/` |
| Benchmarks | `docs/benchmarks/` | `benchmarks/` |
| Development | `docs/architecture/`, with the decision records from `docs/adr/` | `architecture/`, `adr/` |

- URLs are relative to the root of one version's build; the host and the
  version prefix come with the hosting decision and the first release.
- The builder is Sphinx's `html`. A section's URL is its folder, served by its
  `index.html`, which gives the addresses
  [ADR 0011](../adr/0011-curriculum-levels.md) fixes, such as
  `/learn/beginner/`; any other page ends in `.html`.
- The Development section's index, `architecture/index.md`, lists its pages
  and then `../adr/index`, so the decision records sit in the section while
  keeping the `adr/` URL. Renaming either folder later would move every URL in
  it, so neither is renamed after the first deploy.
- The root `toctree` lists the seven indexes in this order. The theme shows
  five entries before a "More" menu by default, and
  `header_links_before_dropdown = 7` shows all seven. **Checked** with
  pydata-sphinx-theme 0.22.0: seven links, in order, and no "More".
- The site is in English only.

### 11.2 conf.py

```python
"""Sphinx configuration for the sqlearn site."""

import sqlearn

project = "sqlearn"
author = "Tomas Pecukevicius"
copyright = "2026, Tomas Pecukevicius"
release = version = sqlearn.__version__
language = "en"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "numpydoc",
    "sphinx_gallery.gen_gallery",
    "myst_nb",
    "sphinxcontrib.bibtex",
]

# Every cross-reference resolves, from the first build.
nitpicky = True
# In docs/ but not on the site: specs, plans, open questions and the agents'
# configuration; the folders' one-line READMEs; the build output; and
# notebooks, which are generated, since lessons are stored as text.
exclude_patterns = [
    "_build",
    "specs",
    "plans",
    "questions",
    "agents",
    "**/README.md",
    "**.ipynb",
]

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_theme_options = {
    "header_links_before_dropdown": 7,
    "switcher": {"json_url": "_static/switcher.json", "version_match": "dev"},
    "check_switcher": False,
    "show_version_warning_banner": False,
}

autosummary_generate = True
numpydoc_show_class_members = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", "_inventories/python.inv"),
    "duckdb": (
        "https://duckdb.org/docs/current/clients/python/reference/",
        "_inventories/duckdb.inv",
    ),
}

# mathjax_path and mathjax4_config point at the local copy, §11.3.

sphinx_gallery_conf = {
    "examples_dirs": "../examples",
    "gallery_dirs": "examples",
    "filename_pattern": ".",
    "doc_module": ("sqlearn",),
    "backreferences_dir": "reference/generated/backreferences",
    "image_scrapers": (),
    "reset_modules": (),
    "write_computation_times": False,
}

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence"]
nb_execution_mode = "cache"
nb_execution_raise_on_error = True

bibtex_bibfiles = ["references.bib"]
```

- **Checked** in a scratch build with these settings, less the MathJax lines
  and Python's inventory (Sphinx 9.1.0, pydata-sphinx-theme 0.22.0, numpydoc
  1.11.0, sphinx-gallery 0.22.1, myst-nb 1.4.0, sphinxcontrib-bibtex 2.7.0,
  ipykernel 7.4.0): `sphinx-build -W --keep-going -n -b html` exits 0;
  sphinx-gallery ran a placeholder under a `GALLERY_HEADER.rst`; MyST-NB
  executed a text notebook with `myst_nb` alone among the extensions, since it
  brings MyST-Parser; a `{class}` reference to `duckdb.DuckDBPyConnection`
  resolved from the local inventory, nitpicky; an excluded folder and the empty
  bibliography raised no warning; and `-b doctest` ran the package's Examples,
  exiting 1 when the expected output was wrong.
- **To verify in the plan**: that the front matter mdindex writes (`type`,
  `tags`, `summary`, `related`, `mdindex`) raises no warning in MyST under
  `-W`, on the ADRs and the architecture pages, which are on the site.
- **Three gallery settings are not optional.** Unless `image_scrapers` and
  `reset_modules` are empty, sphinx-gallery imports matplotlib, and the build
  fails without it (**checked**). The first example that draws adds matplotlib
  to the `docs` group and its scraper back. Unless `write_computation_times`
  is `False`, sphinx-gallery writes two pages of execution times that load
  jQuery, DataTables and Bootstrap from three content delivery networks
  (**checked**), which the offline rule forbids
  ([ADR 0006](../adr/0006-local-and-offline.md)).
- **Warnings as errors and nitpicky from the first build.** `nitpicky` is set
  in `conf.py`, so every build is nitpicky. The `build-docs` recipe runs
  `sphinx-build -W --keep-going -b html docs docs/_build/html`, then
  `-b doctest` into `docs/_build/doctest`. **To verify in the plan**: that the
  doctest pass reuses sphinx-gallery's and MyST-NB's caches instead of running
  the examples and notebooks again.
- **Doctests run in the docs build**, from the docstrings autosummary brings
  in, and pytest does not collect them (no `--doctest-modules`), so each runs
  once, at `verify`.
- **The version switcher is prepared, not shown.** Its configuration is in
  place, and `docs/_static/switcher.json` holds one entry, `dev`. The entry
  needs the site's absolute address, which the hosting decision gives; until
  then a switcher in the navigation bar would offer a broken link, so it stays
  out. It arrives with docs versioning, at the first release.
- **One bibliography.** `references.bib` holds a comment saying what goes in
  it (every source a page cites, from the classes the overview's 3.8 allows)
  and no entry. `bibliography.md` holds the site's one `{bibliography}`
  directive, with `:all:`, and front matter `orphan: true`, so it sits in no
  `toctree` and adds no entry to the navigation bar; its URL is
  `bibliography.html`, and every citation links there.
- **`docs/architecture/writing.md` proves two pipelines.** It is a MyST-NB text
  notebook with one executed cell, which prints `sqlearn.__version__`, and one
  formula, so the build executes a notebook and renders math from the local
  MathJax. `ipykernel` is in the `docs` group to run it.

### 11.3 Offline: MathJax and the inventories

The site reads offline, its formulas included
([ADR 0006](../adr/0006-local-and-offline.md)).

**MathJax.** Sphinx 9.1.0 loads MathJax 4 from a CDN unless told otherwise
(**checked** in its source). The `fetch-mathjax` recipe fetches from the npm
registry, at versions and sha512 checksums pinned in the `justfile`, `mathjax`
4.1.3 (Apache-2.0) and the font package it depends on,
`@mathjax/mathjax-newcm-font` 4.1.3 (Apache-2.0), and unpacks what the CHTML
output needs into `docs/_static/mathjax/`, which git ignores. `conf.py` points
`mathjax_path` at that copy and sets `mathjax4_config` so that the fonts load
from it too. **Checked**: `tex-chtml.js` in `mathjax` 4.1.3 names
`cdn.jsdelivr.net` for its font package and for `speech-rule-engine`, and the
font package unpacks to 49 MB, so the recipe copies only what the CHTML output
loads. **To verify in the plan**: which files that is, the configuration, and
what MathJax's speech feature loads. The acceptance test is the `grep` of §2,
criterion 3, and a formula that renders with the network off. Should MathJax 4
need something from elsewhere whatever its configuration, MathJax 3.2.2
(Apache-2.0), which Sphinx still configures through `mathjax3_config`, is the
fallback (**to verify in the plan** that its package carries its own fonts).

**Inventories.** intersphinx reads Python's and DuckDB's `objects.inv` from
`docs/_inventories/`, committed. `just fetch-inventories` refreshes them, and
`just upgrade-dependencies` runs it. They are committed so the build works
offline, and because a nitpicky build with warnings as errors fails on a
reference it cannot resolve: `docs.python.org` answered 503 to every request
for a whole day in the earlier attempt. Both are zlib data, which
`.gitattributes` marks as binary. The links still point at the live
documentation. **Checked**: intersphinx loads an inventory from a local path
given as the mapping's second element.

### 11.4 The example gallery

`examples/` at the root holds the gallery's sources; sphinx-gallery generates
the Examples section from them into `docs/examples/`, which git ignores.
Examples are grouped in subfolders of `examples/` by library area, each with a
header file of its own, which sphinx-gallery renders as a titled section; the
foundation ships only the root header and the placeholder, and each area's part
creates its folder when its first example lands.

- `examples/GALLERY_HEADER.rst` is the text of the gallery's index, under the
  name sphinx-gallery has used for it since 0.17.
- `examples/show_version.py` is the placeholder that proves the pipeline:

  ```python
  """
  Show the installed version
  ==========================

  Import sqlearn and print the version it was installed as, which hatch-vcs
  read from the git tag the package was built from.
  """

  import sqlearn

  print(sqlearn.__version__)
  ```

- `filename_pattern = "."` runs every example at build, where by default only
  files named `plot*` run: an example the build does not run is one nobody
  knows still works.
- `doc_module` and `backreferences_dir` give each reference page the list of
  examples that use its object, the reason sphinx-gallery was chosen.

### 11.5 Where Markdown ends and reStructuredText begins

The rule, as `docs/architecture/writing.md` states it:

> Docstrings are reStructuredText, in numpydoc's format, because autosummary
> and numpydoc read them so. Every page written by hand in `docs/` is
> Markdown, as MyST: a chapter, a lesson, a page of this section. Two kinds of
> file are reStructuredText because the tool that reads them reads nothing
> else: the text blocks of a gallery example and the gallery's header, which
> sphinx-gallery reads, and the autosummary templates the reference will
> grow. A construct only reStructuredText has goes, inside a Markdown page,
> in an `{eval-rst}` block, as the reference index's `autosummary` does.
> Lessons are MyST-NB's Markdown notebooks, never `.ipynb` files.

**To verify in the plan**: whether sphinx-gallery can read MyST in an example's
text blocks. If it can, the rule loses that exception.

## 12. The tests the foundation ships

Each test has a one-line docstring saying what it checks and why; ruff's `D103`
holds them to it.

| Test | File | What it checks, and why |
|---|---|---|
| `test_the_package_imports` | `tests/src/sqlearn/test_init.py` | `sqlearn` imports from the environment uv built, which every other test of the package needs first |
| `test_the_version_is_a_string` | `tests/src/sqlearn/test_init.py` | `__version__` is a non-empty `str` equal to `importlib.metadata.version("sqlearn")`: the version hatch-vcs wrote from git, which pip and the docs report |
| `test_the_package_ships_py_typed` | `tests/src/sqlearn/test_init.py` | `py.typed` is in the package, without which users' type checkers ignore its annotations |
| `test_duckdb_answers_a_query` | `tests/test_environment.py` | `duckdb` imports and computes `sum(range)` over `range(1000)` as 499500: the one runtime dependency works in this environment |
| `test_duckdb_spills_a_query_larger_than_its_memory_limit` | `tests/test_environment.py` | marked `slow`; under `memory_limit = '64MB'`, grouping 20,000,000 generated rows into 10,000,000 keys raises `duckdb.OutOfMemoryException` with spilling off (`temp_directory = ''`) and returns 10,000,000 groups over 20,000,000 rows with spilling to `tmp_path`: DuckDB finishes work larger than its memory, which the library is built on |

The hook tests are §9 and §10.

- `tests/` mirrors the repository's root: the tests of anything sit at its path
  under `tests/`. `src/` stays in the mirror, so the package's tests are in
  `tests/src/sqlearn/`. A hidden folder loses its dot, since pytest skips
  hidden folders by default (`.*` is among the default `norecursedirs`), so
  the tests of `.githooks/` sit in `tests/githooks/`.
  `tests/test_environment.py` stays at the top of `tests/`, outside the mirror,
  because it tests the environment as a whole, not a file of the tree.
- **Checked** with duckdb 1.5.6: the slow test's query fails with
  `OutOfMemoryException` after 0.04 seconds with spilling off, and returns the
  right counts in about 1.5 seconds with spilling on. Should a later DuckDB fit
  it in memory, the test fails, and its sizes go up.
- A plain `uv run pytest` reports the slow test deselected; `just test-all`
  runs it.

## 13. Bringing today's files under the gates

Today the tree holds no Python, only Markdown: `CLAUDE.md` and everything under
`docs/`. The new gates read it, so the plan:

1. Runs `just fmt` once and commits the result on its own, as formatting only:
   `rumdl fmt .` rewraps the paragraphs that hold a line over 80 columns, and
   moves line breaks, no word.
2. Runs `just check` and puts right what `fmt` cannot: a heading over 80
   columns, a line that cannot wrap (the disable comment of §7.6), and any word
   typos flags (reworded, or added to `extend-words` if it is a real word).
3. Lands the pre-commit hook only after `just pre-commit` and `just test` pass
   on the tree (§9).

The files copied from the Matt Pocock templates in `docs/agents/` are formatted
like the rest; they are ours now.

## 14. Changes to CLAUDE.md

Written after the merge, from the `justfile` as it then is, as a new section
after "Commit conventions":

```markdown
## Checks

- **Once per clone, run `just setup`.** It installs the git hooks and syncs
  the environment.
- **Before every commit, `just check` and `just test` pass.** The pre-commit
  hook runs `just pre-commit` over the files going into the commit and refuses
  the commit when it fails; the commit-msg hook runs commitlint. `just test` is
  yours to run before you commit. Never `--no-verify`. Run `just fmt` before
  you commit: it wraps the Markdown at 80 columns and formats the Python, and
  its two parts are the only recipes that edit files.
- **Before you say any work is done, `just verify` passes**, and a reviewer's
  verdict says whether it ran and passed.
- **`just --list` names every recipe.** When a composite fails, `just` names
  the recipe that failed: run that one alone.
- **The conventions are in `docs/architecture/`**: the layout, the Python
  versions, how documentation and tests are written. Read the page for the
  work in hand.
```

## 15. Where the conventions are written

`CLAUDE.md` is read at every session start, so it carries the bullets of §14
and points at the rest.

| Convention | Where it is written |
|---|---|
| The recipes and their two rhythms, `just setup`, and `just fmt` before every commit | `CLAUDE.md` (§14); `docs/architecture/setup.md`, with setting up a laptop and what the two hooks do (§9, §10) |
| The project's English | one line in `CLAUDE.md`; the rest in `docs/architecture/writing.md`: typos at locale `en`, and its allow-list in `pyproject.toml` |
| The support policy | `docs/architecture/python-versions.md`, with the paragraph of §6 and its reasons; one line in `README.md` |
| The layout | `docs/architecture/layout.md`: the tree of §4.5 and its reasons, `.gitignore` included, `tests/` mirroring the root (§12), examples grouped by area (§11.4), and what arrives later (§4.4) |
| Markdown and reStructuredText | `docs/architecture/writing.md`: the rule of §11.5, math, text notebooks, and the line length, with what the formatter leaves as found and the disable comment for a line that cannot wrap (§7.6) |
| The tests' lighter rules | `docs/architecture/testing.md`: one docstring per test, no annotations and no numpydoc validation, the two tiers and the `slow` marker, the hook tests and their recipe, coverage reported and its floor to come |

`docs/architecture/index.md` is the Development section's index: its title, a
sentence on what the section holds, and the `toctree` of `overview`,
`workflow`, the five pages above, and `../adr/index`.

## 16. Out of scope

- **Product code.** No estimator, transformer, metric, data model or SQL,
  beyond the DuckDB queries of the environment tests.
- **CI.** No `.github/workflows/`, no GitHub Actions, nothing for GitHub Pages:
  none while the repository is private. Until then the hooks, the reviewer and
  `just verify` are the net, and Linux and Windows are a known gap. GitHub
  Actions comes when the repository is public, if it is free for public
  repositories, which is verified with the hosting decision.
- **Claude Code web sessions.** No bootstrap that installs `uv`, `just` and
  commitlint in a web container: work is on the laptop for now (§19). Added
  later, it would be a SessionStart hook in `.claude/settings.json` running
  `just setup` after installing the tools, and `releases.astral.sh` allowed in
  the web environment's network access so uv can fetch Python 3.13 and 3.14.
- **The first release's files.** No `NOTICE`, `CITATION.cff`, `CHANGELOG.md`
  or acknowledgement page. `LICENSE` arrives now.
- **What a public repository brings.** No CONTRIBUTING, code of conduct or
  issue templates, and no security scanning: they arrive when the repository is
  public. A CLA arrives before the first outside contribution
  ([ADR 0004](../adr/0004-apache-2-licence.md)).
- **A coverage floor.** Reported, not enforced; the core spec sets it.
- **Release automation.** No `release` recipe, no tag, no PyPI upload, no
  conda-forge recipe, no `release` skill.
- **Deploying and versioning the docs.** No `docs-deploy`, no version
  directories, no switcher in the navigation bar.
- **Validation and benchmarks.** No `validate` recipe, and no `validation/` or
  `benchmarks/` at the root.
- **Decisions taken later.** No `hypothesis` (3.2), no `pyrefly` and no
  benchmarks (the core spec decides both), no `uv` workspace (the
  applications).
- **Content.** Nothing in the seven sections beyond §4.3.
- **The recipe set's final shape.** It grows as the work needs it.

## 17. Checks the plan carries

These are checks, not builds. Each settles a fact before the plan builds on it.

1. **Current versions.** Every lower bound in §5 is raised to the release
   current when the plan runs, uv's `required-version` included, and the
   checks marked **checked** above are repeated at the locked versions. DuckDB
   2.x: whether it is out and whether the floor moves to it.
2. **rumdl and typos read `pyproject.toml`.** `uv run rumdl config` shows the
   settings as `[from pyproject.toml]`, `blockquotes` and `reflow` among them,
   since a setting rumdl could not read falls back to its default without a
   word; `uv run typos --dump-config -` shows `locale = "en"` and the
   exclusions.
3. **rumdl against markdownlint-cli2, once.** rumdl is young, so its findings
   are compared once with markdownlint's. Run markdownlint-cli2 from npm over
   the files rumdl reads, with MD013 alone at `line_length` 80, `code_blocks`
   and `tables` off, from a configuration file kept outside the repository, and
   rumdl with reflow off (`--config 'MD013.reflow = false'`), since reflow
   changes what `check` reports; a finding on a block-quote line is left out of
   both sides, since markdownlint cannot exempt block quotes and rumdl does.
   Compare the findings by file and line. The same findings: rumdl stays. Any
   divergence: markdownlint-cli2 takes over by the commitlint route (`brew
   install markdownlint-cli2`), the `lint-markdown` recipe calls it, and
   `fmt-markdown` goes, since markdownlint formats nothing.
4. **What `duckdb` gives the type checkers.** Whether the wheel at the locked
   version ships `py.typed` or `.pyi` stubs, and what ty reports on
   `tests/test_environment.py`. Typed: nothing to do. Untyped: the narrowest
   override that lets the foundation's gates pass, its reason in a comment,
   and the finding noted for the core spec, which brings the first
   `import duckdb` into `src/`.
5. **Python's inventory.** `objects.inv` fetched from `docs.python.org`.
6. **The offline MathJax** of §11.3.
7. **mdindex front matter under Sphinx** (§11.2).
8. **commitlint at the installed version** (21.2.4 today) loads
   `commitlint.config.mjs` and gives the exit codes §10.2 relies on.
9. **Nothing about GitHub Actions or Pages.** Both wait for the hosting
   decision.

The smaller points marked **to verify in the plan** are in §7.2, §7.4, §9,
§11.2, §11.3 and §11.5.

## 18. Decisions carried over

From the earlier attempt's questions to Tomas, decided 2026-10-01:

- **The per-commit gate.** The hook runs `just pre-commit` (`check`, then
  `check-lockfile`), over the commit's own files exported from the index, and
  no tests. A `check` failure is in the text of a file in the commit and is the
  committer's to put right; a test fails for reasons outside the commit, so
  tests run at `verify`, not in the hook. What the gate runs changes in the
  `justfile`, never in the hook.
- **The commit-message tool.** commitlint, the strongest rule engine of the
  candidates (commitizen, gitlint, commit-check and a checker of our own were
  compared and set aside): "simple and direct", in Tomas's words.

## 19. What changed from the earlier spec

Decided by Tomas on 2026-11-03, or following from this repository's setup:

| Earlier | Here | Why |
|---|---|---|
| Hooks in `.claude/hooks/git/`, installed by a session-start script | `.githooks/`, installed by `just setup` | Tomas's decision: simple, with no Claude-specific script |
| A web-session bootstrap (§10 there) installing uv, just and commitlint | Left out (§16) | Tomas's decision: laptop only for now |
| `commitlint.config.mjs` with the earlier engine's scopes | The same rules, scopes reset to `hooks`, `site`, `deps` | Tomas's decision to keep commitlint; the old scopes named parts that do not exist here |
| `commit-msg` refusing Claude Code's container identity | Dropped | it guarded web sessions, which are out of scope |
| `records/` for findings, and a hook exemption for records-only commits | GitHub Issues and `docs/questions/`; no exemption | the issue tracker in `docs/agents/` |
| `docs/architecture/decisions/` | `docs/adr/`, on the site at `adr/` | this repository's docs layout |
| `docs/superpowers/specs/`, `plans/` | `docs/specs/`, `docs/plans/` | this repository's docs layout |
| Copied superpowers skills, an orchestrator, `opus`/`sonnet` agents, a record-names hook, 162 hook tests, and their move under `tests/claude/` | The installed plugins; hook tests for the two new hooks only, in `tests/githooks/` | start lean; project agents only when [questions/agents-and-skills.md](../questions/agents-and-skills.md) decides |
| `.claude/` exclusions in ruff, ty, rumdl and typos | Removed | there is no copied code under `.claude/` |

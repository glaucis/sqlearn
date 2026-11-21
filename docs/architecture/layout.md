---
type: architecture
tags: [repository-layout, directory-structure, docs, tests, examples]
summary: "Describes the sqlearn repository's directory tree, why each top-level location exists, and how tests mirror the source layout."
related: [docs/specs/foundation.md, docs/adr/0053-sqlearn-ships-no-datasets.md, docs/adr/0025-results-stored-as-data-in-mirrored-folders.md, examples/GALLERY_HEADER.rst, examples/show_version.py]
mdindex: [type=4ca303, tags=a1a8d0, summary=f64b62, related=f2cd85]
---
# The repository's layout

What is where, and why. [The foundation spec](../specs/foundation.md) holds
the full tree and the reasons.

## The tree

```text
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
                         3.8, and their committed results; mirrors
                         src/sqlearn/; imported by tests/, never
                         installed
  benchmarks/            the benchmark suite and its committed results;
                         mirrors src/sqlearn/
  engine/                sqlearn's C++ library, its kernels and its
                         bindings (ADR 0060), and sqlearn's DuckDB
                         build (ADR 0061), from the engine's Phase 1
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
```

`.github/workflows/` arrives with the native engine's Phase 1; the
repository is public (ADR 0062).
`validation/` and `benchmarks/` at the root, and the first release's files,
arrive with their parts.

## Why

- **`src/`.** The package cannot be imported from the checkout by accident, so
  the tests run against what users install.
- **`docs/` holds everything the site shows.** One site, one build, one
  deploy.
- **`examples/`, `validation/` and `benchmarks/` at the root.** They are code a
  user reads, found without opening `docs/`, as scikit-learn keeps its
  examples.

- **`devdata/` at the root.** Datasets for developing sqlearn: tests,
  validation and benchmarks use them. It sits outside `src/`, so neither the
  wheel nor the sdist holds it, and the package never imports it
  ([ADR 0053](../adr/0053-sqlearn-ships-no-datasets.md)).

## What never enters the repository

Outputs (executed notebooks, the gallery's figures,
rendered HTML, all made by the build, with lessons stored as text), and the
built site in the history. `.gitignore` lists what the build writes: the
package, the site, the generated pages, the matrix environments and the tool
caches.

## Tests mirror the root

The tests of anything sit at its path under `tests/`. `src/` stays in the
mirror, so the package's tests are in `tests/src/sqlearn/`. A hidden folder
loses its dot, since pytest skips hidden folders by default: the tests of
`.githooks/` sit in `tests/githooks/`. `tests/test_environment.py` stays at the
top of `tests/`, outside the mirror, because it tests the environment as a
whole, not a file of the tree. Tests need no `conftest.py` and no
`__init__.py`, since pytest imports them in `importlib` mode.

## Examples by area

`examples/` holds the gallery's sources, and sphinx-gallery generates the
Examples section from them into `docs/examples/`, which git ignores. Examples
are grouped in subfolders by library area, each with a header file of its own
that sphinx-gallery renders as a titled section. Each area's part creates its
folder when its first example lands. Today there is the root header,
`examples/GALLERY_HEADER.rst`, and one placeholder, `examples/show_version.py`.

## What arrives later

- `validation/` with the core's slice: its runners and results, mirroring the
  package
  ([ADR 0025](../adr/0025-results-stored-as-data-in-mirrored-folders.md)); its
  pages with 3.8. `benchmarks/` with 3.9, mirrored the same way.
- `CHANGELOG.md`, `NOTICE` and `CITATION.cff` with the first release.
- `.github/`: the CI workflows, with the native engine's Phase 1.
- `engine/`: sqlearn's C++ library, its kernels and its bindings (ADR 0060),
  and sqlearn's DuckDB build (ADR 0061), with the native engine's Phase 1.
- Guide chapters, lessons, validation pages and benchmarks: the foundation
  creates no content beyond the placeholder example.

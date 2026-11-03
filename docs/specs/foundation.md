---
type: spec
tags: [repository-layout, packaging, quality-gates, docs-site, skeleton]
summary: "Foundation spec for the sqlearn repository skeleton: layout, packaging, quality gates, recipes, docs site, and out-of-scope items."
related: [docs/architecture/overview.md, docs/adr/0001-uv-for-python-packaging.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0007-python-3-12-floor.md, docs/adr/0010-british-prose-american-identifiers.md, docs/adr/0008-just-task-runner.md, docs/adr/0009-sphinx-documentation-site.md, docs/questions/agents-and-skills.md]
mdindex: [type=d4f02e, tags=c61c21, summary=50a6e7, related=1718c6]
---
# Foundation

Status: draft, carried over 2026-11-03 from the earlier attempt's approved
spec,
[`2026-10-01-foundation-design.md`](https://github.com/glaucis/sqlearn_tomosius/blob/main/docs/superpowers/specs/2026-10-01-foundation-design.md)
in `glaucis/sqlearn_tomosius`. That spec holds the full detail (every tool's
configuration, the checks it was verified with); this one records what carries
over and what changed for this repository. To be reviewed by Tomas before a
plan is written from it.

Part 3.1 of [the overview](../architecture/overview.md).

## Purpose

The repository skeleton: layout, packaging and versioning, the quality gates
and the recipes that run them, the docs toolchain with a skeleton site, and
the conventions everyone writes to. It fixes what is expensive to change later
(the folders, the site's URLs, the build backend, every tool's configuration)
and creates nothing a later part owns. No product code.

## Done when

- A fresh clone installs with one command (`uv sync`).
- `just verify` passes on it.
- The docs build with warnings as errors.
- The conventions are written in `CLAUDE.md` and `docs/architecture/`.

## Layout

    sqlearn/
      .claude/               settings, and the project's own agents and skills
      docs/                  the Sphinx source root: the whole site
        adr/                 decision records (site: Development)
        architecture/        how the system is built (site: Development)
        specs/  plans/       specs and plans; in git, excluded from the site
        questions/  agents/  open questions, agent config; excluded from the site
        guide/               the user guide
        reference/           API reference config; pages generated
        learn/               beginner/, intermediate/, advanced/
        validation/          validation pages, rendered from data (3.8)
        benchmarks/          benchmark pages, rendered from data (3.9)
      examples/              sphinx-gallery sources; the gallery is generated
      validation/            reference implementations, runners, committed
                             results; imported by tests, never installed
      benchmarks/            the benchmark suite and its committed results
      src/sqlearn/           the package
      tests/
      pyproject.toml         the package and every tool's configuration
      uv.lock                committed
      justfile               the recipes
      .python-version        3.12
      .editorconfig  .gitattributes (LF everywhere)  .gitignore
      README.md  LICENSE (Apache-2.0)  CLAUDE.md
      CHANGELOG.md  NOTICE  CITATION.cff    from the first release

`.github/workflows/` arrives when the repository is public.

- **`src/` layout,** so the package cannot be imported from the checkout by
  accident and the tests run against what users install.
- **`examples/`, `validation/` and `benchmarks/` at the root:** code a user
  reads, found without opening `docs/`, as scikit-learn keeps its examples.
- **Never in the repository:** datasets beyond a few small bundled ones (larger
  ones are fetched only by an explicit call; examples generate big data inside
  DuckDB), build outputs (executed notebooks, figures, HTML; lessons are stored
  as text), and the built site.
- **The library and the whole site are one repository:** the reference is
  generated from the docstrings and the examples run the code.

### Changed from the earlier spec

| Earlier | Here | Why |
|---|---|---|
| `records/` for findings | GitHub Issues and `docs/questions/` | the issue tracker set up in `docs/agents/` |
| `docs/architecture/decisions/` | `docs/adr/` | this repository's docs layout |
| `docs/superpowers/specs/`, `plans/` | `docs/specs/`, `docs/plans/` | this repository's docs layout |
| copied superpowers skills, orchestrator and `opus`/`sonnet` agents, record hooks in `.claude/` | the installed plugins; project agents only when [questions/agents-and-skills.md](../questions/agents-and-skills.md) decides | start lean, add when the work shows the need |

The site builds from `docs/`, so the folders not on the site (`specs/`,
`plans/`, `questions/`, `agents/`) are excluded by name in `conf.py`.

## Packaging

- `hatchling` with `hatch-vcs`: the version comes from the git tag; nothing is
  bumped by hand. uv's own backend was set aside: pure Python only, no version
  from a tag, no build hook to bundle a front end later.
- uv for environments, one committed universal lockfile, dependency groups
  `test`, `lint`, `docs`, never published
  ([ADR 0001](../adr/0001-uv-for-python-packaging.md)).
- One runtime dependency, `duckdb`, with its justification as a comment beside
  it ([ADR 0005](../adr/0005-runtime-dependencies.md)).
- Python 3.12 floor; the matrix is 3.12, 3.13, 3.14
  ([ADR 0007](../adr/0007-python-3-12-floor.md)).
- Releases: semver on git tags, changelog generated from conventional
  commits, PyPI first, conda-forge at the first release.

## Quality gates

Every tool's settings live in `pyproject.toml`. Versions are pinned by
`uv.lock` and moved only by `just upgrade-dependencies`.

| Tool | Job |
|---|---|
| ruff | lint and format Python |
| ty, mypy (strict, over `src/`) | type checking |
| pytest, pytest-cov | tests; warnings are errors; coverage reported, floor set by the core spec |
| numpydoc | docstring validation |
| rumdl | Markdown lint and wrap at 80 columns |
| typos | spelling, locale `en` ([ADR 0010](../adr/0010-british-prose-american-identifiers.md)) |
| commitlint | conventional commit messages |

## Recipes

`just` runs everything ([ADR 0008](../adr/0008-just-task-runner.md)). Small
recipes, one tool each, and composites that stack them:

- `fmt`: `fmt-python` then `fmt-markdown`; the only recipes that edit files.
- `check`: lint Python, check types, lint Markdown, check spelling. Run by the
  pre-commit hook through `just pre-commit` (`check`, then `uv lock --check`),
  over the commit's own files, so another unfinished file refuses nothing.
- `test`: the fast tier.
- `verify`: `check`, mypy, the tests on every Python in the matrix, docstrings,
  and the docs build. Run at every review, merge and release.
- Later: `validate` (3.8), `release`, `docs-deploy` (hosting decision).

## Documentation site

Sphinx with pydata-sphinx-theme, MyST for Markdown, numpydoc and autosummary
for the reference, sphinx-gallery for examples, intersphinx to Python's and
DuckDB's docs, MathJax bundled locally, and the reference inventories fetched
into the repository so the build works offline
([ADR 0009](../adr/0009-sphinx-documentation-site.md)).

| Navigation | Built from | URL |
|---|---|---|
| Guide | `docs/guide/` | `guide/` |
| Reference | `docs/reference/` | `reference/` |
| Examples | `examples/`, generated into `docs/examples/` | `examples/` |
| Learn | `docs/learn/` | `learn/beginner/`, `learn/intermediate/`, `learn/advanced/` |
| Validation | `docs/validation/` | `validation/` |
| Benchmarks | `docs/benchmarks/` | `benchmarks/` |
| Development | `docs/architecture/`, `docs/adr/` | `architecture/`, `adr/` |

The Development section's URLs depend on the folder names, so those names do
not change after the first deploy.

## Out of scope

- Product code.
- CI: none while the repository is private; the pre-commit hook, the reviewer
  and `just verify` are the net. Linux and Windows are a known gap until then.
- First-release files (`NOTICE`, `CITATION.cff`, `CHANGELOG.md`) and release
  automation.
- Deploying and versioning the docs.
- `validation/` and `benchmarks/` content.

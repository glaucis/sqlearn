---
type: adr
tags: [sphinx, documentation, github-pages, docs-site, learning]
summary: "Decides on one Sphinx-built documentation site (API reference, guide, examples, learning path) served from GitHub Pages."
related: [docs/adr/0062-apple-silicon-first.md]
mdindex: [type=0fc814, tags=c5052f, summary=0b4b95]
---
# 0009: One Sphinx site for documentation and learning

Status: accepted (decided 2026-09-30 in the earlier attempt; carried over
2026-11-03). Amended by
[ADR 0062](0062-apple-silicon-first.md) (2026-11-21): the repository is
public, and the site is served by GitHub Pages from it.

## Context

sqlearn needs an API reference, a user guide, executed examples, validation
and benchmark pages, and a learning path, to the standard of scikit-learn and
pandas.

## Decision

One static site, built with Sphinx from `docs/`, served on GitHub Pages:

- pydata-sphinx-theme, with its version switcher over one directory per
  release;
- autosummary and numpydoc for the reference, generated from docstrings;
- sphinx-gallery for executed examples, linked back to the API pages that use
  them;
- MyST-Parser and MyST-NB, so the guide and the curriculum are written in
  Markdown;
- intersphinx to Python's and DuckDB's documentation;
- MathJax bundled with the site, and `sphinxcontrib-bibtex` for one shared
  bibliography.

## Consequences

- It is the stack of scikit-learn and pandas, and the only candidate that met
  all the requirements in the earlier attempt's research. Its costs are setup
  time and plumbing: a docs build that imports the package, cached executed
  examples, and a written rule for where Markdown ends and reStructuredText
  begins.
- The site is English only.
- Hosting while the repository was private was open; [ADR
  0062](0062-apple-silicon-first.md) settles it: the repository is public.

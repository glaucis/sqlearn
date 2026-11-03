---
type: adr
tags: [sphinx, documentation, gallery, github-pages, docs-site]
summary: "ADR 0009 decides to build sqlearn's documentation and learning site with Sphinx, served on GitHub Pages, using specific extensions."
related: [docs/questions/site-hosting.md]
mdindex: [type=0fc814, tags=812b07, summary=dd3f5e, related=0bc3d0]
---
# 0009: One Sphinx site for documentation and learning

Status: accepted (decided 2026-09-30 in the earlier attempt; carried over
2026-11-03)

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
- Hosting while the repository is private is open:
  [questions/site-hosting.md](../questions/site-hosting.md).

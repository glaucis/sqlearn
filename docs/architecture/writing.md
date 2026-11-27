---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
type: guide
tags: [documentation, markdown, restructuredtext, myst, style]
summary: "Explains how docs and Markdown are written: Markdown vs reStructuredText rules, British English, 80-column wrapping, math, and text notebooks."
related: [docs/specs/foundation.md, docs/adr/0010-british-prose-american-identifiers.md, docs/adr/0006-local-and-offline.md, pyproject.toml, docs/_static/mathjax]
mdindex: [type=83ca68, tags=0634b9, summary=3c2987, related=32f0f2]
---

# Writing the documentation

This page says how the documentation and the Markdown in this repository are
written. The full configuration is in [the foundation
spec](../specs/foundation.md).

## Markdown and reStructuredText

The rule:

> Docstrings are reStructuredText, in numpydoc's format, because autosummary
> and numpydoc read them so. Every page written by hand in `docs/` is
> Markdown, as MyST: a chapter, a lesson, a page of this section. One kind of
> file is reStructuredText because the tool that reads it reads nothing
> else: the autosummary templates the reference will grow. A construct only
> reStructuredText has goes, inside a Markdown page, in an `{eval-rst}`
> block. Lessons are MyST-NB's Markdown notebooks, never `.ipynb` files.

The gallery (its examples and `GALLERY_HEADER.rst`, which sphinx-gallery
read) and the reference index, whose `autosummary` sat in such a block, went
with the old Python to `old_python/`
([ADR 0073](../adr/0073-the-old-python-moves-to-old-python.md)); `docs/conf.py`
no longer loads sphinx-gallery.

## English

Prose is British English; identifiers are American, so `color` in code and
"colour" in a sentence
([ADR 0010](../adr/0010-british-prose-american-identifiers.md)). `just
check-spelling` runs typos at locale `en`, where both pass. typos knows
misspellings, not words, so identifiers never fire. A word typos mistakes for a
misspelling goes once into `[tool.typos.default.extend-words]` in
`pyproject.toml`, mapped to itself.

## Line length

Markdown prose wraps at 80 columns. `just fmt` does it: `rumdl fmt` refills a
paragraph or list item that holds a line over the limit, and leaves a
paragraph of short lines alone. Run `just fmt` before every commit; `just
lint-markdown` reports what is still over.

The formatter leaves as found:

- fenced code blocks, tables, block quotes and front matter;
- link reference definitions, a line holding only a URL, and HTML blocks;
- headings, which `just lint-markdown` reports and `just fmt` never wraps.

A line that cannot wrap, and sits in none of those, gets a comment on the line
above it, in the form rumdl and markdownlint both read:

```markdown
<!-- markdownlint-disable-next-line MD013 -->
```

Only MD013, the line length, is enabled. Another rule joins with its reason.

## Math

Write inline math as `$...$` and display math as `$$...$$`, as in MyST. The
site renders it with MathJax, which the build bundles under
`docs/_static/mathjax` (`just fetch-mathjax`), so a page reads with no
network ([ADR 0006](../adr/0006-local-and-offline.md)). The formula below is
the page's check that the pipeline works.

## Text notebooks

A lesson is a Markdown file with MyST-NB front matter (`file_format: mystnb`
and a `python3` kernelspec), whose `{code-cell}` blocks the build executes.
This page is one: the cell below prints the installed version.

```{code-cell} python
import sqlearn

print(sqlearn.__version__)
```

$$
\hat{\beta} = (X^\top X)^{-1} X^\top y
$$

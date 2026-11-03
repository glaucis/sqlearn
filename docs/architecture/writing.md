---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
---

# Writing the documentation

This page says how the documentation and the Markdown in this repository are
written. The full configuration is in [the foundation
spec](../specs/foundation.md).

## Markdown and reStructuredText

The rule:

> Docstrings are reStructuredText, in numpydoc's format, because autosummary
> and numpydoc read them so. Every page written by hand in `docs/` is
> Markdown, as MyST: a chapter, a lesson, a page of this section. Two kinds of
> file are reStructuredText because the tool that reads them reads nothing
> else: the text blocks of a gallery example and the gallery's header, which
> sphinx-gallery reads, and the autosummary templates the reference will
> grow. A construct only reStructuredText has goes, inside a Markdown page,
> in an `{eval-rst}` block, as the reference index's `autosummary` does.
> Lessons are MyST-NB's Markdown notebooks, never `.ipynb` files.

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

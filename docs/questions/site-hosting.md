---
type: question
tags: [hosting, github-pages, documentation, private-repository, deployment]
summary: "Asks where the Sphinx site is hosted while the repository is private, given GitHub Pages limits, and lists the options considered."
related: [docs/adr/0009-sphinx-documentation-site.md]
mdindex: [type=1f5087, tags=c93410, summary=cfc8b9, related=358b30]
---
# Where is the site hosted while the repository is private?

The site goes on GitHub Pages
([ADR 0009](../adr/0009-sphinx-documentation-site.md)), but GitHub Pages
serves a private repository only on a paid plan, and `glaucis/sqlearn` is
private.

Options:

- Make the repository public before the first deploy.
- Push the built site, overwritten on every deploy and never accumulated, to
  an orphan branch of this repository or to a public repository of its own (as
  scikit-learn's is).

Also open with it: GitHub Actions for CI, which arrives when the repository is
public; verify then that Actions is free for public repositories.

Decided by Tomas, before the first deploy.

---
type: question
tags: [applications, repository-layout, browser-frontend, licensing, open-source]
summary: "Asks whether the browser applications (EDA app and workflow editor) live inside this repo or in their own repository, deferred until the first application start"
mdindex: [type=1f5087, tags=36cb06, summary=690b50]
---
# Where do the applications live?

The exploratory data analysis application and the workflow editor (overview
3.6 and 3.7) bring a browser front end.

Options:

- Inside this repository. Cheap to undo: `git subtree split` carries a folder
  out with its history.
- A repository of its own, depending on the published library.

Fixed either way: a paid edition is a repository of its own from its first
commit, since a public repository has no private folder
([ADR 0004](../adr/0004-apache-2-licence.md)). The library stays at
`src/sqlearn/` whatever is chosen, so the foundation does not wait on this.

Decided by Tomas, when the first application starts.

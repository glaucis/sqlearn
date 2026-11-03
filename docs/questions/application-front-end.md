---
type: question
tags: [front-end, svelte, react, vue, applications]
summary: "Open question on which front-end framework the browser applications should use, with Svelte, React, and Vue as candidates."
related: [docs/architecture/overview.md, docs/adr/0006-local-and-offline.md, docs/adr/0009-sphinx-documentation-site.md]
mdindex: [type=1f5087, tags=8cf69d, summary=fb9ca1, related=74f902]
---
# Which front end do the applications use?

The applications ([overview 3.6 and 3.7](../architecture/overview.md)) are
browser front ends served locally
([ADR 0006](../adr/0006-local-and-offline.md)).

Candidates: Svelte (Tomas's candidate), React, Vue.

The documentation site stays Sphinx and takes no framework
([ADR 0009](../adr/0009-sphinx-documentation-site.md)).

Decided by Tomas, in the exploratory data analysis spec.

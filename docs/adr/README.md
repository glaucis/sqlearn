---
type: guide
tags: [adr, architecture-decisions, documentation, conventions]
summary: "Explains the conventions for architecture decision records: file naming, immutability after acceptance, and archiving superseded records."
mdindex: [type=83ca68, tags=607b14, summary=167747, related=f0df53]
related: [docs/adr/index.md, docs/adr/archived/README.md]
---
Architecture decision records: one file per decision, `NNNN-short-title.md`,
never edited after acceptance (supersede instead). Superseded, or its subject
gone, it moves to `archived/` with its number, its status line saying why.

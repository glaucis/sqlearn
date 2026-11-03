---
type: adr
tags: [spelling, british-english, american-identifiers, conventions, style]
summary: "ADR setting British English for prose and American spelling for code identifiers, checked by the typos tool at locale en."
mdindex: [type=0fc814, tags=a333e3, summary=b4bf2f]
---
# 0010: British prose, American identifiers

Status: accepted (decided 2026-10-01 in the earlier attempt; carried over
2026-11-03)

## Context

The project's text needs one spelling convention, and its code should match
the scientific-Python ecosystem it sits beside.

## Decision

- Prose (docs, docstrings' text, comments, the site) is written in British
  English: "optimise", "behaviour", "licence" (noun).
- Identifiers (names in code, parameters, file names) use American spelling,
  as scikit-learn, numpy and Python do: `normalize`, `color`, `fit_transform`.
- `typos` checks spelling at locale `en`, which accepts both.

## Consequences

- A reviewer corrects American spelling in prose and British spelling in
  identifiers.

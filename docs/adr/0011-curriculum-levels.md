---
type: adr
tags: [curriculum, learning-site, urls, machine-learning, levels]
summary: "ADR fixing the learning site to three curriculum levels (Beginner, Intermediate, Advanced) at permanent /learn/ URLs."
mdindex: [type=0fc814, tags=b2c1ea, summary=26f175, related=3d8346]
related: [docs/architecture/overview.md]
---
# 0011: Three curriculum levels with fixed URLs

Status: accepted (decided 2026-10-01 in the earlier attempt; carried over
2026-11-03)

## Context

The learning site ([overview 3.5](../architecture/overview.md)) teaches machine learning in one sequence. Its
structure and URLs have to be fixed before the first lesson, so no link ever
breaks.

## Decision

Three levels, in sequence: Beginner, Intermediate, Advanced, at
`/learn/beginner/`, `/learn/intermediate/` and `/learn/advanced/`. These URLs
never move.

- **Beginner** assumes Python and nothing of machine learning: what a model
  is, data in, first models, how to tell whether they work.
- **Intermediate:** pipelines, feature engineering, model selection, metrics
  in depth, data past memory.
- **Advanced:** the algorithms' insides and their SQL, custom estimators,
  scale and performance, validation.

## Consequences

- Each level's index says what it assumes and what the reader can do at its
  end. The names stay plain so the index can be precise and can change.
- Lessons are many and grow without limit within each level.
- The detailed split is designed in the learning site's spec.

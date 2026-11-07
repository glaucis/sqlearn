---
type: adr
tags: [search, folds, sql, cross-validation]
summary: "Records that a fold scheme is an interface of SQL over the rows (splits, a stable key, numbered, training and held predicates), that value-dealt folds keep identical rows together, and that ADR 0038's row-position folds stay inside the target encoder."
related: [docs/adr/0039-the-search-names-as-groups.md, docs/adr/0038-the-target-encoders-inner-folds-follow-row-position.md, docs/specs/library-model-selection.md]
---
# 0040: Fold schemes as SQL over rows

Status: accepted (2026-11-07). Made during the model-selection build.

## Context

The search took a `KFold` and nothing else. Model selection adds stratified,
grouped, holdout and time schemes, which differ in how they number the rows
and in which rows a fold learns from and holds out. A search must take any
of them, and none may pull the data into Python to deal it.

## Decision

A fold scheme is any object with the members of `sqlearn.model_selection.Folds`
(spec section 6):

- `splits`: how many folds are scored.
- `key`: the scheme's settings as a tuple, stable across processes (for
  example `("kfold", 5, 0)`). The learning store's fold key becomes
  `(scheme key, k)`, replacing `(n, seed, k)`.
- `numbered(rel, name, target)`: every row, plus a column `name` and any
  helper columns whose names start with `name`.
- `training(name, k)` and `held(name, k)`: predicates over the numbered
  relation, true for the rows fold `k` learns from and holds out.

A scheme is SQL over rows: the numbering is one query, and each fold is two
filters. The search passes both predicates through the fold's query, so the
rows fitted and scored are the scheme's own, not inferred as "everything
else". Rows that fall in neither (a time scheme's gap) are used for neither.

`KFold` implements it: `splits == n`, `key == ("kfold", n, seed)`, training is
`name != k`, held is `name == k`. It deals by a hash of each row's values and
the seed, so identical rows share a fold and are never split between
training and held-out rows.

ADR 0038's folds, dealt by row position, stay inside the target encoder:
they are the encoder's inner folds, not a scheme a user chooses.

## Consequences

- The search's fold key changes shape; nothing stored survives a restart, so
  nothing migrates.
- A user's own scheme works in a search by providing the five members.
- Later schemes are added as classes, with a shortcut in `sq.folds`.

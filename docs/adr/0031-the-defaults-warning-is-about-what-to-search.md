---
type: adr
tags: [search, defaults, warnings, model-selection, api]
summary: "Records that DefaultsUsedWarning fires only when Search's params are left to the default, while a default method or folds is recorded in used_ without a warning."
related: [docs/adr/0022-one-search-with-pluggable-methods.md]
---
# 0031: The defaults warning is about what to search

Status: accepted (2026-11-05). Made during the core build, reviewed after it.

## Context

[ADR 0022](0022-one-search-with-pluggable-methods.md) lets `Search` run with
defaults: a default space of settings for known models, a grid, and
`KFold(5, seed=0)`. It hints when a default was used. Most searches leave the
method and folds alone, so warning on every default would warn on almost every
search.

## Decision

`DefaultsUsedWarning` fires only when `params` (what to search) is left out:

```python
sq.Search(pipe).train("t")  # warns: searched the default space
sq.Search(pipe, params={"model__C": [0.1, 1]})  # no warning
```

A default method or folds is recorded in `used_` and not warned about. With no
default space for the model, the warning says it ran one trial with the
model's own settings.

## Consequences

- `search.used_` says what was defaulted, warned or not.

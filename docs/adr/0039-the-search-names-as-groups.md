---
type: adr
tags: [search, folds, groups, api, naming]
summary: "Records that the search's names move into two groups, sq.search (callable, with grid, range and later random and optuna) and sq.folds (kfold and later the other schemes), as ADR 0034 did for the steps; sq.Model stays at the top level."
related: [docs/adr/0034-a-grouped-api.md, docs/adr/archived/0022-one-search-with-pluggable-methods.md, docs/specs/archived/library-model-selection.md]
---
# 0039: The search's names as groups

Status: accepted (2026-11-07). Made during the model-selection build.
Extends [ADR 0034](0034-a-grouped-api.md) to the search and amends the names
in [ADR 0022](archived/0022-one-search-with-pluggable-methods.md). Amended by
[ADR 0073](0073-the-old-python-moves-to-old-python.md): its classes, built on
`sqlearn._group.Group`, are in `old_python/`, never run. Its search names are
restated in [ADR 0077](0077-the-search.md), which supersedes the rest of the
search's records.

## Context

ADR 0034 put the steps' names into groups (`sq.impute`, `sq.scale`, ...) so
that the top level stays small and each group lists its shortcuts in
`dir()` and `help()`. The search still had four loose names at the top
level (`sq.Search`, `sq.Grid`, `sq.KFold`, `sq.range`), and model selection
is about to add more methods (random, Optuna) and more fold schemes
(stratified, grouped, time, holdout).

## Decision

The search's names move into two groups, built on `sqlearn._group.Group`
as the step groups are. `sq.search` is callable, as `sq.impute` is.

| before | after |
|---|---|
| `sq.Search(pipe, ...)` | `sq.search(pipe, ...)` |
| `sq.Grid()` | `sq.search.grid()` |
| `sq.range(...)` | `sq.search.range(...)` |
| (planned) `sq.Random`, `sq.Optuna` | `sq.search.random(...)`, `sq.search.optuna(...)` |
| `sq.KFold(5, seed=0)` | `sq.folds.kfold(5, seed=0)` |
| (planned) other schemes | `sq.folds.stratified`, `group`, `time`, `holdout` |
| `sq.Model(...)` | unchanged |

`sq.Model` stays at the top level, as `sq.Learned` and `sq.Output` do
(ruling F5 of the preprocessing build). The classes (`Search`, `Grid`,
`Random`, `Optuna`, `Range`, and the fold schemes `KFold`, `Stratified`,
`Grouped`, `Holdout`, `TimeSplit`) stay importable from
`sqlearn.model_selection`, for type annotations and `isinstance`.

The old names are removed, not kept as aliases: nothing is released yet.

## Consequences

- The top level loses `Search`, `Grid`, `KFold` and `range` (which also
  stops shadowing the built-in) and gains `search` and `folds`.
- Later tasks add shortcuts to the two groups without touching the top level.
- Messages print the new paths (`sq.search.range`). Reprs print the class
  and its settings, as scikit-learn's do: `KFold(n=5, seed=0)`, `Grid()`,
  `Range(low=..., high=..., log=...)`.

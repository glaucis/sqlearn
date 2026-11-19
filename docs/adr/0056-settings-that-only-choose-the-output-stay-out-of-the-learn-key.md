---
type: adr
tags: [learned-state, store, search, feature-selection, step-contract]
summary: "Records that a step may declare settings that change only which output it gives from what it learned (sq.select's k, percentile, threshold): they stay out of the key of what it learns, so a search over them learns each fold once and only applies per setting."
related: [docs/adr/0014-learning-store.md, docs/adr/0024-store-keys-follow-what-a-step-reads.md, docs/specs/library-feature-selection.md]
---
# 0056: Settings that only choose the output stay out of the learn key

Status: accepted (2026-11-19), with the
[feature selection spec](../specs/library-feature-selection.md). Chosen by
Tomas on 2026-11-19.

## Context

A step's store key holds all its settings
([ADR 0024](0024-store-keys-follow-what-a-step-reads.md)). For a feature
selector, `k`, `percentile` and `threshold` do not change what it learns
(each column's score or variance), only which columns it keeps from it.

```python
sq.search(pipe, params={"best__k": [5, 10, 20]}, folds=sq.folds.kfold(5))
```

With every setting in the key, each of the three settings learns the same
scores on each of the five folds: fifteen scans of the training rows where
five give the same answer. On data larger than memory that is the cost that
matters. scikit-learn refits `SelectKBest` for each `k`; its answer does not
depend on that.

## Decision

- **A step may declare settings that change only its output, never what it
  learns.** They stay out of the key of what it learns, so the values learned
  for one such setting are found in the store for another
  ([ADR 0014](0014-learning-store.md): nothing is learned twice).
- **What it outputs still follows every setting:** the output, and every
  later step that reads it, are keyed and built with all of them.
- **The feature selectors declare theirs:** `k` for `best`, `percentile` for
  `percentile`, `threshold` for `variance`. `score` changes what is learned
  and stays in the key.

## Consequences

- A search over such a setting learns each fold once; preparing each
  setting's data for the model still happens per setting, as for any step.
- A step that declares a setting wrongly (one that does change what it
  learns) would reuse values it should not: the declaration is tested for
  each step that makes one.
- The answer is scikit-learn's: the values learned do not depend on the
  setting.

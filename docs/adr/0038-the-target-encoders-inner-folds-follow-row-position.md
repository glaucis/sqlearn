---
type: adr
tags: [target-encoding, cross-fitting, folds, row-order, preprocessing]
summary: "Records that the target encoder's inner folds are dealt by each row's position in the pipeline's fixed row order, hashed with the seed, not by the row's values, so identical rows can fall in different folds."
related: [docs/adr/0021-inputs-and-how-the-store-knows-them.md, docs/adr/0022-one-search-with-pluggable-methods.md, docs/specs/library-preprocessing.md]
---
# 0038: The target encoder's inner folds follow row position

Status: accepted (2026-11-07). Made during the preprocessing build (ruling T10a
in its build ledger).

## Context

`sq.encode.target` cross-fits: each training row is encoded from the rows
outside its own inner fold. The obvious way to deal rows into folds in SQL
is to hash the row's values with the seed, because that needs no order. But
identical rows then share a fold. With the category as the only feature, every
row of a category lands in one fold, is encoded from data without that
category, and gets the overall mean: target encoding is defeated.

## Decision

The inner folds hash each row's position in the pipeline's fixed row order
(the core's row numbering) with the seed, as scikit-learn's `KFold` deals rows
by position. Rows that are alike get folds of their own.

## Consequences

- The inner folds depend on row order: the same rows in another order give
  other inner folds, and so slightly other encodings of the training rows.
  The core already relies on a fixed row order for predictions, and the store
  recognises a frame by its values and their order
  ([ADR 0021](0021-inputs-and-how-the-store-knows-them.md)).
- `apply` on new data is unaffected: it uses the values learned from all rows.
- The outer folds of a search (`sq.KFold`) are unchanged.

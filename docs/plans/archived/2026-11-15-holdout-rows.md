---
type: plan
tags: [folds, holdout, model-selection, guide]
summary: "Implementation plan for Holdout.rows (#60): the held-out or training rows of a holdout split, as KFold.rows gives a fold's, and the evaluating guide holding out a plain fifth of the rows."
related: [old_python/docs/guide/evaluating-a-model.md, docs/adr/0040-fold-schemes-as-sql-over-rows.md]
---
# Holdout.rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sq.folds.holdout(...).rows(rel, held=...)` returns a holdout's
held-out or training rows, as `KFold.rows` returns a fold's.

**Architecture:** `Holdout.rows` filters `_whole_row(rel)` on
`Holdout.expression(ALIAS)` (0 held out, 1 learned from) and projects the
data's columns back, as `KFold.rows` does with its own fold.

**Tech Stack:** Python 3.12, DuckDB 2.0 relational API, pytest, `uv`, `just`.

**Spec:** the design comment on issue #60 (2026-11-15), approved by Tomas.

## Global Constraints

- Signature `rows(self, rel, k=0, *, held)`; `held` has no default.
- A `k` other than 0 is a `SqlearnError` ending in a `Fix:` sentence.
- British English in prose, numpydoc docstring with a runnable example.

## Review Focus

1. **A `k` given as `True` or `0.0`**: refused as not 0, as `_whole_number`
   refuses a bool. Test in Task 1.
2. **Repeated identical rows** go to the same side, as a holdout's fold is a
   hash of the whole row. Test in Task 1.
3. **A column named as the row alias** is refused, as `numbered` refuses it.
   Test in Task 1.

---

### Task 1: `Holdout.rows`

**Files:**
- Modify: `src/sqlearn/model_selection/folds.py` (`Holdout`, after
  `numbered`)
- Test: `tests/src/sqlearn/model_selection/test_folds.py` (after
  `test_holdout_is_one_split_of_about_the_share`)

- [ ] **Step 1: Write the failing tests**

```python
def test_holdout_rows_split_the_data():
    # range(10000), holdout(test=0.2, seed=0): held | trained == all,
    # no overlap, 1900 < len(held) < 2100, held == the rows numbered 0,
    # rows(rel, 0, held=True) == rows(rel, held=True), same again on rerun

def test_holdout_rows_keep_identical_rows_together():
    # VALUES (1,'a'), (2,'b'), (1,'a') repeated 50 times: each distinct
    # row appears on one side only

@pytest.mark.parametrize("k", [1, -1, True, 0.0])
def test_holdout_rows_refuse_a_fold_other_than_zero(k):
    # SqlearnError match "only fold 0"

def test_holdout_rows_refuse_the_row_alias():
    # a column named ALIAS: SqlearnError match "rename"
```

- [ ] **Step 2: Run them to watch them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection/test_folds.py -q -k`
`holdout_rows`
Expected: FAIL with `AttributeError: 'Holdout' object has no attribute
'rows'`.

- [ ] **Step 3: Implement** `Holdout.rows(rel, k=0, *, held)`; refuse
  `type(k) is not int or k != 0` with "a holdout has only fold 0 (the
  split), so k={k!r} names no fold. Fix: leave k out, or pass k=0."

- [ ] **Step 4: Run the tests, then `just test`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: a holdout hands back its held-out or
  training rows (#60)`.

### Task 2: The guide and the handoff

**Files:** `docs/guide/evaluating-a-model.md`, `HANDOFF.md`

- [ ] **Step 1:** The guide's first cell takes `split =
  sq.folds.holdout(test=0.2, seed=0)`, `train = split.rows(data,
  held=False)`, `held = split.rows(data, held=True).df()`; the prose before
  it says a fifth of the rows is held out with `sq.folds.holdout`.
- [ ] **Step 2:** `rm -rf docs/reference/generated docs/_build && just
  build-docs`. Expected: the guide's cells run.
- [ ] **Step 3:** `just fmt`, `just verify`. Expected: pass; name every
  failure.
- [ ] **Step 4:** `HANDOFF.md`: #60 to "Just finished". Commit `docs: the
  evaluating guide holds out a plain fifth (#60)`.

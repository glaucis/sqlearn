---
type: adr
tags: [steps, step-contract, apply, apply_row, learned, keeps_inputs, labels]
summary: "Records four additions the preprocessing build made to the step contract: label pairs from apply, the row values argument of apply_row, the Step.learned hook, and the keeps_inputs declaration."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/archived/0028-a-step-returning-a-mapping-counts-as-dynamic.md, docs/adr/0035-names-of-generated-columns.md, docs/specs/archived/library-preprocessing.md]
---
# 0037: Four additions to the step contract

Status: accepted (2026-11-07). Made during the preprocessing build (rulings T5a,
T8c, T11c and F2 in its build ledger). Extended by #32: a fifth declaration,
`copies_inputs`, for a step with `keep` whose copy of each input keeps the
input's own type while `creates` types its other columns. Archived (2026-11-27):
superseded by [ADR 0075](../0075-the-contract-of-a-users-own-step.md), which
states the contract of a user's own step in full.

## Context

The step contract is what a user's own step is written against
([ADR 0019](0019-custom-steps-and-failure-feedback.md)), so each addition is
one more thing every step author may meet and every later change must keep.
The preprocessing steps needed four that the spec did not foresee. Each was the
smallest change that let a step be written at all, or written without
quadratic SQL.

## Decision

1. **`apply` may return a sequence of `(label, expression)` pairs** as well as
   a mapping. OneHot learns the text `'NULL'` and the missing category, and
   both are labelled `NULL` before ADR 0035 numbers the clash; a mapping cannot
   hold two equal keys.
2. **`apply_row(xs, learned, values)` takes a third argument**: references to
   the values `row_values` computes once per row. A whole-row step such as the
   polynomial features shares one projection of them instead of repeating each
   in every output, which made its SQL quadratic in the number of columns.
3. **`Step.learned(values)` is a hook** the pipeline calls once per `learn` or
   `train` (and once for a search's final training, not per fold), after the
   values are known, whether computed or found in the store. It changes
   nothing; the binning steps warn from it. A step cannot otherwise tell a
   learn from an apply, and scikit-learn's `fit` warns on every fit.
4. **`keeps_inputs` is declared**, not inferred: True for a dynamic step whose
   outputs include each input under its own name (`sq.impute.indicator`
   passes its inputs through). The planner and the pipeline both read it, so a
   later step reading those inputs waits for the run after the step learns.

## Considered options

- **Two keys for the same label in a mapping** (a suffix added by the step):
  rejected, because naming clashes is the pipeline's job under ADR 0035, not
  each step's.
- **Row values as a separate step before the whole-row step**: rejected; the
  values belong to the step that reads them, and a separate step would show in
  the pipeline and the store.
- **Inferring `keeps_inputs` from `dynamic` and the output labels**: rejected;
  the labels are known only after learning, and the planner needs the answer
  before.

## Consequences

- The guide's "Writing a step" page documents all four; overriding
  `apply_row` without the `values` parameter is refused by the type checker.
- Removing any of them later breaks user steps that rely on it, so each now
  needs its own superseding ADR.

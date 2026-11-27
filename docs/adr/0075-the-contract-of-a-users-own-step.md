---
type: adr
tags: [step-contract, user-steps, static-dynamic, learn-apply, error-diagnosis]
summary: "Consolidates the contract for user-written steps (static/dynamic classification, inspection, failure reporting, hooks, declarations), superseding ADRs 0019, 002"
related: [docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/archived/0027-a-user-step-may-declare-itself-dynamic.md, docs/adr/archived/0028-a-step-returning-a-mapping-counts-as-dynamic.md, docs/adr/archived/0037-four-additions-to-the-step-contract.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/0074-how-a-pipeline-learns.md, docs/adr/0035-names-of-generated-columns.md]
mdindex: [type=0fc814, tags=e19eff, summary=d1ced5, related=7a2183]
---
# 0075: The contract of a user's own step

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27, in the docs
cleanup. Supersedes
[ADR 0019](archived/0019-custom-steps-and-failure-feedback.md),
[ADR 0027](archived/0027-a-user-step-may-declare-itself-dynamic.md),
[ADR 0028](archived/0028-a-step-returning-a-mapping-counts-as-dynamic.md) and
[ADR 0037](archived/0037-four-additions-to-the-step-contract.md).

## Context

Users write their own steps, and they stay writable in Python through the
rewrite ([ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md)). The contract such a
step is written against was spread over four records. ADR 0019 said how a
user's step is classified static or dynamic (added to
[ADR 0012](archived/0012-static-and-dynamic-steps.md), which covered only
built-in steps) and how a failed run is reported. ADR 0027 then let a step
declare itself dynamic, which ADR 0019's error message already advised.
ADR 0028 settled how an undeclared step returning a mapping is classed.
ADR 0037 added four parts to the contract during the preprocessing build,
and issue #32 a fifth. What static and dynamic mean, and how a pipeline's
runs follow from them, is
[ADR 0074](0074-how-a-pipeline-learns.md).

## Decision

- **A step has two parts:** what it learns, as SQL aggregates, and how it is
  applied, given what it learned (ADR 0019).
- **The normal path does only what it must.** Before a run sqlearn fills in
  each step's class where it is missing, then runs; diagnosis runs only after
  a failure (ADR 0019).
- **Built-in steps carry their class**, and tests and validation check it. A
  class may depend on settings: `max_parts=3` static, `max_parts="auto"`
  dynamic (ADR 0019).
- **A user's step may declare itself static or dynamic, and the declaration
  is trusted:** sqlearn does not inspect it. Declaring it not static means
  the same as declaring it dynamic. Declaring it both static and dynamic is
  refused with a `StepError` (ADR 0019, ADR 0027).
- **A user's step that declares nothing is inspected:** sqlearn calls its
  apply with placeholders in place of learned values, each a reference to
  that value of the learn stage. If the SQL builds, the step is static; if
  the step needs a real value (a loop over learned categories), the
  placeholder raises and the step is dynamic. Anything else unexpected counts
  as dynamic (ADR 0019).
- **An undeclared step whose apply returns a mapping of named columns is
  dynamic**, whether its names are fixed or come from what it learned:
  telling the two apart from placeholders is not reliable, and a step wrongly
  called dynamic costs one extra run, while one wrongly called static gives
  wrong SQL (ADR 0028).
- **The answer of an inspection is kept for the session**, once per step and
  settings. It is never written into the user's code or onto the step
  (ADR 0019).
- **When a run fails, sqlearn finds the step that failed and says so**,
  whether the failure comes while the SQL is built or while DuckDB runs it
  (ADR 0019):
  - for a user's step, a message names the step and its position, what went
    wrong, why, and a `Fix:` line; where it helps, the step's declaration is
    re-checked by inspection;
  - for a built-in step, it is sqlearn's bug, reported as an internal error
    with what is needed to reproduce it.
- **sqlearn does not judge whether a pipeline that runs is the one the user
  meant:** imputing with the median where the mode was wanted is the user's
  call (ADR 0019).
- **Apply may return a sequence of `(label, expression)` pairs** as well as a
  mapping, so two outputs may carry the same label; naming clashes is the
  pipeline's job under [ADR 0035](0035-names-of-generated-columns.md), not
  each step's (ADR 0037).
- **A whole-row step's apply receives references to its row values**,
  computed once per row, so its outputs share one projection of them instead
  of repeating each in every output. The values belong to the step that reads
  them, not to a separate step (ADR 0037).
- **A step has a hook the pipeline calls once per `learn` or `train`** (once
  for a search's final training, not per fold), after the learned values are
  known, whether computed or found in the store. It changes nothing; a step
  may warn from it (ADR 0037).
- **`keeps_inputs` is declared, not inferred:** true for a dynamic step whose
  outputs include each input under its own name. The planner and the pipeline
  both read it, so a later step reading those inputs waits for the run after
  the step learns (ADR 0037).
- **`copies_inputs` is declared** by a step with `keep` whose copy of each
  input keeps the input's own type while `creates` types its other columns
  (ADR 0037, issue #32).
- **Learning from the target and cross-fitting are two further
  declarations**, which stay in
  [ADR 0055](0055-a-target-step-need-not-cross-fit.md).
- **Changing or removing any part of this contract before `1.0.0`** follows
  ADR 0070's rule: the `sq.` API may change in the commit that needs it,
  recorded in `tests/public_api.txt`. This replaces ADR 0037's rule that
  removing any of its additions needs its own superseding ADR.
- **The mechanics are the C++ group's design (ADR 0070).** The old Python
  implemented the contract as the class `sq.Step` with `static` and
  `dynamic` class attributes, `learn(self, x)`, `apply(self, x, learned)`,
  `apply_row(xs, learned, values)` and the `Step.learned(values)` hook, and
  located a failure that came while DuckDB ran from the stage name in its
  error, each stage named after its step; that code is now in
  `old_python/src/sqlearn/` (`_step.py`, `_diagnose.py`, `_errors.py`).

## Consequences

- A wrong "static" is caught while the SQL is built, before DuckDB reads a
  row (ADR 0019).
- A step whose apply ignores what it learned and uses a stale value from
  elsewhere builds and runs with the wrong value; nothing catches that. The
  guide to writing steps says learned values come only through what the step
  learned (ADR 0019).
- A test suite of deliberately broken steps (wrong declaration, bad SQL, a
  missing column) checks the exact message each one gets (ADR 0019).
- A step that detection would misjudge can say what it is (ADR 0027).
- A step declared static whose apply returns new columns is not caught yet:
  the planner believes the declaration (parked, issue #8; ADR 0027).
- A step returning a mapping with fixed names costs one more run than it
  needs; declaring it static removes the run. No built-in step depends on
  this rule: they declare what they are (ADR 0028).
- The guide's page on writing a step documents the contract's parts
  (ADR 0037).
- ADRs 0019, 0027, 0028 and 0037 are archived in `archived/` and keep their
  numbers.

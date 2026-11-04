---
type: adr
tags: [custom-steps, static, dynamic, errors, feedback, performance]
summary: "Records how a user's own step is classified static or dynamic (declared and trusted, or inspected with placeholders), and that diagnosis runs only after a failure, with a message naming the step, the cause and the fix."
related: [docs/adr/0012-static-and-dynamic-steps.md, docs/adr/0018-runs-follow-the-chains-between-steps.md, docs/adr/0014-learning-store.md]
---
# 0019: Custom steps, and feedback when a run fails

Status: accepted (2026-11-04). Adds to
[ADR 0012](0012-static-and-dynamic-steps.md), which says built-in steps declare
their class and does not say how a user's step is classified.

## Context

Users write their own steps, as scikit-learn allows. sqlearn cannot know every
step in advance, yet must chain them
([ADR 0018](0018-runs-follow-the-chains-between-steps.md)). It should be fast in
the normal case and explain itself in full when something goes wrong.

A custom step is written in two parts:

```python
class MyScale(sq.Step):
    def learn(self, x):  # what to learn, as SQL aggregates
        return {"mu": sq.avg(x), "sd": sq.stddev_pop(x)}

    def apply(self, x, learned):  # how to apply it
        return (x - learned.mu) / learned.sd
```

## Decision

**The normal path does only what it must.** Before a run sqlearn fills in what
is missing, then runs. Diagnosis runs only after a failure.

1. **Fill in what is missing.** Every step needs a static or dynamic value.
   - Built-in steps carry theirs; tests and validation check them. A value may
     depend on settings (`StringSplit(max_parts=3)` is static,
     `max_parts="auto"` dynamic).
   - A user's step that declares one is trusted.
   - A user's step that does not is **inspected**: sqlearn calls its `apply`
     with placeholders in place of learned values. `learned.mu` is a reference
     to "the `mu` of the learn stage". If the SQL builds, the step is static;
     if the step needs a real value (`for city in learned.cities`), the
     placeholder raises and the step is dynamic. Anything else unexpected
     counts as dynamic.
   - The answer is kept in memory for the session, beside the learning store
     ([ADR 0014](0014-learning-store.md)), once per step and settings. It is
     never written into the user's code or onto the step.
2. **Run.**
3. **If it fails, find what failed and say so.** sqlearn locates the step: from
   the placeholder's own error while the SQL is built, or from the stage name
   in DuckDB's error (the compositor names each stage after its step) while it
   runs. Then:
   - **a user's step:** a message names the step and its position, what went
     wrong, why, and the fix; where it helps, the step's declaration is
     re-checked by inspection. For example:

     ```text
     MyEncoder (step 3) is declared static, but its apply() loops over
     learned.cities, which is only known after learning. A step that needs
     learned values to write its SQL is dynamic.
     Fix: remove static=True (sqlearn will then detect it), or set dynamic=True.
     ```

   - **a built-in step:** it is sqlearn's bug, reported as an internal error
     with what is needed to reproduce it.

sqlearn does not judge whether a pipeline that runs is the one the user meant:
imputing with the median where the mode was wanted is the user's call.

## Consequences

- A wrong "static" is caught while the SQL is built, before DuckDB reads a row.
- A step whose `apply` ignores `learned` and uses a stale value from elsewhere
  builds and runs with the wrong value; nothing catches that. The guide to
  writing steps says learned values come only through `learned`.
- A test suite of deliberately broken steps (wrong declaration, bad SQL, a
  missing column) checks the exact message each one gets.

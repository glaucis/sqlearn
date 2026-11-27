---
type: adr
tags: [custom-steps, static, dynamic, classification, api]
summary: "Records that a user's step may declare dynamic = True as well as static = True, that the declaration is trusted, and that declaring both is refused."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/archived/0028-a-step-returning-a-mapping-counts-as-dynamic.md]
---
# 0027: A user's step may declare itself dynamic

Status: accepted (2026-11-05). Made during the core build, reviewed after it.
Archived (2026-11-27): superseded by
[ADR 0075](../0075-the-contract-of-a-users-own-step.md), which states the
contract of a user's own step in full.

## Context

[ADR 0019](0019-custom-steps-and-failure-feedback.md) detects whether a user's
step is static or dynamic, lets the user declare it, and its error message
advises "or set dynamic=True". The first build supported only `static`, so the
advice named an attribute that did nothing.

## Decision

A step class may declare either:

```python
class Bucket(sq.Step):
    dynamic = True  # its output columns depend on what it learns


class Double(sq.Step):
    static = True  # one expression per column, whatever it learns
```

The declaration is trusted, as `static` is: sqlearn does not call `apply` with
placeholders to find out. `static = False` means the same as `dynamic = True`.
Declaring `static = True` and `dynamic = True` together is a `StepError`.

## Consequences

- A step that detection would misjudge can say what it is.
- A step declared `static = True` whose `apply` returns new columns is not
  caught yet: the planner believes the declaration (parked, issue #8).

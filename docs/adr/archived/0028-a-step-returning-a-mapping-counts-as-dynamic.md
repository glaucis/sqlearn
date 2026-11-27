---
type: adr
tags: [custom-steps, static, dynamic, classification, runs]
summary: "Records that an undeclared user step whose apply returns a mapping of new columns is classed dynamic even when its names are fixed, at the cost of one extra run."
related: [docs/adr/archived/0012-static-and-dynamic-steps.md, docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/archived/0027-a-user-step-may-declare-itself-dynamic.md]
---
# 0028: A step returning a mapping counts as dynamic

Status: accepted (2026-11-05). Made during the core build, reviewed after it.
Archived (2026-11-27): superseded by
[ADR 0075](../0075-the-contract-of-a-users-own-step.md), which states the
contract of a user's own step in full.

## Context

sqlearn classifies an undeclared user step by calling its `apply` with
placeholders for what it learns
([ADR 0019](0019-custom-steps-and-failure-feedback.md)). One expression back is
static. A step can also return a mapping of named columns, and those names may
be fixed or may come from what it learned:

```python
class Bounds(sq.Step):  # names fixed: x_low, x_high
    def apply(self, x, learned):
        return {"low": x - learned["sd"], "high": x + learned["sd"]}


class OneHot(sq.Step):  # names come from the categories learned
    def apply(self, x, learned):
        return {c: x == c for c in learned["categories"]}
```

Telling the two apart from placeholders is not reliable.

## Decision

An undeclared step whose `apply` returns a mapping is dynamic, whatever its
names. [ADR 0012](0012-static-and-dynamic-steps.md) makes the conservative
choice the safe one: a step wrongly called dynamic costs one extra run; a step
wrongly called static gives wrong SQL.

## Consequences

- `Bounds` above costs one more run than it needs. Declaring `static = True`
  ([ADR 0027](0027-a-user-step-may-declare-itself-dynamic.md)) removes it.
- No built-in step depends on this: they declare what they are.

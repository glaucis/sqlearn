---
type: adr
tags: [columns, selectors, steps, planner, custom-steps]
summary: "Records that a step given no cols= works on every column reaching it, and that the planner then counts it as reading every earlier step."
related: [docs/adr/0020-column-selectors.md, docs/adr/archived/0018-runs-follow-the-chains-between-steps.md, docs/adr/archived/0024-store-keys-follow-what-a-step-reads.md]
---
# 0026: A step without `cols=` works on every column

Status: accepted (2026-11-05). Made during the core build, reviewed after it.
Archived (2026-11-27): superseded by
[ADR 0074](../0074-how-a-pipeline-learns.md), which states how a pipeline learns
in full.

## Context

[ADR 0020](../0020-column-selectors.md) says what `cols=` takes, not what a step
does when it is left out. The built-in steps give a default (`Scale` and
`Impute` default to `sq.numeric()`), but `sq.Step` and a user's subclass
default to `cols=None`:

```python
class Clip(sq.Step):
    def apply(self, x, learned):
        return duckdb.FunctionExpression("greatest", x, duckdb.ConstantExpression(0))


sq.Pipeline([("clip", Clip())])  # which columns does it clip?
```

## Decision

- `cols=None` means every column reaching the step, in schema order.
- The planner treats such a step as reading columns it cannot know in
  advance, so it depends on every step before it, as
  [ADR 0018](0018-runs-follow-the-chains-between-steps.md) does for unknown
  inputs. A step after a dynamic one waits for it, and its store key holds
  every earlier step ([ADR 0024](0024-store-keys-follow-what-a-step-reads.md)).

## Consequences

- `Clip()` clips every column, columns created by earlier steps included.
- Such a step relearns whenever any earlier step changes; naming its columns
  narrows that.

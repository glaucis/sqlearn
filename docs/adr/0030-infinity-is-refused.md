---
type: adr
tags: [impute, scale, infinity, errors, numerics]
summary: "Records that Impute and Scale refuse a column holding infinity with a StepError naming it, as scikit-learn does, instead of giving NaN output silently."
related: [docs/adr/archived/0019-custom-steps-and-failure-feedback.md, docs/adr/0016-validation-method.md]
---
# 0030: Infinity is refused

Status: accepted (2026-11-05). Made during the core build, reviewed after it.

## Context

A column holding `inf` gives an infinite or NaN mean and spread. Left alone,
`Scale` would turn the whole column into NaN without a word. scikit-learn
refuses such input ("Input contains infinity").

```python
con.sql("CREATE TABLE t AS SELECT * FROM (VALUES (1.0), (2.0), ('inf'::DOUBLE)) v(x)")
sq.Pipeline([("scale", sq.Scale())]).learn("t")
# StepError: scale (step 1) cannot learn from column 'x': it contains infinity,
# which makes what is learned meaningless. Fix: replace the infinite values
# with NULL before this step.
```

## Decision

`Impute` and `Scale` check that each value they learned is finite, and refuse
the column with a `StepError` naming the step and the column when it is not.
Nothing is output silently wrong.

## Consequences

- Data with infinities must be cleaned first, as in scikit-learn.
- `Impute` learns one extra aggregate per column for the check.

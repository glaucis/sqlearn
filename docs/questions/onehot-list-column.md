---
type: question
tags: [onehot, runs, performance, remote-data, compositor]
summary: "Kept idea: OneHot writes one list column so a pipeline learns in one pass instead of two; worth building only when reading the data twice is expensive."
related: [docs/adr/0018-runs-follow-the-chains-between-steps.md, docs/benchmarks/onehot-second-run.md, "issue #22"]
---
# Should OneHot write one list column, to learn in one pass?

A kept idea, not planned. Decided 2026-11-10: keep it, do not build it yet.
Tracked in [issue #22](https://github.com/glaucis/sqlearn/issues/22).

## The idea

A pipeline learns in runs, passes over the data
([ADR 0018](../adr/0018-runs-follow-the-chains-between-steps.md)). OneHot
forces a new run because the columns it writes cannot be named before its
categories are learned:

```python
sq.Pipeline([sq.impute.median(), sq.encode.onehot("city"), sq.scale.standard()])
# run 1 learns impute and onehot; run 2 learns the scaler on city_Oslo, ...
```

If OneHot wrote one list column instead, `city_onehot = [0, 1, 0]`, its shape
would be known before learning, and the whole pipeline would learn in one run.
The list would become named columns only when handed to a model or shown to the
user. Checked on DuckDB 2.0.0: impute, scale and one-hot learn and apply in one
`WITH` query, the encoding as
`list_transform((SELECT cats FROM learn_onehot), lambda x: (city = x)::int)`.
DuckDB 2.0 refuses the old `x -> ...` lambda arrow.

## What it would save

[The benchmark](../benchmarks/onehot-second-run.md), 10,000,000 rows from a
local Parquet file: the second run adds 0.18 s to learning (0.75 s against
0.57 s) and one more read of the file (53 MB read against 24 MB). Applying is
one run either way.

## What it would cost

- Every step that can follow OneHot (scalers, imputers, custom steps) has to
  accept a list column as well as plain ones, or the compositor has to unpack
  the list for them.
- The generated SQL is harder to read and to debug.

## When to revisit

When reading the data twice is expensive: data on S3 or another remote store,
or a slow network disk, where a second run means a second download. Measure
the second run there first, with the benchmark above pointed at the remote
file.

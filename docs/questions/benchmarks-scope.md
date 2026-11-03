---
type: question
tags: [benchmarks, scope, performance, methodology]
summary: "Open question on which libraries, machine, and data sizes the project's benchmarks should compare."
mdindex: [type=1f5087, tags=b8b6e8, summary=2423f7, related=3d8346]
related: [docs/architecture/overview.md]
---
# What do the benchmarks compare, and on what machine?

Benchmarks ([overview 3.9](../architecture/overview.md)) compare speed, memory
and sizes past memory. Open:

- Which libraries are compared (scikit-learn, pandas, Polars, Spark, others).
- On what machine; the machine is described alongside the committed results.
- At what data sizes, including the size at which each other library stops.

Decided by Tomas, in the benchmarks spec.

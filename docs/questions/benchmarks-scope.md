---
type: question
tags: [benchmarks, performance, scope, methodology]
summary: "Open question on which libraries, machine, and data sizes the project benchmarks should compare."
mdindex: [type=1f5087, tags=a5c667, summary=38a4e4, related=3d8346]
related: [docs/architecture/overview.md]
---
# What do the benchmarks compare, and on what machine?

Benchmarks ([overview 3.9](../architecture/overview.md)) compare speed, memory and sizes past memory. Open:

- Which libraries are compared (scikit-learn, pandas, Polars, Spark, others).
- On what machine; the machine is described alongside the committed results.
- At what data sizes, including the size at which each other library stops.

Decided by Tomas, in the benchmarks spec.

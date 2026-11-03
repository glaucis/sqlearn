---
type: question
tags: [validation, precision, numerical-methods, reference-implementation, documentation]
summary: "Open questions on how library validation works: exact reference precision, handling iterative algorithms, and presenting the error table."
mdindex: [type=1f5087, tags=b67955, summary=301387]
related: [docs/architecture/overview.md]
---
# How exactly does validation work?

Validation ([overview 3.8](../architecture/overview.md)) compares every
library's result against an exact reference implementation. Three points are
open:

- **Precision:** `fractions.Fraction` or `decimal`, and at what precision.
- **Iterative algorithms:** the rule where no closed form exists (models fitted
  by iteration have no exact answer to compare against).
- **Presentation:** how the error table reads for someone who is not a
  numerical analyst.

Decided by Tomas, in the validation spec. The first validation page is part of
the library core's vertical slice, so these are settled with
[3.2](../architecture/overview.md).

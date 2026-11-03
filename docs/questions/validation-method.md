---
type: question
tags: [validation, precision, numerical-accuracy, testing, reference-implementation]
summary: "Open questions on how library validation works: exact reference precision, handling iterative algorithms, and error table presentation."
mdindex: [type=1f5087, tags=939656, summary=7455dd]
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

## What the earlier attempts show

Evidence from the ten earlier attempts ([the map](earlier-attempts/README.md));
the decision is still open.

- **Precision:** the strongest designs used exact references at 50 digits
  (`mpmath`, `Decimal`) or `Fraction` for order statistics, compared every
  library against them, and measured the error in ULPs against a bound stated
  per step and type. A `DECIMAL` mode in DuckDB does not help: its aggregates
  of `DECIMAL` return `DOUBLE`.
- **Two references answer two questions.** An exact reference says whether
  the SQL is faithful to the mathematics; a live scikit-learn says whether
  users get what they expect (`sql_learn_test`). The best designs kept both,
  with an `anomaly` flag when a reference library misses its own precision.
  A reference must be independent: `statistics.NormalDist` is the same
  algorithm as the AS 241 it would check.
- **Iterative algorithms:** `sql_learn_test` proposed checks that need no
  reference: a one-sided comparison of the objective, residual orthogonality.
  No attempt reached a model.
- **What broke every time:** nothing was a gate. Validators sat outside CI,
  parity tests skipped when data was missing, tolerances were hand-picked,
  loosened to hide mismatches, or replaced by correlation above 0.9. No
  attempt compared a whole pipeline; per-method parity passed while the
  pipeline was wrong.
- **Rules worth keeping:** a pipeline-level comparison for every composed
  case; datasets bundled or generated, never downloaded; small and large
  fixtures (a `ddof` error is 15% at n = 4, 5e-6 at n = 100,000); small,
  medium and large runs; NULL, NaN, empty, single-row and reserved-word
  fixtures; measurement at `threads=1`, since DuckDB's parallel sums vary in
  the last digits; tolerances set from measurement, loosened only with a
  written reason; known divergences asserted with their reason; invariants
  rather than second implementations as oracles.
- **Presentation:** per-feature results generated from the tests (never typed
  by hand) as a table of worst absolute, relative and ULP error per dataset,
  type and reference; a divergence register with the root cause.

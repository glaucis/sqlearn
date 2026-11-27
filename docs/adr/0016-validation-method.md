---
type: adr
tags: [validation, precision, references, testing, gate, upstream]
summary: "Records how sqlearn validates its SQL: against an exact canonical value and every comparable library, locating each drift, enforced as a gate, published as generated pages."
related: [docs/questions/validation-method.md, docs/architecture/overview.md, docs/adr/0006-local-and-offline.md, docs/adr/0012-static-and-dynamic-steps.md]
---
# 0016: Validation against the mathematics and every comparable library

Status: accepted (2026-11-04)

## Context

Validation ([overview 3.8](../architecture/overview.md)) is evidence for users
that every piece of sqlearn's SQL was not only tested but validated, and that
the project is serious. Earlier attempts wrote strong methods (exact
references, bounds from measurement) and never enforced them: validators sat
outside the checks, parity tests skipped when data was missing, tolerances
were hand-picked or loosened to hide mismatches, and no attempt compared a
whole pipeline, which let a fit defect survive in every one of them
([earlier attempts](../questions/archived/earlier-attempts/README.md)).

## Decision

**1. Against the mathematics.** Every formula is compared with a **canonical
value**: the exact mathematical answer computed in Python at high precision
(`mpmath` or `Decimal` at 50 digits, `Fraction` where the answer is rational),
never taken from another library. Comparisons are like for like: the same
input values, the same data type, the same definition (for example the
population standard deviation).

To locate a drift, each case is computed three ways and each is compared with
the canonical value:

- sqlearn's SQL;
- DuckDB's own function alone (for example `STDDEV_POP`), so a DuckDB
  limitation shows as DuckDB's;
- the same at one thread, so drift from parallel summation shows as such.

**2. Against every comparable library.** numpy, scikit-learn, scipy, pandas
and any other library that computes the same thing are compared with the
canonical value too, to show who is closest and who drifts. A library that
misses the precision its own algorithm should reach is flagged an
**anomaly**, distinct from pass or fail, with a reproducer ready to report
upstream.

**3. Enforced and published.**

- Validation runs in the checks; a failure blocks the merge.
- Error is measured (absolute, relative and in ULPs) and each bound is set from
  measurement; loosening a bound needs a written reason.
- Whole pipelines are validated, not only single steps (at least `Impute` then
  `Scale` against scikit-learn's pipeline).
- Data is bundled or generated with a fixed seed, never downloaded
  ([ADR 0006](0006-local-and-offline.md)); small, medium and large cases, and
  NULL, NaN, empty, single-row and reserved-word cases.
- Each step's validation page is generated from the runs, never typed by hand.

## Consequences

- The reference libraries are development dependencies only; at run time
  sqlearn still needs only `duckdb` and `numpy` (ADR 0057).
- Where a value is no better defined than its input, the measure is in ULPs
  of that value's perturbation scale, not of the value: the PCA runner
  (`validate_pca.py`) measures eigenvalues in ULPs of the largest, each
  eigenvector entry and output at the scale its gap sets, each entry of the
  covariance at `sqrt(CᵢᵢCⱼⱼ)`, and its outputs against its own learned
  values. The runner's docstring gives each scale; the bounds are still set
  from measurement.
- Known, deliberate differences from a library are recorded with their reason
  and asserted as such, not hidden by a looser bound.
- Left for later: the rule for models fitted by iteration, which have no exact
  answer (decided with the models, overview 3.3; one earlier idea is to check
  the objective and the residuals instead), and the layout of the validation
  page (the validation spec, written with the core).

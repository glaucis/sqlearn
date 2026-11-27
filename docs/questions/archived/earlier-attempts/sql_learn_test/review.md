---
type: question
tags: [earlier-attempts, library-core, validation, scikit-learn-api, duckdb]
summary: "Lessons from sql_learn_test (21–24 August 2026): scikit-learn's API copied exactly with a live scikit-learn as the oracle, DuckDB's parallel sums found non-reproducible, and no estimator built."
related: [docs/questions/archived/earlier-attempts/README.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md, docs/architecture/workflow.md]
---
# What does `sql_learn_test` teach the library core?

`sql_learn_test` is GitHub `glaucis/sql_learn` from 21 to 24 August 2026
(ROOT `sql_learn_test`, 59 commits): a restart two months after the war room
stopped. Two batches read it; the notes, with citations as `OLD:path:Lnn`,
are in [notes/](notes/): [product and research](notes/A-product.md) and
[process](notes/B-process.md). Seven agent-only syntheses and most research
reports were read in part; the checklists say which.

## Summary

- **No estimator was built.** `src/sql_learn` holds only `__version__`; the
  tests check that importing the package loads no numpy, and a docstring gate
  skips while no estimator exists. 31 of 59 commits are `chore`.
- **scikit-learn's API, unchanged.** "Public API is identical to
  scikit-learn" meant its signatures, parameter and attribute names and the
  trailing underscore for fitted state; where the API and SQL disagree, the
  SQL changes (`OLD:architecture/sklearn-parity.md`). numpy, pandas and
  scikit-learn are banned from library code by ruff's `TID251`;
  `check_estimator` is not a target. This supports ADR 0003 as it stands.
- **The oracle is a live scikit-learn,** never values typed into tests, with
  tolerances to come from measured noise (none was ever fixed). The
  attempt's process notes argue tests-first as a way to limit what the code
  author sees, with the live call as the only independent oracle, then
  metamorphic checks, then a hand value with its origin.
- **The research was about running agents:** 17 topics sent to two models
  with identical briefs, 17 syntheses and 3 audits; none studied
  scikit-learn's API, DuckDB or the earlier attempts.
- **Mechanical gates:** a before-and-after hash of the test suite and
  configuration, closing the ways a test can be quietly weakened; a runtime
  tripwire that flags banned imports; a list of the ways round the linter
  (`.df()`, `.fetchdf()`, `.arrow()`, `importlib`, `# noqa`). The agent
  pipeline built around them "has never run end to end".

## DuckDB facts, checked on 2.0.0

| Behaviour | Result | Consequence |
|---|---|---|
| `SUM`, `AVG`, `STDDEV_POP` over 3,000,000 doubles, 8 threads, run twice | differ in the last digits each run; `fsum` too | learned values are not reproducible by default; measure at `threads=1` or bound the variation |
| the same at `threads=1` | identical | reproducible |
| `NaN = NaN`, `NaN > 1e308` | true, true | NaN is equal to itself and sorts above every number |
| `ORDER BY x DESC` with NULL | NULL last | NULLs sort last in both directions |
| string order of `b`, `B`, `a`, `_` | `B`, `_`, `a`, `b` | byte order; it matches `np.unique` |
| `1 % 0` (integers) | error | integer division by zero raises; floating point gives `inf` or NaN |

The attempt also found that a column name passed as a query parameter
becomes a constant, and that `EXPLAIN` catches unknown columns before a query
runs.

## New against earlier reviews

- **Parity per method is not enough:** each method can match while
  `fit_transform` is wrong, so the whole estimator and the whole pipeline need
  comparing. This is the gap behind the fit defect in every earlier attempt.
- **Small fixtures hide errors:** a `ddof` mistake is 15% at n = 4 and 5e-6 at
  n = 100,000, small enough for a tolerance to swallow. Parity fixtures should
  be small as well as large.
- **An open point:** whether "SQL, not numpy" covers the small dense solve
  (normal equations, PCA's eigendecomposition).
- **For models fitted by iteration,** checks that need no reference: a
  one-sided objective comparison, residual orthogonality.
- **Pin scikit-learn and DuckDB exactly** for parity runs, and note the BSD-3
  notice owed when adapting scikit-learn's docstrings.
- **No sqlglot:** it was rejected as a SQL validator after accepting a
  trailing `GROUP BY` (not rechecked).

## Worth keeping

The exact scikit-learn API as the contract; the live oracle first, then
metamorphic checks, then a hand value with its origin; the test-suite hash
gate; the import tripwire and the list of ways round the linter; the NULL,
NaN, empty and single-row fixtures; reproduce twice and stop after two failed
attempts; a three-tier rule classification (mechanical, reviewable,
explained only).

## Guard against

The agent layer before the first estimator; mandatory hand-kept queues with
no checker; the same contract paragraph in seven files; gates that pass when
empty; research figures nobody rechecked; a repository-wide `git checkout`
that lost uncommitted work.

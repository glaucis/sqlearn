---
type: question
tags: [earlier-attempts, library-core, planning, validation, specs]
summary: "Lessons from the April planning repo (glaucis/sqlearn-private, 9–24 April 2026): the most detailed specs and validation method of any attempt, no code, and the fit defect written down as the rule."
related: [docs/questions/earlier-attempts/README.md, docs/questions/earlier-attempts/sqlearn-v04/review.md, docs/questions/earlier-attempts/sqlearn_000/review.md, docs/questions/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# What does the April planning repo teach the library core?

The April planning repo is GitHub `glaucis/sqlearn-private` as it stood from
9 to 24 April 2026 (ROOT `sqlearn-ecosystem_old/sqlearn-private`, 593
commits). It ran alongside [v0.4](../sqlearn-v04/review.md), then on 13 April
decided to call v0.4 "legacy" and restart greenfield
(`OLD:_old/TODO.md:L424-L441`); that restart is probably
[`sqlearn_000`](../sqlearn_000/review.md) (inference). Its copy of v0.4
(`_old_sqlearn/`) was skipped. Five batches read the rest; the notes, with
citations as `OLD:path:Lnn`, are in [notes/](notes/):
[direction](notes/A-direction.md), [core specs](notes/B-core-specs.md),
[transformer specs](notes/C-transform-specs.md),
[test specs](notes/D-test-specs.md) and
[ideas and process](notes/E-ideas-process.md). `CONSTITUTION.md` and the
`standards/` pages it cites are missing from this copy.

## Summary

- **No code, a great deal of specification.** From 12 April the repository
  held documents only: per-module specs for the core (about 10,700 lines),
  77 transformer specs, 60 test specs and a validation framework. About two
  thirds of the commits were about the process (392 of 593 by keyword; 91
  only ticked a box).
- **The fit defect is the written rule.** A layer ends only after a learning
  step that changes the schema, and the worked examples batch Impute and Scale
  into one query over the same input
  (`OLD:_old/projects/sqlearn/src/compiler/layers.md:L56-L77`). A golden SQL
  file freezes the wrong scale, a query-count test requires Impute, Scale,
  MinMaxScale, Winsorize and RobustScale to fit in one query, and an ordering
  warning recommends Impute before Scale: the order the rule gets wrong. The
  README even argues that a staged query cannot work, which the `WITH` check in
  the v0.4 review disproves.
- **The strongest validation method of any attempt, on paper only:** exact
  references (40- to 50-digit `Decimal`, `Fraction`, `mpmath`) from a cited
  primary source, never another library; error in ULPs through a five-layer
  tolerance cascade (default 4 ULP, values guessed); bundled Parquet plus
  seeded generated data; a merge gate and a release gate. None of it was
  built. Pipeline-level parity was again absent: `Pipeline` is marked "n/a"
  and the one-column validator template cannot express one.
- **The API renaming was "settled" here.** NAMING-REVIEW fixed `learn`,
  `apply`, `sql`, verb class names and `data`/`target`/`columns`, dropped
  `fit_transform` and replaced `get_params` with `to_config`; all 15 of its
  open questions have blank decision lines.
- **The v2 direction (21 April), "the user typed it, the user gets it":** NULL
  kept as NULL by default; one `drop_nulls` output filter that fit ignores;
  safe named siblings for restricted-domain steps (`Log`), whose errors name
  three remedies; risk warnings moved to the paid tier.
- **Status was kept in many places and torn down twice.** An orchestration
  pipeline built on 20 April was removed on 23 April with its protocols,
  agents and memories; hooks and subagents were switched off on 22 April as
  "chaos".

## New against earlier reviews

- **`where=` on a learning step limits fit scope** as
  `AGG(x) FILTER (WHERE …)`, a precise meaning for an otherwise vague
  universal parameter.
- **Cross-validation overwrote each fold's learned state** on the shared
  transformer instances, which led to a parked `FitSnapshot` design: fitted
  state must not live only on the step objects.
- **Cross-validation in one scan was designed in full**
  (`OLD:_old/projects/sqlearn/src/helpers/explore_caching.md`): per-fold
  `FILTER (WHERE __sq_fold__ != :k)` aggregates in a `stats` CTE joined with
  `CROSS JOIN`, two-phase discovery so the category universe comes from all
  training data, and a test that each aggregate equals its subset result.
- **A frozen artefact:** the compiled SQL text with two SHA-256 fingerprints,
  version fields and strict schema checking.
- **The only multi-engine design of any attempt** (the federated "pro" spec):
  other sources through DuckDB `ATTACH`, a coordinator rejected, and a
  Welford/partial-merge table for per-partition statistics. It keeps the fit
  defect and makes statistics per source by default. The repo admits
  transpilation is "syntactic, not semantic".
- **Grouped statistics leaked into transform on purpose.** `FrequencyEncode`,
  `GroupAggregate` and the `group_by` design compute
  `AVG(...) OVER (PARTITION BY ...)` at apply time; "static" meant "has no fit
  query", not "uses no data statistics". `CountEncode` is the learned
  alternative.
- **Row-count-changing steps** (`Filter`, `Sample`, `Deduplicate`, outlier
  removal, inner `Lookup`) get only an alignment warning: no fit-only rule and
  no `y` alignment.
- **A transformer contract with 12 edge cases** (SQL keywords and Unicode as
  column names, NaN against NULL), a read-only source-table invariant, and
  query-count tests.
- **`custom()` with `learn={name: aggregate template}`** and contract checks,
  and `CollapseRare`'s options matrix turned into tests.

## DuckDB facts, checked on 2.0.0

| Behaviour | Result | Consequence |
|---|---|---|
| `AVG`, `STDDEV_POP` and `/` of `DECIMAL(38,18)` | `DOUBLE` | a `DECIMAL` precision mode silently returns to floating point |
| `DECIMAL(38,18)` × `DECIMAL(38,18)`, 200 × 3 | overflow error | the specified precision mode cannot multiply |
| `44.2`, `1e-20` as literals | `DECIMAL(3,1)`, `DOUBLE` | learned floats need an explicit literal rule |
| `TRIM` of tab-`a`-newline | length 3 | `TRIM` removes spaces only |
| `5 / 2`, `5 // 2` | 2.5, 2 | bit arithmetic needs `//` |
| `VAR_POP` over all NULL | NULL | not 0, as a spec assumed |
| `POW(0, -1)` | `inf` | no error is raised |
| `PERCENTILE_CONT(0.25) WITHIN GROUP …`, `QUANTILE_CONT(x, 0.25)` | equal | either name is the interpolating form |
| `rel.fetchone()` | removed | a relation reruns on each call; use `fetchall()` |

## Contradictions inside the repo

The specs disagree with the code and with each other: `RobustScale` with IQR
0 gives NULL in the spec and 0 in the code (scikit-learn uses scale 1);
`PowerScale` claims maximum likelihood, the code used a skewness grid; query
counts are "2 regardless" in one place and "2k + 1" in another; the manifest
says `StandardScaler` divides by n − 1 (it does not); contract test 9 uses
`rtol=1e-6` against the spec's own ULP cascade; the v0.2 notes claim five
engines tested. Its licence plan (MIT with a proprietary tier inside), its
opt-in telemetry service, pandas for exploration and "preprocessing only, no
GUI" all conflict with this repository's ADRs and overview.

## Worth keeping

- The v2 rules: NULL preserved by default, safe named siblings, errors that
  name the remedies, a determinism rule for expressions.
- `where=` as fit scope, through `FILTER`.
- Fitted state held apart from the step objects, so folds and refits cannot
  overwrite it.
- The one-scan cross-validation design, with the category universe frozen
  separately from per-fold statistics.
- The validation framework as a design: exact references from primary
  sources, ULP reporting, bundled and generated data, a gate. It needs a
  pipeline-level validator and measured, not guessed, tolerances.
- The 12-case edge contract, the read-only source invariant, query-count
  tests, and the frozen artefact with fingerprints.
- Plain `logging` with no telemetry; one error root with message, context and
  hint.

## Guard against

Process that outgrows the product (two thirds of 593 commits); checkbox plans
that need plans of their own; rewrites after drafting at scale; an
instruction file that grew to 690 lines; specifications that outrun any code
and so are never tested; guessed tolerances presented as a method.

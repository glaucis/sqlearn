---
type: question
tags: [earlier-attempts, library-core, fit, learned-state, sqlglot, validation]
summary: "Lessons from Tomosius/sqlearn, the first built sqlearn (March 2026): the fit defect was diagnosed in writing and kept, and v0.4 later broke several things this attempt had working."
related: [docs/questions/archived/earlier-attempts/README.md, docs/questions/archived/earlier-attempts/ducklearn/review.md, docs/questions/archived/earlier-attempts/sqlearn-v04/review.md, docs/questions/archived/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# What does `Tomosius/sqlearn` teach the library core?

`Tomosius/sqlearn` is the first built sqlearn: GitHub `Tomosius/sqlearn`, 271
commits from 13 March to 9 April 2026, read from its working copy (ROOT
`sqlearn-desktop`, 378 files) and the history of its git copy (ROOT
`test/sqlearn`). It implemented [ducklearn](../ducklearn/review.md)'s design,
and [v0.4](../sqlearn-v04/review.md) grew out of it. Five batches read it; the
notes, with citations as `OLD:path:Lnn`, are in [notes/](notes/):
[design](notes/A-design.md), [core code](notes/B-core.md),
[tests](notes/C-tests.md), [user docs](notes/D-docs.md) and
[process](notes/E-process.md).

## Summary

- **The fit defect was known and kept.** A rejected idea of 17 March says a
  scaler after an imputer must learn from imputed values
  (`OLD:ideas/rejected/query-template-single-pass.md:L13-L19`); the compiler
  still batches `MEDIAN(price)`, `AVG(price)` and `STDDEV_POP(price)` over raw
  data (`OLD:architecture/design/compiler.md:L207-L226`). A SQL snapshot
  freezes the result and a test loosened to `atol=0.1` hides it.
- **It was half fixed here, and v0.4 lost the half.** The output of steps that
  learn nothing is substituted into later aggregates (`AVG(LN(x + 1))`); the
  output of learning steps is not, and set queries (`DISTINCT`) never see any
  upstream step, so `Lower` then `OneHotEncoder` would learn the raw
  categories (inference). v0.4 dropped the substitution.
- **The `WITH` fix was already on file**, as an optimisation idea from
  ducklearn, never as the correctness rule
  (`OLD:ideas/active/base-features.md:L197-L207`).
- **scikit-learn's names were kept**, with `get_params`, `set_params` and
  `clone`, and parameters were routed by `(step index, parameter)` tuples
  rather than strings split on `__`. v0.4 renamed the methods and moved to
  string keys.
- **Learned state was also designed as a relation.** For cross-validation a
  `stats` CTE is joined with `CROSS JOIN`, with `FILTER (WHERE fold != k)` per
  fold, and per-fold DuckDB tables were designed as a cache. Saving was pickle
  only, and a refit kept stale keys.
- **sqlglot was a decision** ("multi-database from day one"). The v30 break
  (292 type errors, the `<30` pin) and the shared-AST-node bugs start here.
- **Validation was thin:** about 40 of 2,600 test functions compare against
  scikit-learn, each transformer alone; RobustScaler at `atol=0.5`; no CI;
  Hypothesis installed and unused. No attempt so far ever compared a whole
  pipeline with scikit-learn's.
- **Process:** a burst of code from 13 to 18 March, then "approach under
  review" and 21 days of silence. Status was kept by hand in four places
  (backlog file, issues, milestones, project board).

## Against v0.4

v0.4 broke four things this attempt had working: substitution of upstream
expressions into aggregates, structured parameter routing, correct
intermediate views and a working `Columns`. It added JSON config, training
schema validation and a row id. This attempt also wired automatic CTE
promotion for deep expressions (deeper than 8 nodes), which v0.4 kept as dead
code, and its snapshot helper failed on a missing snapshot where v0.4's wrote
one and passed.

## New against earlier reviews

- **Planning used schemas from before fit and never redid them.** Steps whose
  output columns depend on learned values (Ordinal, Frequency, window steps,
  AutoDatetime, Union) planned with stale schemas (inference).
- **Standalone transformers could not fit;** only `Pipeline` could.
- **The project database was agent tooling, not library state:** code
  inventory, backlog, ideas and audit findings in DuckDB, queried by agents
  through an MCP server, abandoned unfinished on 19 March.
- **A separate review sweep after a build burst found real bugs** the
  per-module tests had missed: shared AST nodes, a wrong default type,
  unquoted columns and 23 type errors.
- **The docs' numbers were typed by hand, and several are wrong.** The guide
  prints the imputed-data standard deviation (0.8165 for 10, NULL, 8) where
  the code computes the raw one (1.0); two tutorials disagree. The new site
  needs executed examples.
- **Accepted divergences were tested as such:** a test asserts both
  scikit-learn's value and sqlearn's, with the reason (constant column, all
  NULL, single row).

## Semantics defects

Discrete `QUANTILE` beside interpolating `MEDIAN`; `MODE` without a
tie-break; `LEAST`/`GREATEST` turning NULL into the clip bound (all three
confirmed on DuckDB 2.0.0 in the v0.4 review); zero-scale columns becoming
NULL; a Box-Cox lambda from a heuristic, not maximum likelihood; `Sample`
ignoring its seed; `Deduplicate` ordering by a constant; the target column
never excluded from selectors or output.

## Worth keeping

- "If a step cannot be proved free of learned state, treat it as learning",
  and a guard that raises when a stateless step reads learned values.
- A test that each aggregate with `FILTER (WHERE fold != k)` equals the same
  aggregate over the physical subset. Checked on DuckDB 2.0.0 for `MEDIAN`,
  `QUANTILE_CONT` and `MODE … ORDER BY`: equal.
- Parameters addressed by structured keys, not strings.
- A hash of the generated SQL saved with a pipeline. Whether DuckDB's `HASH` is
  stable across versions is unverified; do not rely on it for saved results.
- Divergence tests with reasons, SQL reserved words as column names in a
  standing fixture, golden SQL snapshots that fail when missing.
- For the site: Python and generated SQL side by side, one page per
  component with formula and SQL, a "chose, why, alternatives, trade-offs"
  template for decisions.
- Commit rules, quoting every identifier, copying AST nodes, `NULLIF` on
  divisors, and a review sweep after each burst of building.

## Guard against

One fact tracked in several places; skills and agents that restate the
architecture docs; agents defined and never run; tooling for the process
(1,392 lines of project-database code) before the product works; hundreds of
ideas (475 brainstormed) before the core is settled.

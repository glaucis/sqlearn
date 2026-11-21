---
type: adr
tags: [exploration, eda, api, relations, pandas, results]
summary: "Records that sq.explore's functions run on the data when called and return DuckDB relations in long form, follow pandas' statistical conventions, and keep each small answer in a temporary table on the connection."
related: [docs/specs/library-exploration.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# 0059: Exploration functions run now and return relations

Status: accepted (2026-11-20), with the
[exploration spec](../specs/library-exploration.md). Written from the
agent's calls, which Tomas approved with the spec on 2026-11-20.

## Context

The exploration module (overview 3.6) answers questions about a dataset
before a pipeline is built: what each column holds, how much is missing,
which columns move together. Its answers are read in a notebook, by a
program, and later by the exploration application. Three choices shape every
function in it: whether a function is a step or runs at once, what it hands
back, and whose definitions of the statistics it follows.

## Decision

- **The functions run when called**, as the metrics do: nothing is learned
  for later, so they are not steps, take no part in a pipeline, the learning
  store or `sq.save`.
- **Each returns a DuckDB relation in long form** (one row per column, pair,
  bin, value or pattern), handed over through `out=` as `apply` is
  ([ADR 0023](0023-lazy-results-out-and-feed.md)), with the session's `out`
  setting as the default. No result class: the relation is what sqlearn
  already hands back, it shows itself in a notebook, and the application
  reads the same thing.
- **The statistics follow pandas**, the tool users compare against: `std`
  with one degree of freedom, sample-adjusted skewness and excess kurtosis,
  quartiles by linear interpolation; NULL and NaN are both missing.
- **The group is `sq.explore`.**

## Consequences

- Unlike `apply`, the answer is computed at the call: each is materialised
  into a small temporary table on sqlearn's connection, so it stays valid
  after its input is gone (a pandas frame's registration is released
  later). The tables are the size of the answer and live as long as the
  connection.
- Rows never reach Python, only answers (ADR 0002).
- Exact by default; approximate quantiles and distinct counts only when the
  user passes `exact=False` (ADR 0046).

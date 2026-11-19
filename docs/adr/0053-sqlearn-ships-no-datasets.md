---
type: adr
tags: [datasets, scope, packaging, licensing, api, development]
summary: "Records that sqlearn ships, generates and fetches no datasets: the user brings their own. The former sq.datasets moves to devdata/ at the repository root, for developing sqlearn only, outside the wheel and the sdist, and the package never imports it."
related: [docs/adr/0045-datasets-are-relations-built-in-sql.md, docs/adr/0052-meta-sqlearn.md, docs/adr/0006-local-and-offline.md, docs/architecture/layout.md]
---
# 0053: sqlearn ships no datasets

Status: accepted (2026-11-18). Issue #61. Replaces the public `sq.datasets` of
[ADR 0045](0045-datasets-are-relations-built-in-sql.md), moves
[ADR 0052](0052-meta-sqlearn.md)'s `meta_sqlearn` out of the package, and
replaces the line on example datasets in
[ADR 0006](0006-local-and-offline.md).

## Context

`sq.datasets` held three bundled real datasets (`iris`, `wine`,
`breast_cancer`, CC BY 4.0) and four generators (`blobs`, `classification`,
`regression`, `customers`). A next step under discussion was a fetcher of real
datasets.

Datasets and the library that processes them are separate things: a car dealer
does not sell fuel. Someone who wants to use sqlearn has data, or can get it,
and DuckDB reads it directly. A commercial version is planned, and third-party
data in the package would bring its licence terms along. The project itself
still needs data to test and measure its code.

## Decision

- **sqlearn ships no datasets, generates none and fetches none.** The user
  brings their own. `sq.datasets` no longer exists.
- **`devdata/` at the repository root holds them for development:** the former
  package, with `meta_sqlearn` and its work tickets, its tests in
  `tests/devdata/` and its validation in `validation/devdata/`. Tests,
  validation and benchmarks may import it.
- **It never ships.** The wheel and the sdist take only `src/`, and code under
  `src/` never imports `devdata`; a test holds the package to this.
- **The published documentation does not use it,** because a reader does not
  have it: a page builds a small table, or uses a dataset from a library the
  example already imports.

## Consequences

- The public API and the package are smaller, and no third-party data is
  distributed with sqlearn.
- The repository still holds the three real datasets with their credits, in
  `devdata/data/`.
- A new user needs a table before a first pipeline; the guide's examples show
  small ones.

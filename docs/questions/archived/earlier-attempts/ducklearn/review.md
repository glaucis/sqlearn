---
type: question
tags: [earlier-attempts, library-core, design, fit, cross-validation]
summary: "Lessons from ducklearn, the first design of sqlearn (March 2026, no code): the layered fit and its defect start here, and so do per-fold statistics in one scan."
related: [docs/questions/archived/earlier-attempts/README.md, docs/questions/archived/earlier-attempts/sqlearn-v04/review.md, docs/questions/archived/fit-execution-model.md, docs/questions/validation-method.md]
---
# What does ducklearn teach the library core?

ducklearn (ROOT `ducklearn`, 13 March 2026, no git) is the first design of the
project: 14 documents, 132 numbered decisions, an agent guide, and no code.
Every later attempt descends from it, and v0.4 implemented most of it. One
batch read all of it; the notes, with citations as `OLD:path:Lnn`, are in
[notes/A-design.md](notes/A-design.md).

## Summary

- **The design is v0.4's, earlier.** One `Transformer` base with `discover()`
  (scalar aggregates), `discover_sets()` (categories), `expressions()`,
  `query()` and `output_schema()`; steps compose as dicts of sqlglot ASTs into
  one SELECT; fit runs one batched query per layer with a temp view between
  layers; transform is one query with learned values as literals.
- **The fit defect starts here.** A layer ends only after a schema-changing
  learning step (`OLD:docs/04-compiler.md:L190-L193`), so Imputer then
  StandardScaler share a layer and the scaler learns from raw data; the
  document's own audit example shows it.
- **The API kept scikit-learn's names.** `fit`, `transform`, `fit_transform`,
  `get_params` and `set_params` stay (`OLD:docs/03-architecture.md:L96-L140`);
  the departures are `y` as a column name, `fit` taking a data source, the
  `Columns` and `Union` classes and the `+` operator. The renaming to
  `learn`/`apply` came later, in v0.4.
- **Validation was weak from the start:** scikit-learn as the reference with
  one fixed `atol=1e-10` (`OLD:docs/14-decisions.md:L8`), no exact
  arithmetic and no measured bounds. The stronger written method came in v0.4.
- **Data was synthetic**, generated in the repository; no downloads.
- **A commercial plan** put a signed offline licence key for "Pro" features
  inside the MIT package (`OLD:docs/11-business-model.md`), which ADR 0004 now
  rules out.

## New ideas

- **Per-fold statistics in one scan.** `AVG(x) FILTER (WHERE fold != k)` for
  each fold k in one query, with a test that the filtered aggregate equals the
  aggregate over a physical subset (`OLD:docs/03-architecture.md:L1696-L1744`,
  `OLD:docs/13-testing.md:L323-L341`). Checked on DuckDB 2.0.0: works. Bears on
  the fit question and on model selection (overview 3.3).
- **A stable output schema across folds** ("two-phase discovery"), so every
  fold yields the same columns (`OLD:docs/03-architecture.md:L1746-L1873`).
- **Static/dynamic classification proved in CI** for built-in steps, both
  branches tested for steps that are static only under some parameters
  (`OLD:docs/03-architecture.md:L499-L582`).
- **A runtime guard** (`_FrozenEmptyParams`) that raises when a static step
  reads learned state, turning "fit leaked into transform" into an error at
  first use (`OLD:docs/03-architecture.md:L1080-L1143`).
- **Baked and self-contained SQL** as two outputs of one composer: literals for
  normal runs, learned values computed inside the query for cross-validation.
- **A frozen, hashed artefact**: readable YAML with fitted values and both
  schemas, plus a hash of the SQL to detect silent change
  (`OLD:docs/08-export.md:L29-L181`).
- **`to_explicit()`** to freeze automatic choices so they cannot drift between
  versions (`OLD:docs/05-transformers.md:L521-L552`).
- **For the exploration app:** every chart is a small SQL result and the
  browser never receives raw rows (`OLD:docs/07-analysis.md:L349-L369`); a
  drag-and-drop builder that generates code, an ancestor of the node editor.

## Cautions

- The documents contradict each other and were never reconciled: an
  `__array__` wrapper against "no `__array__` magic"; OneHot dense in two
  places and sparse in two; the Imputer median written as `AVG`.
- Its commit-skill template adds a `Co-Authored-By` trailer, which this
  repository forbids; do not copy it.
- Python 3.10, numpy and sqlglot at runtime, and eight more packages for the
  studio extra: against ADRs 0005 and 0007.

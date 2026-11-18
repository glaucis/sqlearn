---
type: note
tags: [decision-records, adr, index, sqlearn, architecture]
summary: "Index of sqlearn decision records (ADRs), grouped by topic such as tooling, execution in DuckDB, the API, and validation."
mdindex: [type=edb465, tags=af7fe9, summary=e1bff3, related=14668e]
related: [docs/adr/0001-uv-for-python-packaging.md, docs/adr/0004-apache-2-licence.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/adr/0007-python-3-12-floor.md, docs/adr/0008-just-task-runner.md, docs/adr/0010-british-prose-american-identifiers.md, docs/adr/0025-results-stored-as-data-in-mirrored-folders.md]
---

# Decision records

The decisions that shape sqlearn, one record each, numbered as they land
and grouped here by topic. A record may sit under more than one topic.

## Project and tooling

How sqlearn is built, licensed and checked.

- [0001: uv for Python packaging](0001-uv-for-python-packaging.md)
- [0004: Apache-2.0 licence](0004-apache-2-licence.md)
- [0005: One runtime dependency, each one justified](0005-runtime-dependencies.md)
- [0006: Local and offline](0006-local-and-offline.md)
- [0007: Python 3.12 as the floor](0007-python-3-12-floor.md)
- [0008: just as the task runner](0008-just-task-runner.md)
- [0010: British prose, American identifiers](0010-british-prose-american-identifiers.md)
- [0025: Results stored as data, in folders that mirror the package](0025-results-stored-as-data-in-mirrored-folders.md)

## Documentation and learning

- [0009: One Sphinx site for documentation and learning](0009-sphinx-documentation-site.md)
- [0011: Three curriculum levels with fixed URLs](0011-curriculum-levels.md)

## Execution in DuckDB

Computation as SQL, and how a pipeline becomes runs.

- [0002: SQL on DuckDB as the execution engine](0002-sql-on-duckdb-execution-engine.md)
- [0012: Static and dynamic steps decide how learning runs](0012-static-and-dynamic-steps.md)
- [0015: DuckDB's expression objects, no sqlglot](0015-duckdb-expressions-no-sqlglot.md)
- [0018: Runs follow the chains between steps](0018-runs-follow-the-chains-between-steps.md)
- [0023: Lazy results, `out=` and `feed=`](0023-lazy-results-out-and-feed.md)
- [0052: sqlearn's own tables live in `meta_sqlearn`](0052-meta-sqlearn.md)

## The API

The verbs and conventions users write against.

- [0003: scikit-learn-style API](0003-scikit-learn-style-api.md)
- [0013: learn, apply, train and predict](0013-learn-apply-train-predict.md)
- [0020: Column selectors](0020-column-selectors.md)
- [0026: A step without `cols=` works on every column](0026-a-step-without-cols-works-on-every-column.md)
- [0034: A grouped API](0034-a-grouped-api.md)
- [0035: Names of generated columns](0035-names-of-generated-columns.md)
- [0045: Datasets are relations built in SQL](0045-datasets-are-relations-built-in-sql.md)
- [0046: sqlearn warns, the user chooses](0046-sqlearn-warns-the-user-chooses.md)
- [0047: A pipeline saves as JSON](0047-a-pipeline-saves-as-json.md)
- [0048: The user saves the model and imports its packages](0048-the-user-saves-the-model-and-imports-its-packages.md)

## Steps users write

- [0019: Custom steps, and feedback when a run fails](0019-custom-steps-and-failure-feedback.md)
- [0026: A step without `cols=` works on every column](0026-a-step-without-cols-works-on-every-column.md)
- [0027: A user's step may declare itself dynamic](0027-a-user-step-may-declare-itself-dynamic.md)
- [0028: A step returning a mapping counts as dynamic](0028-a-step-returning-a-mapping-counts-as-dynamic.md)
- [0037: Four additions to the step contract](0037-four-additions-to-the-step-contract.md)

## Inputs and the learning store

- [0014: Learned values live in a store while the program runs](0014-learning-store.md)
- [0021: Inputs, and how the store recognises them](0021-inputs-and-how-the-store-knows-them.md)
- [0024: Store keys follow what a step reads](0024-store-keys-follow-what-a-step-reads.md)
- [0029: Relations from another connection are refused](0029-relations-from-another-connection-are-refused.md)

## Models and search

- [0017: Models come from other libraries, for now](0017-models-from-other-libraries.md)
- [0022: One search, with pluggable methods](0022-one-search-with-pluggable-methods.md)
- [0031: The defaults warning is about what to search](0031-the-defaults-warning-is-about-what-to-search.md)
- [0039: The search's names as groups](0039-the-search-names-as-groups.md)
- [0040: Fold schemes as SQL over rows](0040-fold-schemes-as-sql-over-rows.md)
- [0041: The hand-over](0041-the-hand-over.md)
- [0042: A metric's settings are a call](0042-a-metrics-settings-are-a-call.md)
- [0043: Repeatable within rounding](0043-repeatable-within-rounding.md)
- [0049: Table metrics are relations](0049-table-metrics-are-relations.md)
- [0050: predict_proba keeps the target](0050-predict-proba-keeps-the-target.md)
- [0051: Aggregates learn in levels](0051-aggregates-learn-in-levels.md)

## Numerics and validation

Accuracy, and how it is measured.

- [0016: Validation against the mathematics and every comparable library](0016-validation-method.md)
- [0030: Infinity is refused](0030-infinity-is-refused.md)
- [0032: The median is exact, by sorting](0032-the-median-is-exact-by-sorting.md)
- [0033: The mean is summed with compensation](0033-the-mean-is-summed-with-compensation.md)
- [0036: Staged aggregates anywhere in a learned value](0036-staged-aggregates-anywhere-in-a-learned-value.md)
- [0038: The target encoder's inner folds follow row position](0038-the-target-encoders-inner-folds-follow-row-position.md)
- [0044: The standard deviation in two staged passes](0044-the-standard-deviation-in-two-staged-passes.md)

```{toctree}
:hidden:
:glob:

0*
```

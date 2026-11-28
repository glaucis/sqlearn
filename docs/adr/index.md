---
type: architecture
tags: [adr, decisions, index, sqlearn, catalogue]
summary: "Index of sqlearn architecture decision records, grouped by topic such as tooling, DuckDB execution, the native C++ engine, the API, and numerics."
mdindex: [type=4ca303, tags=5eb697, summary=d97c88, related=3d970d]
related: [docs/adr/0001-uv-for-python-packaging.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0070-sqlearn-is-rewritten-in-cpp.md, docs/adr/archived/0067-how-computation-moves-to-the-engine.md, docs/adr/0073-the-old-python-moves-to-old-python.md]
---

# Decision records

The decisions that shape sqlearn, one record each, numbered as they land
and grouped here by topic. A record may sit under more than one topic.

## Project and tooling

How sqlearn is built, licensed and checked.

- [0001: uv for Python packaging](0001-uv-for-python-packaging.md)
- [0004: Apache-2.0 licence](0004-apache-2-licence.md)
- [0005: Runtime dependencies, each one justified](0005-runtime-dependencies.md)
- [0057: numpy is a runtime dependency](0057-numpy-is-a-runtime-dependency.md)
- [0006: Local and offline](0006-local-and-offline.md)
- [0007: Python 3.12 as the floor](0007-python-3-12-floor.md)
- [0008: just as the task runner](0008-just-task-runner.md)
- [0080: The engine stays on CMake for now](0080-the-engine-stays-on-cmake-for-now.md)
- [0010: British prose, American identifiers](0010-british-prose-american-identifiers.md)
- [0025: Results stored as data, in folders that mirror the package](0025-results-stored-as-data-in-mirrored-folders.md)

## Documentation and learning

- [0009: One Sphinx site for documentation and learning](0009-sphinx-documentation-site.md)
- [0011: Three curriculum levels with fixed URLs](0011-curriculum-levels.md)

## Execution in DuckDB

Computation as SQL, and how a pipeline becomes runs.

- [0002: SQL on DuckDB as the execution engine](0002-sql-on-duckdb-execution-engine.md)
- [0015: DuckDB's expression objects, no sqlglot](0015-duckdb-expressions-no-sqlglot.md)
- [0058: A Gram step builds XᵀX in numpy](0058-a-gram-step-builds-xtx-in-numpy.md)
- [0023: Lazy results, `out=` and `feed=`](0023-lazy-results-out-and-feed.md)
- [0074: How a pipeline learns: static and dynamic steps, and its runs](0074-how-a-pipeline-learns.md)

## The native engine

sqlearn's computation in C++, inside its own DuckDB build.

- [0060: sqlearn is a C++ library, and Python its bindings](0060-a-native-engine-in-cpp-inside-duckdb.md)
- [0061: sqlearn ships its own DuckDB build](0061-sqlearn-ships-its-own-duckdb-build.md)
- [0062: Apple silicon first, a safe CPU build elsewhere](0062-apple-silicon-first.md)
- [0063: The engine's compute libraries: Accelerate, OpenBLAS and Metal](0063-the-engines-compute-libraries.md)
- [0064: The GPU runs by itself only when the answer is the same](0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)
- [0065: Safety rules for the C++](0065-safety-rules-for-the-cpp.md)
- [0066: Permissive licences, never copyleft](0066-permissive-licences-never-copyleft.md)
- [0068: sqlearn's own models, in the engine](0068-sqlearns-own-models.md)
- [0069: The crash handler hands the fault on](0069-the-crash-handler-hands-the-fault-on.md)
- [0070: sqlearn is rewritten in C++](0070-sqlearn-is-rewritten-in-cpp.md)
- [0071: Fused multiply-add only on purpose](0071-fused-multiply-add-only-on-purpose.md)
- [0072: Benchmarks run on Tomas's go-ahead](0072-benchmarks-run-on-tomass-go-ahead.md)
- [0073: The old Python moves to `old_python/`](0073-the-old-python-moves-to-old-python.md)

## The API

The verbs and conventions users write against.

- [0003: scikit-learn-style API](0003-scikit-learn-style-api.md)
- [0013: learn, apply, train and predict](0013-learn-apply-train-predict.md)
- [0020: Column selectors](0020-column-selectors.md)
- [0034: A grouped API](0034-a-grouped-api.md)
- [0035: Names of generated columns](0035-names-of-generated-columns.md)
- [0046: sqlearn warns, the user chooses](0046-sqlearn-warns-the-user-chooses.md)
- [0053: sqlearn ships no datasets](0053-sqlearn-ships-no-datasets.md)
- [0059: Exploration functions run now and return relations](0059-exploration-functions-run-now-and-return-relations.md)
- [0079: Saving a pipeline: JSON, sqlearn's part only, nothing imported](0079-saving-a-pipeline.md)

## Steps users write

- [0055: A target step need not cross-fit](0055-a-target-step-need-not-cross-fit.md)
- [0075: The contract of a user's own step](0075-the-contract-of-a-users-own-step.md)

## Inputs and the learning store

- [0029: Relations from another connection are refused](0029-relations-from-another-connection-are-refused.md)
- [0076: The learning store and its keys](0076-the-learning-store-and-its-keys.md)

## Models and search

- [0017: Models come from other libraries, for now](0017-models-from-other-libraries.md)
- [0039: The search's names as groups](0039-the-search-names-as-groups.md)
- [0040: Fold schemes as SQL over rows](0040-fold-schemes-as-sql-over-rows.md)
- [0041: The hand-over](0041-the-hand-over.md)
- [0042: A metric's settings are a call](0042-a-metrics-settings-are-a-call.md)
- [0043: Repeatable within rounding](0043-repeatable-within-rounding.md)
- [0049: Table metrics are relations](0049-table-metrics-are-relations.md)
- [0054: D² Tweedie on a constant target](0054-d2-tweedie-on-a-constant-target.md)
- [0050: predict_proba keeps the target](0050-predict-proba-keeps-the-target.md)
- [0077: The search: one function, pluggable methods, defaults and the defaults warning](0077-the-search.md)

## Numerics and validation

Accuracy, and how it is measured.

- [0016: Validation against the mathematics and every comparable library](0016-validation-method.md)
- [0030: Infinity is refused](0030-infinity-is-refused.md)
- [0038: The target encoder's inner folds follow row position](0038-the-target-encoders-inner-folds-follow-row-position.md)
- [0078: How aggregates learn: exact quantiles by sorting, compensated sums, levels](0078-how-aggregates-learn.md)

## Archived

Records that no longer hold: superseded, or about only the old Python. Each
keeps its number; its status line says why it was archived.

- [0012: Static and dynamic steps decide how learning runs](archived/0012-static-and-dynamic-steps.md):
  superseded by ADR 0074.
- [0014: Learned values live in a store while the program runs](archived/0014-learning-store.md):
  superseded by ADR 0076.
- [0018: Runs follow the chains between steps](archived/0018-runs-follow-the-chains-between-steps.md):
  superseded by ADR 0074.
- [0019: Custom steps, and feedback when a run fails](archived/0019-custom-steps-and-failure-feedback.md):
  superseded by ADR 0075.
- [0021: Inputs, and how the store recognises them](archived/0021-inputs-and-how-the-store-knows-them.md):
  superseded by ADR 0076.
- [0022: One search, with pluggable methods](archived/0022-one-search-with-pluggable-methods.md):
  superseded by ADR 0077.
- [0024: Store keys follow what a step reads](archived/0024-store-keys-follow-what-a-step-reads.md):
  superseded by ADR 0076.
- [0026: A step without `cols=` works on every column](archived/0026-a-step-without-cols-works-on-every-column.md):
  superseded by ADR 0074.
- [0027: A user's step may declare itself dynamic](archived/0027-a-user-step-may-declare-itself-dynamic.md):
  superseded by ADR 0075.
- [0028: A step returning a mapping counts as dynamic](archived/0028-a-step-returning-a-mapping-counts-as-dynamic.md):
  superseded by ADR 0075.
- [0031: The defaults warning is about what to search](archived/0031-the-defaults-warning-is-about-what-to-search.md):
  superseded by ADR 0077.
- [0032: The median is exact, by sorting](archived/0032-the-median-is-exact-by-sorting.md):
  superseded by ADR 0078.
- [0033: The mean is summed with compensation](archived/0033-the-mean-is-summed-with-compensation.md):
  superseded by ADR 0078.
- [0036: Staged aggregates anywhere in a learned value](archived/0036-staged-aggregates-anywhere-in-a-learned-value.md):
  superseded by ADR 0078.
- [0037: Four additions to the step contract](archived/0037-four-additions-to-the-step-contract.md):
  superseded by ADR 0075.
- [0044: The standard deviation in two staged passes](archived/0044-the-standard-deviation-in-two-staged-passes.md):
  superseded by ADR 0078.
- [0045: Datasets are relations built in SQL](archived/0045-datasets-are-relations-built-in-sql.md):
  `sq.datasets` was replaced by ADR 0053, and the code is in `old_python/`.
- [0047: A pipeline saves as JSON](archived/0047-a-pipeline-saves-as-json.md):
  superseded by ADR 0079.
- [0048: The user saves the model and imports its packages](archived/0048-the-user-saves-the-model-and-imports-its-packages.md):
  superseded by ADR 0079.
- [0051: Aggregates learn in levels](archived/0051-aggregates-learn-in-levels.md):
  superseded by ADR 0078.
- [0052: sqlearn's own tables live in `meta_sqlearn`](archived/0052-meta-sqlearn.md):
  its tables were the dataset generators', now in `old_python/devdata/`.
- [0056: Settings that only choose the output stay out of the learn key](archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md):
  superseded by ADR 0076.
- [0067: The library is ported to C++ piece by piece](archived/0067-how-computation-moves-to-the-engine.md):
  superseded by ADR 0070.

```{toctree}
:hidden:
:glob:

0*
archived/0*
```

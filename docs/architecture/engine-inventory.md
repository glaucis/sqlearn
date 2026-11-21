---
type: architecture
tags: [native-engine, migration, inventory, dependencies, port-order]
summary: "The port's map: every module of src/sqlearn with the phase that ports it to C++, what stays in the bindings, what it imports, and the profiling numbers that order Phase 4's groups."
related: [docs/specs/native-engine.md, docs/adr/0067-how-computation-moves-to-the-engine.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/benchmarks/engine-profile.md]
---
# The native engine's inventory

sqlearn is ported to a C++ library one piece at a time, with `main` green
([ADR 0067](../adr/0067-how-computation-moves-to-the-engine.md)). This page is
the port's map. It gives every module of `src/sqlearn` the phase that ports it,
the C++ that replaces it, what stays in the Python bindings, and what it imports
from the other modules. It then puts Phase 4's groups in order, from those
imports and from the [profiling page](../benchmarks/engine-profile.md). The
phases are the [spec's](../specs/native-engine.md) §4; the draft order this page
confirms is its §5.3.

## How to read it

- **Phase** is the phase whose merge deletes the module's Python: `2`, `3` or
  `4`. Some modules gain C++ earlier than that; the row says so.
- **The C++** starts with the module's Phase 4 group, **G1** to **G12**, which
  "The groups of Phase 4" below puts in order.
- **Stays in the bindings** is what the bindings keep: `sq.`'s names and
  docstrings, and the bridge to Python objects (outside models, Optuna, users'
  own steps, data frames). The bindings hold no logic (spec §3.1).
- **Depends on** lists every other module of `src/sqlearn` the module imports,
  read from its `import` lines. "(in a function)" marks an import made inside
  a function, "(types only)" one under `TYPE_CHECKING`, which is not run.
- **Evidence** cites the profiling page's rows, where there is a number. All
  its numbers were measured under a load of 10 to 17 on 8 cores, so they are
  estimates. A module with no row there was not profiled.

## The table

| Module | Phase | The C++ that replaces it | Stays in the bindings | Depends on | Evidence |
|---|---|---|---|---|---|
| `_gram.py` | 2 | The `sqlearn_gram` kernel: XᵀX of the centred columns as one parallel aggregate (Accelerate, OpenBLAS), in place of numpy summing batches. Where `check_fits` goes is Phase 2's spec's call | Nothing | `_errors.py`, `_expr.py`, `_feed.py`, `_memory.py` | [Gram learn](../benchmarks/engine-profile.md): Python's share 37%, 27%, 32% at 50, 200, 500 columns; `gram_matrix` the largest Python function (0.77 s, 5.01 s, 10.69 s); 8, 20, 44 statements |
| `_errors.py` | 4 | G1: the exception and warning types | The Python classes users catch, mapped from the C++ ones | none | Not profiled |
| `errors.py` | 4 | G1: none, it re-exports | All of it: `sq.errors`' names | `_errors.py` | Not profiled |
| `_expr.py` | 4 | G1: the expression helpers, building DuckDB's expressions | The helpers' results handed to Python steps as DuckDB expressions (the seam, spec §3.1) | none | Not profiled |
| `_names.py` | 4 | G1: the naming rule for created columns (ADR 0035) | Nothing | none | Not profiled |
| `_selectors.py` | 4 | G1: the selectors and their combinations | `sq.cols` and the kinds as Python objects, with their operators | none | Not profiled |
| `_group.py` | 4 | G1: how a group method reads its columns | The group namespaces' objects and their `repr` | `_errors.py`, `_selectors.py` | Not profiled |
| `fn.py` | 4 | G1: the column functions | `sq.fn`'s names and docstrings | `_expr.py` | Not profiled |
| `agg/aggregates.py` | 4 | G1: the aggregates, each by its name | Their names and docstrings | `_errors.py`, `_expr.py` | Not profiled |
| `agg/__init__.py` | 4 | G1: none, it re-exports | All of it: `sq.agg`'s names | `agg/aggregates.py` | Not profiled |
| `_config.py` | 4 | G2: the configuration and the connection | `sq.set_config`, `sq.get_config`; the user's connection passed through | `_errors.py`, `_memory.py` (in a function), `_output.py` (types only) | Not profiled |
| `_memory.py` | 4 | G2: the memory budget | Nothing | `_config.py`, `_errors.py` | Not profiled |
| `_inputs.py` | 4 | G2: reading an input into a relation and its data key | Data frames handed to DuckDB | `_config.py`, `_errors.py`, `_expr.py`, `_selectors.py` | Not profiled |
| `_step.py` | 4 | G3: the step contract the C++ steps implement | `sq.Step`, which users' own steps subclass, reached through the seam (spec §3.1) | `_selectors.py` | Not profiled |
| `_compose.py` | 4 | G3: the compositor, the one place SQL is rendered (ADR 0015), with the quantiles' sort (`_quantile_ctes`) | Nothing | `_errors.py`, `_expr.py`, `_names.py`, `_selectors.py`, `_step.py` | The quantiles' sort is the `median` row's statement: [widest steps](../benchmarks/engine-profile.md), WINDOW 156.55 s and 1108.31 s at 200 and 500 columns, 15.74 GB spilled at 500 |
| `_plan.py` | 4 | G3: the run planner | Nothing | `_diagnose.py`, `_errors.py`, `_names.py`, `_selectors.py`, `_step.py` | Not profiled |
| `_diagnose.py` | 4 | G3: the diagnosis of a failed run | Nothing | `__init__.py` (in a function), `_compose.py`, `_config.py`, `_errors.py`, `_expr.py`, `_memory.py`, `_step.py` | Not profiled |
| `_output.py` | 4 | G3: the output kinds and writing to files | The relation or data frame handed back | `_compose.py`, `_config.py`, `_errors.py` | Not profiled |
| `out.py` | 4 | G3: none, it re-exports | All of it: `sq.out`'s names | `_output.py` | Not profiled |
| `_model.py` | 4 | G4: the interface an outside model is reached through | The wrapper calling the outside model's methods | `_errors.py` | Not profiled |
| `_feed.py` | 4 | G4: the hand-over's batches and their numbered tables | The arrays handed to the model, and its predictions back | `_compose.py`, `_config.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_memory.py`, `_model.py`, `_selectors.py` | Not profiled |
| `_store.py` | 4 | G5: the learning store | The keys of a user's own step's settings, read through the seam | `_inputs.py`, `_step.py` | Not profiled |
| `_pipeline.py` | 4 | G5: the pipeline's learn and apply | `sq.Pipeline`'s names and docstrings | `_compose.py`, `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_feed.py`, `_gram.py`, `_inputs.py`, `_model.py`, `_output.py`, `_plan.py`, `_selectors.py`, `_step.py`, `_store.py` | [Gram learn](../benchmarks/engine-profile.md) and [widest steps](../benchmarks/engine-profile.md): every learn profiled runs through it |
| `preprocessing/_missing.py` | 4 | G6: the helpers of the steps that learn over present numbers | Nothing | `_errors.py`, `_expr.py`, `_step.py` | Not profiled |
| `preprocessing/_lookup.py` | 4 | G6: finding a value among learned categories | Nothing | `_errors.py`, `_expr.py` | Not profiled |
| `preprocessing/scale.py` | 4 | G6: the scaling steps | The `sq.scale` group's names and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/_missing.py` | [Widest steps](../benchmarks/engine-profile.md), `scale`: about 3.7 s and 13.8 s at 200 and 500 columns, one statement, Python's share 25% and 19% |
| `preprocessing/impute.py` | 4 | G6: the imputing steps | The `sq.impute` group's names and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/_missing.py` | [Widest steps](../benchmarks/engine-profile.md), `median`: about 21 s and 187 s at 200 and 500 columns, Python's share 1%; its sort is the compositor's |
| `preprocessing/bin.py` | 4 | G6: the binning steps | The `sq.bin` group's names and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/_missing.py`, `preprocessing/scale.py` | Not profiled |
| `preprocessing/features.py` | 4 | G6: the feature steps | The `sq.features` group's names and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/_missing.py`, `preprocessing/scale.py` | Not profiled |
| `preprocessing/transform.py` | 4 | G6: the transforming steps | The `sq.transform` group's names and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `fn.py`, `preprocessing/scale.py` | Not profiled |
| `preprocessing/onehot.py` | 4 | G6: the one-hot step | Its name and docstrings | `_expr.py`, `_group.py`, `_selectors.py`, `_step.py` | Not profiled |
| `preprocessing/ordinal.py` | 4 | G6: the ordinal step | Its name and docstrings | `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/_lookup.py` | Not profiled |
| `preprocessing/target.py` | 4 | G6: the target encoder | Its name and docstrings | `_compose.py`, `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `preprocessing/_lookup.py` | Not profiled |
| `preprocessing/_encode.py` | 4 | G6: none beyond the group's argument rules | The `sq.encode` group's names and docstrings | `_errors.py`, `_group.py`, `_selectors.py`, `preprocessing/onehot.py`, `preprocessing/ordinal.py`, `preprocessing/target.py` | Not profiled |
| `preprocessing/__init__.py` | 4 | G6: none, it re-exports | All of it: the steps' names | `preprocessing/bin.py`, `preprocessing/features.py`, `preprocessing/impute.py`, `preprocessing/onehot.py`, `preprocessing/ordinal.py`, `preprocessing/scale.py`, `preprocessing/target.py`, `preprocessing/transform.py` | Not profiled |
| `feature_selection/_scores.py` | 4 | G7: the scores' SQL and their finishing, with the p-values Phase 3's distribution functions bring | Nothing | `_expr.py` | Not profiled |
| `feature_selection/variance.py` | 4 | G7: the variance selector | Its name and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/scale.py` | [Widest steps](../benchmarks/engine-profile.md), `variance`: about 6.5 s at 200 columns, 15 to 26 s at 500, one statement, Python's share 17% and 10% |
| `feature_selection/univariate.py` | 4 | G7: the univariate selectors | Their names and docstrings | `_errors.py`, `_group.py`, `_selectors.py`, `_step.py`, `feature_selection/_scores.py`, `preprocessing/scale.py`, `preprocessing/target.py` | Not profiled |
| `feature_selection/_select.py` | 4 | G7: none beyond the group's argument rules | The `sq.select` group's names and docstrings | `_errors.py`, `_group.py`, `_selectors.py`, `feature_selection/univariate.py`, `feature_selection/variance.py` | Not profiled |
| `feature_selection/__init__.py` | 4 | G7: none, it re-exports | All of it | `feature_selection/univariate.py`, `feature_selection/variance.py` | Not profiled |
| `decomposition/pca.py` | 4 | G7: the PCA step. Its learn moves onto `sqlearn_gram` in Phase 2 and its `eigh` into C++ in Phase 3; its Python goes in Phase 4 | Its name and docstrings | `_errors.py`, `_expr.py`, `_group.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py`, `preprocessing/scale.py` | [Gram learn](../benchmarks/engine-profile.md): about 1.5 s, 10 s, 32 s at 50, 200, 500 columns |
| `decomposition/_decompose.py` | 4 | G7: none beyond the group's argument rules | The `sq.decompose` group's names and docstrings | `_errors.py`, `_group.py`, `_selectors.py`, `decomposition/pca.py` | Not profiled |
| `decomposition/__init__.py` | 4 | G7: none, it re-exports | All of it | `decomposition/pca.py` | Not profiled |
| `explore/_common.py` | 4 | G8: choosing columns and answering | Nothing | `_config.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_selectors.py` | Not profiled |
| `explore/correlations.py` | 4 | G8: the correlations, in tiles of columns | Its name and docstrings | `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_output.py`, `_selectors.py`, `explore/_common.py` | [Spearman](../benchmarks/engine-profile.md), before #75: about 11 s and 126 s at 50 and 200 columns, Python's share 3%; summed UNGROUPED_AGGREGATE 40.45 s and 645.66 s, WINDOW 8.12 s and 23.22 s |
| `explore/profile.py` | 4 | G8: the profile | Its name and docstrings | `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_memory.py`, `_output.py`, `_selectors.py`, `explore/_common.py` | [Widest steps](../benchmarks/engine-profile.md), `profile`: about 11.6 s at 200 columns, 32 to 51 s at 500, Python's share 8% and 9%, no operator standing out |
| `explore/histogram.py` | 4 | G8: the histogram | Its name and docstrings | `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_output.py`, `_selectors.py`, `explore/_common.py` | Not profiled |
| `explore/missing.py` | 4 | G8: the patterns of missing values | Its name and docstrings | `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_output.py`, `_selectors.py`, `explore/_common.py` | Not profiled |
| `explore/top.py` | 4 | G8: the commonest values | Its name and docstrings | `_config.py`, `_diagnose.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_output.py`, `_selectors.py`, `explore/_common.py` | Not profiled |
| `explore/__init__.py` | 4 | G8: none, it re-exports | All of it: `sq.explore`'s names | `explore/correlations.py`, `explore/histogram.py`, `explore/missing.py`, `explore/profile.py`, `explore/top.py` | Not profiled |
| `metrics/_labels.py` | 4 | G9: the checks before a label metric scores | Nothing | `_errors.py`, `_expr.py`, `_selectors.py` | Not profiled |
| `metrics/_relations.py` | 4 | G9: the relation helper of tables and curves | Nothing | `_errors.py` | Not profiled |
| `metrics/accuracy.py` | 4 | G9: the metric base and accuracy | Names and docstrings | `_errors.py`, `_expr.py`, `_feed.py`, `agg/aggregates.py`, `metrics/_labels.py` | Not profiled |
| `metrics/classification.py` | 4 | G9: precision, recall, F1, F-beta | Names and docstrings | `_errors.py`, `_expr.py`, `metrics/_labels.py`, `metrics/accuracy.py` | Not profiled |
| `metrics/balanced.py` | 4 | G9: balanced accuracy, the Matthews correlation | Names and docstrings | `_errors.py`, `metrics/_labels.py`, `metrics/accuracy.py`, `metrics/classification.py` | Not profiled |
| `metrics/probability.py` | 4 | G9: the probability metrics | Names and docstrings | `_errors.py`, `_expr.py`, `metrics/accuracy.py`, `metrics/classification.py` | Not profiled |
| `metrics/regression.py` | 4 | G9: the regression metrics | Names and docstrings | `_errors.py`, `_expr.py`, `metrics/accuracy.py` | Not profiled |
| `metrics/tables.py` | 4 | G9: the confusion matrix | Names and docstrings | `_errors.py`, `_expr.py`, `_output.py`, `metrics/_labels.py`, `metrics/_relations.py`, `metrics/classification.py` | Not profiled |
| `metrics/curves.py` | 4 | G9: the ROC and precision-recall curves | Names and docstrings | `_errors.py`, `_expr.py`, `_output.py`, `metrics/_labels.py`, `metrics/_relations.py`, `metrics/classification.py` | Not profiled |
| `metrics/__init__.py` | 4 | G9: none, it re-exports | All of it: `sq.metrics`' names | `metrics/accuracy.py`, `metrics/balanced.py`, `metrics/classification.py`, `metrics/curves.py`, `metrics/probability.py`, `metrics/regression.py`, `metrics/tables.py` | Not profiled |
| `model_selection/defaults.py` | 4 | G10: the default search spaces, looked up by the model's class path | Reading the outside model's class path | none | Not profiled |
| `model_selection/folds.py` | 4 | G10: the folds from a hash and a seed | The fold objects' names and docstrings | `_errors.py`, `_expr.py` | Not profiled |
| `model_selection/kept.py` | 4 | G10: the kept preparations in a DuckDB file | Nothing | `_config.py`, `_errors.py`, `_expr.py`, `_inputs.py`, `_selectors.py`, `_step.py`, `agg/aggregates.py` | Not profiled |
| `model_selection/methods.py` | 4 | G10: the methods' ask and tell | The bridge to Optuna | `_errors.py`, `_model.py`, `_pipeline.py`, `_step.py` | Not profiled |
| `model_selection/search.py` | 4 | G10: the search over folds | `sq.search`'s names and docstrings; the trials' outside models reached through G4 | `_compose.py`, `_config.py`, `_errors.py`, `_expr.py`, `_feed.py`, `_inputs.py`, `_model.py`, `_output.py`, `_pipeline.py`, `_step.py`, `_store.py`, `metrics/__init__.py`, `metrics/accuracy.py`, `model_selection/defaults.py`, `model_selection/folds.py`, `model_selection/kept.py`, `model_selection/methods.py` | Not profiled |
| `model_selection/groups.py` | 4 | G10: none beyond the groups' argument rules | The `sq.search` and `sq.folds` groups; the bridge to Optuna | `_group.py`, `_pipeline.py`, `metrics/__init__.py`, `metrics/accuracy.py`, `model_selection/folds.py`, `model_selection/methods.py`, `model_selection/search.py` | Not profiled |
| `model_selection/__init__.py` | 4 | G10: none, it re-exports | All of it | `model_selection/defaults.py`, `model_selection/folds.py`, `model_selection/groups.py`, `model_selection/methods.py`, `model_selection/search.py` | Not profiled |
| `store.py` | 4 | G10: none beyond clearing the store and the kept files | All of it: `sq.store`'s names | `_store.py`, `model_selection/kept.py` | Not profiled |
| `_saving/__init__.py` | 4 | G11: none, it holds only a docstring | Nothing | none | Not profiled |
| `_saving/codec.py` | 4 | G11: the tagged JSON encodings, with a static class lookup | Nothing | `_errors.py`, `_selectors.py`, `agg/aggregates.py`, `model_selection/folds.py` (in a function), `preprocessing/impute.py` (in a function) | Not profiled |
| `_saving/recipe.py` | 4 | G11: steps and models as records, and the check of what a file may import | Importing a user's step or an outside model's class, once the C++ has checked its path | `_errors.py`, `_model.py`, `_saving/codec.py`, `_step.py` | Not profiled |
| `_saving/learned.py` | 4 | G11: the `learned` part of a saved file | Nothing | `_compose.py`, `_errors.py`, `_inputs.py`, `_pipeline.py`, `_saving/codec.py`, `_step.py`, `_store.py` | Not profiled |
| `_saving/files.py` | 4 | G11: `sq.save` and `sq.load` | Their names and docstrings | `__init__.py` (in a function), `_errors.py`, `_model.py`, `_pipeline.py`, `_saving/codec.py`, `_saving/learned.py`, `_saving/recipe.py`, `_step.py` | Not profiled |
| `__init__.py` | 4 | G12: none: it is the `sq.` namespace | All of it: the bindings' module | `_config.py`, `_model.py`, `_output.py`, `_pipeline.py`, `_saving/files.py`, `_selectors.py`, `_step.py`, `agg/__init__.py`, `decomposition/_decompose.py`, `errors.py`, `explore/__init__.py`, `feature_selection/_select.py`, `fn.py`, `metrics/__init__.py`, `model_selection/groups.py`, `out.py`, `preprocessing/_encode.py`, `preprocessing/bin.py`, `preprocessing/features.py`, `preprocessing/impute.py`, `preprocessing/scale.py`, `preprocessing/transform.py`, `store.py` | Not profiled |

No module's Python is deleted in Phase 3. Phase 3 brings numeric functions that
two modules use before their Phase 4 groups: PCA's `eigh`, and the
distributions that give `feature_selection/_scores.py` its p-values.

## Phase 2 first

`_gram.py` is ported first, in Phase 2, as the spec has it. The
[Gram learn](../benchmarks/engine-profile.md) numbers support that:

- Python's share was 37%, 27% and 32% at 50, 200 and 500 columns, the largest
  of every path profiled.
- `gram_matrix` was the largest Python function at every width.
- The statements grew from 8 to 20 to 44 as the batches did, and
  BATCH_CREATE_TABLE_AS, which writes the numbered table the batches are read
  from, summed 0.33 s, 1.64 s and 3.62 s.

`_gram.py` imports `MEGABYTES` from `_feed.py` and the budget from `_memory.py`,
both still Python in Phase 2. The kernel is registered in DuckDB, so the
Python pipeline (`_pipeline.py`'s `_learn_gram`) calls it in its SQL and passes
the budget in. No binding beyond Phase 1's is needed for it.

## The groups of Phase 4

A piece of the port is one group (ADR 0067). The groups go in this order. Each
is ported after the groups it imports from, so each group's C++ calls only C++
already merged, except where the seam to Python steps carries the call (spec
§3.1). Phase 4's specs may split the groups into numbered phases; that is
theirs to decide.

1. **G1, expressions and names:** `_errors.py`, `errors.py`, `_expr.py`,
   `_names.py`, `_selectors.py`, `_group.py`, `fn.py`, `agg/aggregates.py`,
   `agg/__init__.py`. They import nothing outside the group. The Python steps
   still call `_expr.py`'s helpers and the aggregates; the bindings hand them
   DuckDB expressions, which cross unchanged because there is one DuckDB.
2. **G2, the session and inputs:** `_config.py`, `_memory.py`, `_inputs.py`.
   They import only G1, and each other: `_config.py` imports `_memory.py`
   inside a function, and `_memory.py` imports `_config.py`, so the two go
   together. `_config.py`'s import of `_output.py` is for types only.
3. **G3, the step contract, the compositor and the planner:** `_step.py`,
   `_compose.py`, `_plan.py`, `_diagnose.py`, `_output.py`, `out.py`. They
   import only G1, G2 and each other; `_diagnose.py` reads `__version__` from
   the package, which the bindings answer. **This group relies on the seam:**
   every built-in step is still Python when the compositor becomes C++, and
   reaches it as a user's own step does.
4. **G4, the hand-overs:** `_model.py`, `_feed.py`. They import only G1 to G3.
   The outside model's side stays in the bindings.
5. **G5, the pipeline and the store:** `_pipeline.py`, `_store.py`. They import
   G1 to G4 and `_gram.py`, already C++ from Phase 2. With G5 the core is done.
6. **G6, preprocessing:** the twelve modules of `preprocessing/`. They import
   G1 and G3 (`target.py` imports `_compose.py`). Inside the group,
   `scale.py` goes before `bin.py`, `features.py` and `transform.py`, which
   import its `_numeric_inputs`.
7. **G7, feature selection and decomposition:** the five modules of
   `feature_selection/` and the three of `decomposition/`. They import G6:
   `variance.py`, `univariate.py` and `pca.py` import `preprocessing/scale.py`'s
   `_numeric_inputs` (and `pca.py` its `EPS`), and `univariate.py` imports
   `preprocessing/target.py`'s `_NUMBERS`.
8. **G8, exploration:** the seven modules of `explore/`. They import only G1
   to G3; no step.
9. **G9, metrics:** the ten modules of `metrics/`. They import G1 and G3, and
   `accuracy.py` imports `_feed.py`'s `PROBA` (G4).
10. **G10, model selection and the public store:** the seven modules of
    `model_selection/`, and `store.py`. `search.py` and `groups.py` import
    the pipeline (G5) and the metrics (G9); `store.py` imports
    `model_selection/kept.py`. Optuna stays Python, reached through the
    bindings.
11. **G11, saving:** the five modules of `_saving/`. They import the pipeline,
    the store, the step contract and the models, and `codec.py` imports
    `model_selection/folds.py` and `preprocessing/impute.py` inside functions,
    so saving comes after every group whose objects it encodes. Files saved
    before the port still load, and the group gets a whole-branch security
    review of its own (spec §3.8).
12. **G12, the package:** `__init__.py`, which imports from every group. It
    has no C++; when every name it gives comes from the C++, it is the
    bindings' module and Phase 4 is done.

**Tests of internals** move with their group (spec §3.8). Counting the test
files under `tests/` that name each private module, `sqlearn._config` is named
by 49, `_store` by 18, `_errors` by 12, `_step` by 10 and `_saving` by 6: G2,
G1, G3, G5 and G11 carry most of the rewriting. These are counts of files, by
`grep`, not a measurement of work.

## The heavy paths, measured

From the [profiling page](../benchmarks/engine-profile.md), 1,000,000 rows,
under a load of 10 to 17 on 8 cores. Times are the two timing runs, rounded as
the page rounds them.

| Path | Columns | Time | Python's share | Where DuckDB spends it | Its group |
|---|---|---|---|---|---|
| Gram learn (`pca`) | 50, 200, 500 | about 1.5 s, 10 s, 32 s | 37%, 27%, 32% | TABLE_SCAN, then UNGROUPED_AGGREGATE (summed: 29.63 s and 7.66 s at 500) | Phase 2, then G7 |
| `median` (`sq.impute.median`) | 200, 500 | about 21 s, 187 s | 1%, 1% | WINDOW 156.55 s, 1108.31 s; 15.74 GB spilled at 500 | G3 (the sort), G6 (the step) |
| Spearman, before #75 | 50, 200 | about 11 s, 126 s | 3%, 3% | UNGROUPED_AGGREGATE 40.45 s, 645.66 s (summed); WINDOW 8.12 s, 23.22 s | G8 |
| `profile` | 200, 500 | about 11.6 s, 32 to 51 s | 8%, 9% | no operator stands out | G8 |
| `variance` | 200, 500 | about 6.5 s, 15 to 26 s | 17%, 10% | UNGROUPED_AGGREGATE, PROJECTION; TABLE_SCAN at 500 | G7 |
| `scale` (`sq.scale.standard`) | 200, 500 | about 3.7 s, 13.8 s | 25%, 19% | UNGROUPED_AGGREGATE, PROJECTION; TABLE_SCAN at 500 | G6 |

For the one-statement paths (`scale`, `median`, `variance`) the page finds
Python's time almost all inside the call that submits the statement to DuckDB.
Porting the Python around that call is not shown to save it.

## What the numbers change

Against the spec's draft order (§5.3), area by area.

- **The Gram learn, Phase 2:** kept. The numbers above put it first.
- **PCA:** kept. Its learn moves with the Gram learn in Phase 2, its `eigh` in
  Phase 3, the rest in Phase 4 (G7, after preprocessing, whose `scale.py` it
  imports).
- **Feature scores:** kept in Phase 4, gaining p-values from Phase 3. They go
  in G7 with the other selectors, after preprocessing, because
  `univariate.py` imports `preprocessing/scale.py` and
  `preprocessing/target.py`.
- **The core:** kept first, split into G1 to G5 by its imports, as the spec's
  §4 names its parts (the expression and naming layer, the compositor and
  planner, the step framework, the store). Two changes, both from imports, not
  numbers:
  - **The hand-overs move up**, from the draft's place after model selection to
    G4, before the pipeline: `_pipeline.py` imports `fetch`,
    `predict_streamed` and `stream_trainer` from `_feed.py`, and `Model`,
    `as_model`, `check_feed`, `is_model` and `is_trained` from `_model.py`.
  - **`store.py` moves out of the core**, to G10 with model selection:
    it imports `model_selection/kept.py`, whose `prepared` and `clear` it
    calls. `_store.py`, the store itself, stays in the core (G5).
- **Steps, after the core:** kept. One change, from the code and a number:
  **the exact median's sort is the compositor's, not a step's.** The draft
  names "an exact median that spills" as a kernel candidate under the steps.
  The sort that spills is `_compose.py`'s `_quantile_ctes`, which computes
  every quantile of a learn stage in one window over all values; the
  quantiles of `impute.py`, `scale.py`, `bin.py` and `features.py` all go
  through it. So the candidate belongs to G3. The number: the `median` row,
  WINDOW 1108.31 s summed at 500 columns, 15.74 GB spilled, about 9 times the
  time for 2.5 times the columns, with Python's share at 1%. Whether G3 brings
  a kernel for it, or ports the sort as SQL first, is G3's spec's call.
- **Exploration:** kept in Phase 4, after the steps. It imports no step, so its
  place is free after G3; the numbers give no reason to move it. Two of the
  draft's kernel candidates are not borne out by these numbers:
  - **Spearman's ranks:** the ranks are WINDOW, 23.22 s of the summed operator
    time at 200 columns, against UNGROUPED_AGGREGATE's 645.66 s for the
    pairwise sums. The ranks are not where the time goes. Phase 3's "average
    ranks for Spearman, if profiling still shows them a cost" stays as the
    spec has it, to be measured again after #75 changes the first scan.
    Whether the pairwise sums of ranked columns could run on `sqlearn_gram` is
    a candidate for G8's spec, not measured here.
  - **`profile`'s moments:** no operator stood out, and Python's share was 8%
    and 9%. No kernel is argued for it.
  - **`histogram`'s counts** were not profiled; they stay a GPU candidate for
    Phase 6, as the draft has it.
- **Metrics:** kept, after exploration. Not profiled.
- **Model selection:** kept, after metrics, whose modules `search.py` and
  `groups.py` import. Optuna stays Python, through the bindings. Not profiled.
- **Saving:** kept last of the library's groups, because it encodes every
  other group's objects. The package (`__init__.py`, G12) closes Phase 4.

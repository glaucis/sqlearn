# The docs cleanup: what is kept, archived, amended, consolidated

Task 2 of [the docs cleanup plan](2026-11-27-docs-cleanup.md): one row per
document, for Tomas to approve before anything moves. Nothing has moved yet.

Verdicts, as the plan defines them:

- **keep**: true now, or work still ahead.
- **archive**: a plan implemented; a spec built or of the old Python; a
  question answered (its ADR cited); an ADR superseded, or whose subject is
  only the old Python.
- **amend**: still true in part: the part that changed, and what changed it.
- **consolidate**: one of several ADRs on one subject whose current rule is
  spread across them; the proposed new ADR supersedes them.

Each **archive** ADR was checked with `git grep -n "<number>" CLAUDE.md
docs/architecture`: an ADR a current rule cites is **amend**, not archive.
CLAUDE.md's opening paragraph lists ADR ranges as a record of what was built,
not as rules, and was not counted as a citation.

## Counts

| folder | keep | archive | amend | consolidate | rows |
| --- | --- | --- | --- | --- | --- |
| `docs/adr/` | 26 | 3 | 26 | 20 | 75 |
| `docs/specs/` | 6 | 15 | 0 | 0 | 21 |
| `docs/plans/` | 4 | 28 | 0 | 0 | 32 |
| `docs/questions/` | 8 | 3 | 3 | 0 | 14 |
| `docs/architecture/` | 6 | 0 | 5 | 0 | 11 |
| `docs/agents/` | 3 | 0 | 1 | 0 | 4 |
| `docs/benchmarks/` | 7 | 2 | 2 | 0 | 11 |
| `docs/validation/` | 1 | 0 | 0 | 0 | 1 |
| `docs/` (top level) | 2 | 0 | 0 | 0 | 2 |
| **all** | **63** | **51** | **37** | **20** | **171** |

`docs/questions/earlier-attempts/` (39 files) is one row: it goes whole.

## The proposed consolidations

Six new ADRs, each superseding the records on one subject:

- **A. How a pipeline learns: static and dynamic steps, and runs along the
  column graph**: supersedes 0012, 0018, 0026.
- **B. The contract of a user's own step**: supersedes 0019, 0027, 0028,
  0037.
- **C. The learning store and its keys**: supersedes 0014, 0021, 0024, 0056.
- **D. The search: one function, pluggable methods, defaults and the
  defaults warning**: supersedes 0022, 0031, and takes the search half of
  0039 (0039 itself is amend).
- **E. How aggregates learn: exact quantiles by sorting, compensated sums,
  levels**: supersedes 0032, 0033, 0036, 0044, 0051.
- **F. Saving a pipeline: JSON, sqlearn's part only, nothing imported**:
  supersedes 0047, 0048, and restates ADR 0070's saving bullet.

## Questions for Tomas

1. **The consolidations.** Each would restate rules written for the old
   Python, while ADR 0070 has each group designed for C++. The classifiers
   were unsure how much of the Python mechanics in 0012, 0019, 0044 and 0051
   binds the C++ design. Write all six now, some, or none (leaving each to
   its group's C++ design, with those ADRs kept as they are)?
2. **Kept for now, though built:** `specs/foundation.md` (active pages send
   readers to it for the full tree and configuration),
   `specs/library-exploration.md` (`HANDOFF.md` points at its §8 for later
   work), `specs/selection-by-group.md` and its plan (the audit's first run
   still waits on your go-ahead). Archive any of them now?
3. **Benchmarks.** The plan makes `archived/` folders only under `adr/`,
   `specs/`, `plans/` and `questions/`. Two benchmark pages would be archive
   (`generators-on-many-threads.md`, `category-lookup.md`): add
   `docs/benchmarks/archived/`, or keep them? Five more pages measured only
   the old Python and are kept as the evidence ADRs cite; ADR 0072 names
   none of them for a rerun.
4. **ADR 0058** (a Gram step's XᵀX in numpy) is amend only because CLAUDE.md
   cites it as a current rule; the Gram step it describes is old Python,
   never run (ADR 0073). Correct that rule in CLAUDE.md and archive 0058?
5. **The amend rows outside `docs/adr/`** (five architecture pages,
   `agents/issue-tracker.md`, three questions, two benchmark pages) state
   things no longer true since ADR 0073. The plan's Task 4 edits only ADRs'
   status lines. Fix these pages in this cleanup, or leave them as a
   follow-up?

## Tomas's answers (2026-11-27)

Given after the list was committed; the work follows them.

1. **The consolidations:** write all six now (A to F, ADRs 0074 to 0079);
   the twenty ADRs they supersede are archived.
2. **The four built documents:** kept, all four.
3. **Benchmarks:** `docs/benchmarks/archived/` is added, and the two archive
   pages move there.
4. **ADR 0058:** the rule in CLAUDE.md stays; 0058 is amend.
5. **The amend rows outside `docs/adr/`:** fixed in this cleanup.
6. **The link check:** asked separately (`just test` does not rerun it after
   a docs-only edit): it gets its own task, whose inputs are the tracked
   Markdown, so only it reruns on a docs edit.

## The rows

### docs/adr/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `adr/0001-uv-for-python-packaging.md` | keep | uv for dependencies, locking and `uv run` is still a CLAUDE.md rule (cited as 0001) and in overview.md and setup.md. |  |
| `adr/0002-sql-on-duckdb-execution-engine.md` | amend | Computation in DuckDB still holds (CLAUDE.md cites 0002 with 0060), but its "every step is SQL, never data into Python" rule is already amended by 0058 (Gram step in numpy) and 0060 (C++ `sqlearn_*` functions), and its consequences still say `fit`/`transform`, renamed by 0013. | Status line already records 0058 and 0060; the verbs line needs 0013's names. |
| `adr/0003-scikit-learn-style-api.md` | amend | The rule that sqlearn follows scikit-learn's conventions and records each departure stands (CLAUDE.md cites 0003, and 0070 repeats it), but its own list of conventions (`fit`/`transform`/`fit_transform`, `Pipeline`-style classes with `__init__` settings) was departed from by 0013, 0034 and 0039, and its status line does not say so. | Add to its status the departures 0013, 0022, 0023, 0034, 0039. |
| `adr/0004-apache-2-licence.md` | amend | Apache-2.0, the CLA, trademark and credit still hold (CLAUDE.md cites 0004 with 0066), but its runtime-licence list (MIT, BSD, Apache, PSF; `duckdb` and `numpy`) was widened by 0066 to any OSI-approved permissive licence. | Status line already records 0066. |
| `adr/0005-runtime-dependencies.md` | amend | "Each runtime dependency justified in writing" stands (CLAUDE.md cites 0005), but `duckdb` from PyPI is replaced by sqlearn's own DuckDB build (0061), numpy was added by 0057, and the C++ in the one binary (0060) is not covered by its `pyproject.toml`-comment wording. | Status line already records 0057 and 0061. |
| `adr/0006-local-and-offline.md` | amend | Local and offline stands (CLAUDE.md cites 0006), but its consequence that example datasets are bundled or fetched is replaced by 0053 (no datasets), and 0061 adds the extension rule. | Status line already records 0053 and 0061. |
| `adr/0007-python-3-12-floor.md` | keep | The 3.12 floor and test matrix are a CLAUDE.md rule (cited as 0007) and in python-versions.md; unsure only whether its support policy's "DuckDB publishes wheels" condition still fits now that sqlearn builds its own DuckDB (0061), which the file does not address. |  |
| `adr/0008-just-task-runner.md` | amend | `just` as the one entry point stands (CLAUDE.md cites 0008), but its tiers ("`verify` at every review, merge and release") were changed by the Phase 1 spec (§3.1, §3.2): `just done` on what changed, `just verify` the release tier, CMake under `just`. | Status line already records the Phase 1 spec (a spec, not an ADR). |
| `adr/0009-sphinx-documentation-site.md` | amend | One Sphinx site on GitHub Pages stands (overview.md cites 0009), with its hosting question settled by 0062; its "docs build that imports the package" and docstring-generated reference now depend on the bindings, which the file does not discuss. | Status line already records 0062. |
| `adr/0010-british-prose-american-identifiers.md` | keep | A current CLAUDE.md rule (cited as 0010) and in writing.md. |  |
| `adr/0011-curriculum-levels.md` | keep | The learning site's levels and fixed URLs are work still ahead (overview.md cites 0011). |  |
| `adr/0012-static-and-dynamic-steps.md` | consolidate | Static and dynamic steps describe how a pipeline learns through `sq.`, but the current rule is spread: its run count is superseded by 0018, user-step classification is in 0019, 0027 and 0028, and its consequences on `WITH` stages and lazy relation objects are the Python compositor's mechanics; cited by overview.md and in CLAUDE.md's "decisions ADRs 0012–0033" (a summary, not a rule). Unsure: 0070 has each group designed for C++, so the consolidation may best come with the C++ pipeline group's spec. | New ADR "How a pipeline learns: static and dynamic steps, and its runs", superseding 0012, 0018, 0026. |
| `adr/0013-learn-apply-train-predict.md` | keep | The four verbs are a current CLAUDE.md rule (cited as 0013) and in overview.md. |  |
| `adr/0014-learning-store.md` | consolidate | The store is behaviour seen through `sq.` (nothing learned twice, folds reused), but its key is already split: data part extended by 0021, steps part superseded by 0024, further narrowed by 0056; cited by overview.md. | New ADR "The learning store and its keys", superseding 0014, 0021, 0024 (and 0056, outside this batch). |
| `adr/0015-duckdb-expressions-no-sqlglot.md` | amend | "DuckDB only, no sqlglot" is still stated in overview.md §"Later: other database engines" (cites 0015), but its decision that steps build DuckDB's Python expression objects and a Python compositor renders the SQL is the old Python's mechanics (`_compose.py`, now in `old_python/`), replaced by the C++ library (0060, 0070). | Keep the no-sqlglot and DuckDB-only rule; the representation of SQL pieces is the C++'s to decide (0060, 0070). |
| `adr/0016-validation-method.md` | keep | Validation against exact values and comparable libraries is the gate of every group under 0070 and 0073 and is cited by overview.md, testing.md and validation.md; its PCA-runner example (`validate_pca.py`) now sits in `old_python/`, and its published pages are still ahead. |  |
| `adr/0017-models-from-other-libraries.md` | amend | Outside models stay supported (CLAUDE.md cites 0017 with 0068), but "for now sqlearn builds everything except the models" is amended by 0068, which makes sqlearn's own models a goal. | Status line already records 0068. |
| `adr/0018-runs-follow-the-chains-between-steps.md` | consolidate | Supersedes 0012's run count and holds the current planning rule (earliest run, declared reads and writes), cited by overview.md; it belongs with 0012 and 0026 in one record of how a pipeline learns. | New ADR "How a pipeline learns: static and dynamic steps, and its runs", superseding 0012, 0018, 0026. |
| `adr/0019-custom-steps-and-failure-feedback.md` | consolidate | Users' own steps stay writable in Python (0070, CLAUDE.md), so the contract is still ahead, but its classification rule is extended by 0027 and 0028 and the contract grows in 0037; its failure-message form overlaps 0046's house form. Unsure whether the placeholder inspection survives the C++ redesign; the file gives no view. | New ADR "The contract of a user's own step", superseding 0019, 0027, 0028, 0037. |
| `adr/0020-column-selectors.md` | amend | Selectors and their Polars operators are `sq.` behaviour still ahead, but the names `sq.numeric()`, `sq.string()` moved to `sq.cols` by 0034, and "resolved in Python" is now the C++'s to do (0060, 0070). |  |
| `adr/0021-inputs-and-how-the-store-knows-them.md` | consolidate | Which inputs `learn` accepts and how the store recognises each is `sq.` behaviour, but it extends 0014's key and is narrowed by 0024 and 0029; its "depends only on `duckdb`" consequence was changed by 0057. | New ADR "The learning store and its keys", superseding 0014, 0021, 0024 (and 0056). |
| `adr/0022-one-search-with-pluggable-methods.md` | consolidate | One search with ask-and-tell methods and defaults is `sq.` behaviour, but its names (`sq.Search`, `sq.Random`, `sq.Optuna`, `sq.KFold`, `sq.accuracy`) were changed by 0034 and 0039, and its warning was narrowed by 0031. | New ADR "The search: one function, pluggable methods, defaults and the defaults warning", superseding 0022, 0031 and the search half of 0039. |
| `adr/0023-lazy-results-out-and-feed.md` | amend | Lazy results, `out=` and `feed=` are `sq.` behaviour, but `sq.out_parquet` became `sq.out.parquet` (0034) and "sqlearn still depends only on `duckdb`" was changed by 0057. |  |
| `adr/0024-store-keys-follow-what-a-step-reads.md` | consolidate | Holds the current steps part of the key (superseding part of 0014) and is itself narrowed by 0056. | New ADR "The learning store and its keys", superseding 0014, 0021, 0024 (and 0056). |
| `adr/0025-results-stored-as-data-in-mirrored-folders.md` | amend | Results as committed JSON with no dates still describe the validation and benchmark records, and layout.md (line 120) cites 0025 for `validation/` mirroring the package; but its Python mirror (`src/sqlearn/preprocessing/scale.py`, `tests/src/...`) and the `just check` mirror check are gone with the old Python (0073; HANDOFF says `check-mirror` is gone). | The JSON results rule stands; the folder layout for the C++ groups is not yet decided in these files. |
| `adr/0026-a-step-without-cols-works-on-every-column.md` | consolidate | "`cols=None` means every column" is `sq.` behaviour, a planner rule that sits with 0018 and 0024; its example is Python's `duckdb.FunctionExpression`. | New ADR "How a pipeline learns: static and dynamic steps, and its runs", superseding 0012, 0018, 0026. |
| `adr/0027-a-user-step-may-declare-itself-dynamic.md` | consolidate | A user step's `static`/`dynamic` declaration is part of the user-step contract that 0019 started. | New ADR "The contract of a user's own step", superseding 0019, 0027, 0028, 0037. |
| `adr/0028-a-step-returning-a-mapping-counts-as-dynamic.md` | consolidate | A refinement of 0019's classification of undeclared user steps. | New ADR "The contract of a user's own step", superseding 0019, 0027, 0028, 0037. |
| `adr/0029-relations-from-another-connection-are-refused.md` | keep | Refusing a relation from another connection is `sq.` behaviour; unsure: its mechanism (`con.register` of a temporary view on sqlearn's connection) is the Python `duckdb` module's, and whether the C++ with its own DuckDB build keeps it is not in the files. |  |
| `adr/0030-infinity-is-refused.md` | keep | Refusing infinite learned values is `sq.` behaviour still required; it names the core's `Impute` and `Scale`, renamed by 0034. |  |
| `adr/0031-the-defaults-warning-is-about-what-to-search.md` | consolidate | A narrowing of 0022's defaults warning, best read with it. | New ADR "The search: one function, pluggable methods, defaults and the defaults warning", superseding 0022, 0031 and the search half of 0039. |
| `adr/0032-the-median-is-exact-by-sorting.md` | consolidate | The exact median by sorting, with `approx=True` as opt-in, is `sq.` behaviour, but its marker rule is superseded by 0036 and the rule for staged aggregates is spread over 0033, 0036, 0044 and 0051; its SQL and "the compositor" are the Python's mechanics. Cited only in CLAUDE.md's "decisions ADRs 0012–0033" summary. | New ADR "How aggregates learn: exact quantiles by sorting, compensated sums, levels", superseding 0032, 0033, 0036 (and 0044, 0051). |
| `adr/0033-the-mean-is-summed-with-compensation.md` | consolidate | A compensated mean is an accuracy rule still wanted, but its standard-deviation line is superseded by 0044 and "`sq.avg` builds `favg`" is the Python's mechanics. Cited only in CLAUDE.md's "decisions ADRs 0012–0033" summary. | New ADR "How aggregates learn: exact quantiles by sorting, compensated sums, levels", superseding 0032, 0033, 0036 (and 0044, 0051). |
| `adr/0034-a-grouped-api.md` | amend | The grouped `sq.` API stands, but its top-level list (`sq.Pipeline`, `sq.Step`, `sq.Search`, config) was changed by 0039 (`sq.Search` became `sq.search`, folds into `sq.folds`) and 0047 adds `sq.save`/`sq.load` at the top level; 0070 lets `sq.` names change before 1.0.0. Cited only in CLAUDE.md's "ADRs 0034–0038" summary. |  |
| `adr/0035-names-of-generated-columns.md` | keep | The naming rule for created columns is `sq.` behaviour, listed as a G1 item in engine-inventory.md. |  |
| `adr/0036-staged-aggregates-anywhere-in-a-learned-value.md` | consolidate | Already superseded in part by 0051 and amended twice (#44, #41); its #41 amendment (which stages cross-join) is the Python compositor's mechanics. | New ADR "How aggregates learn: exact quantiles by sorting, compensated sums, levels", superseding 0032, 0033, 0036 (and 0044, 0051). |
| `adr/0037-four-additions-to-the-step-contract.md` | consolidate | The user-step contract additions stay relevant to the Python seam for users' steps, but its consequence that removing any needs its own superseding ADR conflicts with 0070 (the `sq.` API may change before 1.0.0 without an ADR), and its signatures (`apply_row`, `Step.learned`) are the old Python's. | New ADR "The contract of a user's own step", superseding 0019, 0027, 0028, 0037. |
| `adr/README.md` | keep | States the ADR convention (one numbered file per decision, supersede rather than edit), which still holds. | — |
| `adr/index.md` | keep | The topic index of every ADR; still current, but its links and the "(superseded by …)" notes must follow any ADR moved to `archived/`. | — |
| `adr/0038-the-target-encoders-inner-folds-follow-row-position.md` | keep | A semantic rule of `sq.encode.target` (inner folds dealt by row position, so identical rows can fall in different folds) that the rewritten encoder must still honour. | — |
| `adr/0039-the-search-names-as-groups.md` | amend | The `sq.search` / `sq.folds` names remain the intended `sq.` API, but the mechanics it names (built on `sqlearn._group.Group`, classes importable from `sqlearn.model_selection`) are old Python moved by ADR 0073, and ADR 0070 lets each group redesign them for C++. | — (could later join a "grouped `sq.` API" record with ADR 0034, outside this batch) |
| `adr/0040-fold-schemes-as-sql-over-rows.md` | amend | Unsure: the user-visible rules (value-hashed `kfold` keeps identical rows together, a scheme defines its own training and held rows, a user may supply a scheme) still describe `sq.`, but the interface is the Python `sqlearn.model_selection.Folds` protocol and the store's fold-key shape, which are old Python (ADR 0073) and may be redrawn by the group's C++ design (ADR 0070). | — |
| `adr/0041-the-hand-over.md` | amend | The `feed=` forms, categories for text, and "never swap" with `sq.set_config(memory=...)` are behaviour seen through `sq.` and the hand-over stays (ADR 0068), but the mechanics named (DuckDB Python fetch methods, `sqlearn._selectors.is_text`) are old Python (ADR 0073), and ADR 0060 puts the logic in C++. | — |
| `adr/0042-a-metrics-settings-are-a-call.md` | amend | Calling a metric for a configured copy (`sq.metrics.f1(average="macro")`) is still the `sq.` API, but "averaging done in Python" and the `Metric.__call__` / `ClassificationMetric` subclass detail are changed by ADR 0060 (Python holds no logic) and ADR 0070. | — |
| `adr/0043-repeatable-within-rounding.md` | keep | The current rule for repeatability and ULP bounds, cited by `architecture/validation.md`; DuckDB's thread-order sums still apply. | — |
| `adr/0044-the-standard-deviation-in-two-staged-passes.md` | consolidate | The current rule for `sq.agg.std`/`var` is spread across this record, its two inline amendments (#42, #44) and ADR 0051, which superseded its refusals; unsure how much of the compositor's staged-SQL mechanics binds the C++ design, while the numerical promises (exactly 0 on a constant column, the 2-ULP bound) are behaviour seen through `sq.`. | New ADR "How sqlearn's aggregates learn: exact median, compensated mean, two-pass spread, nesting in levels", superseding 0032, 0033, 0036, 0044, 0051 |
| `adr/0045-datasets-are-relations-built-in-sql.md` | archive | Its subject, `sq.datasets`, was replaced by ADR 0053 and the code is now `old_python/devdata/` (ADR 0073), never run; grep of `0045` in CLAUDE.md and docs/architecture: no hits. | ADR 0053 (sqlearn ships no datasets), ADR 0073 |
| `adr/0046-sqlearn-warns-the-user-chooses.md` | amend | Its rule is current and cited in CLAUDE.md, but "even when the result would be identical" is changed by ADR 0064 (the GPU runs by itself when the answer is bit for bit the CPU's), as its Status line records. | — |
| `adr/0047-a-pipeline-saves-as-json.md` | consolidate | The saving rule is spread across this record, ADR 0048 (which removed `allow=`, `trust_model=`, `model=` and the pickle) and ADR 0070's saving bullet (old files need not load; security rules hold in C++); `architecture/overview.md` cites 0047 and 0048, so its links move to the new record. | New ADR "Saving a pipeline: JSON, sqlearn's part only, nothing imported", superseding 0047 and 0048 (and restating ADR 0070's saving bullet) |
| `adr/0048-the-user-saves-the-model-and-imports-its-packages.md` | consolidate | The current saving rules (user saves the model, `sq.load` imports nothing, only steps, models and fold schemes built) live here as an amendment of 0047; cited by `architecture/overview.md`. | Same new ADR as 0047 |
| `adr/0049-table-metrics-are-relations.md` | keep | A departure from scikit-learn's form for `sq.metrics` table functions (lazy relations, `out=`, not a `Metric`) that still describes `sq.`. | — |
| `adr/0050-predict-proba-keeps-the-target.md` | keep | A departure from scikit-learn for `Pipeline.predict_proba` (target kept, `__sqlearn_proba_<i>` columns, `classes_`) that still describes `sq.`. | — |
| `adr/0051-aggregates-learn-in-levels.md` | consolidate | Supersedes parts of 0036 and 0044, so the rule for nested aggregates is spread across them; its benchmark script path (`validation/benchmarks/nested_cost.py`) is now under `old_python/`; unsure, as for 0044, how much of the CTE mechanics binds the C++. | Same new aggregates ADR as 0044 |
| `adr/0052-meta-sqlearn.md` | archive | Its subject is the dataset generators' ticket tables, moved out of the package by ADR 0053 and now in `old_python/devdata/` (ADR 0073); its general rule for "any later table sqlearn places in `meta_sqlearn`" left the package with it, and the record says each such move is its own decision; grep of `0052` in CLAUDE.md and docs/architecture: no hits. | ADR 0053, ADR 0073 (nothing replaces the general rule for sqlearn's own tables) |
| `adr/0053-sqlearn-ships-no-datasets.md` | amend | "sqlearn ships, generates and fetches no datasets" is current and cited in CLAUDE.md, but `devdata/` at the root and its tests and validation paths are changed by ADR 0073 to `old_python/devdata/`, never run. | — |
| `adr/0054-d2-tweedie-on-a-constant-target.md` | keep | A departure from scikit-learn for `sq.metrics.d2_tweedie` on a constant target that still describes `sq.`. | — |
| `adr/0055-a-target-step-need-not-cross-fit.md` | keep | Semantics of the step contract seen through `sq.` (learning from the target and cross-fitting are two declarations; `sq.select` does not cross-fit). | — |
| `adr/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md` | consolidate | A rule of the learning store (output-only settings stay out of the learn key) that narrows ADR 0024, so the store's key is spread over 0014, 0021, 0024 and this record. | New ADR "The learning store and its keys" (C), superseding 0014, 0021, 0024, 0056. |
| `adr/0057-numpy-is-a-runtime-dependency.md` | amend | numpy is still a runtime dependency (cited in CLAUDE.md and `architecture/overview.md`), but ADR 0061 limits it to "until the engine's linear algebra (Phase 3)", ADR 0066 adds its 0BSD/CC0 allowance, and its "the library may import numpy" no longer fits ADR 0060's Python without logic. | — |
| `adr/0058-a-gram-step-builds-xtx-in-numpy.md` | amend | Cited as a current rule in CLAUDE.md ("until the engine's Phase 2 … (0058, 0070)") and `architecture/overview.md`, but the Gram step it describes is old Python in `old_python/`, never run (ADR 0073), and its replacement is C++ (ADR 0060, 0070); those citations may themselves be stale. | — |
| `adr/0059-exploration-functions-run-now-and-return-relations.md` | keep | Behaviour seen through `sq.explore` (runs at the call, long-form relations, pandas' conventions, exact by default) that the rewritten explore group must provide. | — |
| `adr/0060-a-native-engine-in-cpp-inside-duckdb.md` | amend | The core decision is current and cited throughout, but the porting parts (built-in steps still Python during the port; consequence "ported piece by piece (ADR 0067)") are changed by ADR 0070 and 0073, as its Status line notes. | — |
| `adr/0061-sqlearn-ships-its-own-duckdb-build.md` | amend | Its own DuckDB build is current and cited in CLAUDE.md, but its decision of a second package was changed to one package (the wheel `sqlearn` holding `duckdb/`) by the Phase 1 spec §3.3, not by an ADR, as its Status line records. | — |
| `adr/0062-apple-silicon-first.md` | keep | Current platform rule, cited in CLAUDE.md and docs/architecture. | — |
| `adr/0063-the-engines-compute-libraries.md` | keep | Current compute-library rule (Accelerate, OpenBLAS, Metal, no MLX, no `-ffast-math`), cited in CLAUDE.md. | — |
| `adr/0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md` | keep | Current rule for the GPU, cited in CLAUDE.md; work still ahead (#77). | — |
| `adr/0065-safety-rules-for-the-cpp.md` | amend | The safety rules are current and cited, but "sanitizers on every CI run", fuzzing "in CI" and the C++ tests "beside the Python tests (ADR 0067)" are changed by the Phase 1 spec (no CI by itself before `1.0.0`; `just verify` and manual workflows) and by ADR 0070 (C++ tests inside, Python only through `sq.`), as its Status line records. | — |
| `adr/0066-permissive-licences-never-copyleft.md` | keep | Current licence rule, cited in CLAUDE.md and docs/architecture; its 2026-11-24 amendment is inline and still current. | — |
| `adr/0067-how-computation-moves-to-the-engine.md` | archive | Superseded by ADR 0070; grep of `0067`: CLAUDE.md:55 ("superseding 0067") and `architecture/engine-inventory.md` (line 11 "which supersedes 0067", and its `related:` frontmatter) cite it only as superseded, not as a current rule. | ADR 0070 (as amended by 0073) |
| `adr/0068-sqlearns-own-models.md` | keep | sqlearn's own models are a goal still ahead (Phase 5), cited in CLAUDE.md and `architecture/overview.md`. | — |
| `adr/0069-the-crash-handler-hands-the-fault-on.md` | keep | Describes the C++ crash handler in `engine/src/crash/`, current; Windows work still ahead. | — |
| `adr/0070-sqlearn-is-rewritten-in-cpp.md` | amend | The rewrite rule is current and cited in CLAUDE.md, but ADR 0073 replaced its gate (Python deleted in the group's merge, benchmark not slower than that Python) and its "Python library frozen" / "Python still waiting" lines: the old Python is in `old_python/`, never run. | — |
| `adr/0071-fused-multiply-add-only-on-purpose.md` | keep | Current rule for FMA contraction, cited in CLAUDE.md. | — |
| `adr/0072-benchmarks-run-on-tomass-go-ahead.md` | amend | The go-ahead rule is current and cited, but its consequence that a group's gate times the old Python beside the new C++ is removed by ADR 0073 (no group is benchmarked against the old Python), and the page scripts it names are now in `old_python/`. | — |
| `adr/0073-the-old-python-moves-to-old-python.md` | keep | The current rule for `old_python/`, cited in CLAUDE.md and docs/architecture. | — |

### docs/specs/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `specs/README.md` | keep | The folder's README. | n/a |
| `specs/datasets-many-threads.md` | archive | Built in Python (#46, merged `591b2ba`); the datasets then left the package (ADR 0053, `3c1535c`) and now sit in `old_python/devdata/` (ADR 0073). | Nothing (sqlearn ships no datasets, ADR 0053) |
| `specs/foundation.md` | keep | Built (part 3.1), but `architecture/layout.md`, `writing.md`, `setup.md`, ADR 0008 and the overview §3.1 still send readers to it for the full tree, the configuration and the out-of-scope list; archiving it means moving that content into the architecture pages first (question 2). | `architecture/layout.md`, `architecture/setup.md`, `architecture/writing.md`, `architecture/testing.md` (in part) |
| `specs/learn-nested-aggregates.md` | archive | Built in the old Python (#49, merged `b1599cf`). | `architecture/engine-inventory.md` (the rewrite's groups) |
| `specs/library-balanced-scores.md` | archive | Built in the old Python (#62, merged `d9c2b18`). | `architecture/engine-inventory.md` |
| `specs/library-core.md` | archive | Built in the old Python (part 3.2, issue #8; the file says "Built"). | `architecture/engine-inventory.md` (G1 to G5, the core) |
| `specs/library-datasets.md` | archive | Built, then moved out of the package (ADR 0053, #61) and into `old_python/devdata/` (ADR 0073). | Nothing (sqlearn ships no datasets, ADR 0053) |
| `specs/library-decomposition.md` | archive | Built in the old Python (PCA, #66, merged `cdb2aec`). | `architecture/engine-inventory.md` (`_gram.py`, Phase 2) |
| `specs/library-exploration.md` | keep | Built in the old Python (#74), but `HANDOFF.md`'s "Next up" points at its §8 for the exploration still ahead (question 2). | `architecture/engine-inventory.md` (G8) for what was built; nothing yet for §8's later pieces |
| `specs/library-feature-selection.md` | archive | Built in the old Python (#65, merged `717a286`). | `architecture/engine-inventory.md` (G7) |
| `specs/library-metrics.md` | archive | Built in the old Python (precision, recall, F1, #34). | `architecture/engine-inventory.md` |
| `specs/library-model-selection.md` | archive | Built in the old Python (#33). | `architecture/engine-inventory.md` |
| `specs/library-more-metrics.md` | archive | Built in the old Python (#58). | `architecture/engine-inventory.md` |
| `specs/library-preprocessing.md` | archive | Built in the old Python (the file says "Built"; #30). | `architecture/engine-inventory.md` |
| `specs/library-regression-metrics.md` | archive | Built in the old Python (#63, merged `88e12ce`). | `architecture/engine-inventory.md` |
| `specs/library-saving-the-model.md` | archive | Built in the old Python (#55, `a8558e3` and its merge), though its status line still reads "for Tomas to approve before the plan". | `architecture/engine-inventory.md` |
| `specs/library-saving.md` | archive | Built in the old Python (#57), and already amended by the saving-the-model spec. | `architecture/engine-inventory.md` |
| `specs/native-engine-phase-1.md` | keep | Phase 1 is unfinished: steps 3 and 4 (spec §3.5 to §3.7) are still ahead. | n/a |
| `specs/native-engine.md` | keep | The rewrite's governing spec; its later phases are still ahead. | n/a |
| `specs/pipeline-predict-proba.md` | archive | Built in the old Python (#59, merged `8288e35`). | `architecture/engine-inventory.md` |
| `specs/selection-by-group.md` | keep | Built and merged (`d1a32ed`) and described in `architecture/testing.md`, which cites it as the spec; its audit's first real run still waits on the go-ahead in `HANDOFF.md` (question 2). | `architecture/testing.md` |

### docs/plans/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `plans/README.md` | keep | The folder's README. | n/a |
| `plans/2026-11-03-foundation.md` | archive | Implemented: the foundation (part 3.1) is built. | Nothing |
| `plans/2026-11-04-library-core.md` | archive | Implemented in the old Python (issue #8). | Nothing |
| `plans/2026-11-06-library-preprocessing.md` | archive | Implemented in the old Python (#30). | Nothing |
| `plans/2026-11-07-library-model-selection.md` | archive | Implemented in the old Python (#33). | Nothing |
| `plans/2026-11-09-fix-batch.md` | archive | Implemented: its issues were fixed in the old Python (for example `d7f1938` for #32). | Nothing |
| `plans/2026-11-09-library-metrics.md` | archive | Implemented in the old Python (#34). | Nothing |
| `plans/2026-11-10-fix-batch-2.md` | archive | Implemented in the old Python (for example `cc6cfdd`, `53dc701` for #43; `04a54a5` records the batch). | Nothing |
| `plans/2026-11-10-fix-batch-3.md` | archive | Implemented in the old Python (for example `a0d4a9b` for #53; `cdb177f` records the batch). | Nothing |
| `plans/2026-11-10-library-datasets.md` | archive | Implemented, and the datasets later left the package (ADR 0053, ADR 0073). | Nothing |
| `plans/2026-11-11-library-saving-the-model.md` | archive | Implemented in the old Python (#55). | Nothing |
| `plans/2026-11-11-library-saving.md` | archive | Implemented in the old Python (#57). | Nothing |
| `plans/2026-11-13-library-more-metrics.md` | archive | Implemented in the old Python (#58). | Nothing |
| `plans/2026-11-15-holdout-rows.md` | archive | Implemented in the old Python (#60, merged `ed06a24`). | Nothing |
| `plans/2026-11-15-pipeline-predict-proba.md` | archive | Implemented in the old Python (#59, merged `8288e35`). | Nothing |
| `plans/2026-11-17-learn-nested-aggregates.md` | archive | Implemented in the old Python (#49, merged `b1599cf`). | Nothing |
| `plans/2026-11-18-datasets-many-threads.md` | archive | Implemented (#46, merged `591b2ba`). | Nothing |
| `plans/2026-11-19-library-balanced-scores.md` | archive | Implemented in the old Python (#62, merged `d9c2b18`). | Nothing |
| `plans/2026-11-19-library-feature-selection.md` | archive | Implemented in the old Python (#65, merged `717a286`). | Nothing |
| `plans/2026-11-19-library-regression-metrics.md` | archive | Implemented in the old Python (#63, merged `88e12ce`). | Nothing |
| `plans/2026-11-20-library-decomposition.md` | archive | Implemented in the old Python (#66, merged `cdb2aec`). | Nothing |
| `plans/2026-11-20-library-exploration.md` | archive | Implemented in the old Python (#74, merged `b779980`). | Nothing |
| `plans/2026-11-21-native-engine-phase-0a-decisions.md` | archive | Implemented: Phase 0 merged (`dc2bfa3`), and `41e64cf` marks plan 0a done. | Nothing |
| `plans/2026-11-21-native-engine-phase-0b-inventory.md` | archive | Implemented: the profile (`f254178`, `46db428`) and the inventory (`5488e8a`) landed, and Phase 0 closed (`fb99ae1`). | `architecture/engine-inventory.md` (its output) |
| `plans/2026-11-21-native-engine-phase-0c-revision.md` | archive | Implemented: the revision landed (`957c496`) inside the merged Phase 0 (`dc2bfa3`). | Nothing |
| `plans/2026-11-22-native-engine-phase-1-checks-rework.md` | archive | Implemented: per-check selection landed (`f49d879`, `00900f0`) and step 1 merged (`af9a70b`). | Nothing |
| `plans/2026-11-22-native-engine-phase-1-checks.md` | archive | Executed, and its selection then replaced by the rework plan (which says so); step 1 merged (`af9a70b`). | `plans/2026-11-22-native-engine-phase-1-checks-rework.md` (also archive) |
| `plans/2026-11-23-native-engine-phase-1-build.md` | archive | Implemented: step 2 merged (`84e674d`). | Nothing |
| `plans/2026-11-27-bazel-prototype.md` | keep | Not yet carried out (next after the docs cleanup in `HANDOFF.md`). | n/a |
| `plans/2026-11-27-docs-cleanup.md` | keep | In progress; the plan archives itself at its end. | n/a |
| `plans/2026-11-27-old-python.md` | archive | Implemented (`d4f7d3b`, `55cd48e`, merged); the docs-cleanup plan archives it at its end. | Nothing |
| `plans/2026-11-27-selection-by-group.md` | keep | Merged (`d1a32ed`), but its Task 6 Step 4 (`just audit-groups` once) is the run `HANDOFF.md` lists as waiting on the go-ahead. | Nothing |

### docs/questions/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `questions/README.md` | amend | Its rule says an answered question is deleted, or stays marked as answered when an ADR cites its research, which the cleanup plan's `archived/` folder now replaces. | The rule rewritten to "answered questions move to `questions/archived/`". |
| `questions/agents-and-skills.md` | keep | Open: the candidates are "decided by research, then Tomas" and none is created; `workflow.md` links it (its `estimator-contract` row still says fit/transform/predict, the verbs ADR 0013 replaced). | — |
| `questions/application-front-end.md` | keep | Open: the front end is to be decided in the exploratory data analysis spec, and the overview and the native-engine spec link it. | — |
| `questions/applications-home.md` | keep | Open: decided "when the first application starts", which has not happened. | — |
| `questions/benchmarks-scope.md` | keep | Open: which libraries, machine and sizes are "decided by Tomas, in the benchmarks spec", which does not exist yet. | — |
| `questions/engine-compute-libraries.md` | archive | Says "Answered by ADR 0063 on 2026-11-21, and kept as the research behind it"; ADR 0063, the native-engine spec and HANDOFF's dead ends link it, so their links must follow the move. | ADR 0063 |
| `questions/fit-execution-model.md` | archive | Marked answered (ADRs 0012, 0013, 0014) and says it is deleted with the earlier-attempt reviews, which go whole; ADRs 0002 and 0012 link it. | ADRs 0012, 0013, 0014 |
| `questions/free-threaded-python.md` | keep | Still open (HANDOFF lists it as an open question), though its "to decide in Phase 1 step 2" has passed: step 2 is merged and nothing was decided. | — |
| `questions/multi-engine-support.md` | amend | Open future work (#54 open), but it describes the old Python as today's ("Polars already sits at the edges: frames can be passed in, and `feed="polars"`", the learning store, #50), none of which exists in the package since ADR 0073. | — |
| `questions/onehot-list-column.md` | keep | A kept idea tracked in #22, which is open; its example and benchmark are the old Python's pipeline, so revisiting it means the C++ planner's runs. | — |
| `questions/scikit-learn-api-survey.md` | keep | Says "the survey itself is still to be done", and ADR 0003's consequences send every component design to it; only the verbs are decided (ADR 0013). | — |
| `questions/test-selection.md` | amend | Open (2026-11-27, "no decision taken yet"), but its baseline (§9 and Part B §0) describes 24 runners taking about 47 minutes, `devdata/data/` and a frozen Python library under ADR 0070, which ADR 0073 changed: no runner exists now. | — |
| `questions/validation-method.md` | keep | Two points stay open (the rule for iterative algorithms, the page's presentation); ADR 0016 answers the rest, and the validation pages are still to be built. | — |
| `questions/earlier-attempts/` (whole, 39 files)` | archive | Its README's plan is complete (all 12 steps ticked, every attempt "merged"), and step 12 says it closed the drain into the decisions of issue #8, now ADRs 0012–0016, which cite it as evidence; it also names local paths outside the repository. | ADRs 0012–0016 (the decisions); the evidence stays readable in `archived/` |

### docs/architecture/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `architecture/README.md` | keep | One-line folder note ("how the system works now"), true of the folder. | — |
| `architecture/index.md` | keep | The section's toctree; lists only pages that exist. | — |
| `architecture/overview.md` | amend | Stale since ADRs 0070 and 0073: "Status, 2026-11-03: the foundation (3.1) is built; everything else is the plan"; 3.10's "not slower than the Python it replaced" (ADR 0073: no group is benchmarked against it); "Now (2026-11-21): Phase 0 is done (merge pending) … after HANDOFF's three small fixes"; the runtime `duckdb` "until then, the one from PyPI" (Phase 1 step 2 is merged); 3.2 and 3.3 describe built areas whose code is now only in `old_python/`. | — |
| `architecture/engine-inventory.md` | amend | Maps "every module of `src/sqlearn`" with the phase "whose merge deletes the module's Python", and says "Files saved before the port still load"; since ADR 0073 those modules are in `old_python/`, already out of the package, each group is designed afresh rather than ported (ADR 0070), and files saved before the rewrite need not load. | — |
| `architecture/workflow.md` | keep | The spec-to-merge flow, the tiers' table and the document locations match `testing.md` and the current recipes. | — |
| `architecture/setup.md` | amend | Current on the toolchain and hooks, but its recipe table, which claims to list every recipe, lacks `audit-groups`, `bench` and `benchmarks-due`, which the justfile has. | — |
| `architecture/layout.md` | amend | Updated for `old_python/`, but the tree shows a root `benchmarks/` that does not exist, says `validation/` holds "the validation runners" (none since ADR 0073), and says tests need no `conftest.py` while `tests/conftest.py` exists. | — |
| `architecture/python-versions.md` | keep | Restates ADR 0007's policy and the 3.12–3.14 matrix, which `pyproject.toml` and the justfile still carry (unsure only whether "DuckDB publishes wheels" still reads right now that sqlearn builds its own DuckDB, ADR 0061; ADR 0007 was not amended). | — |
| `architecture/writing.md` | amend | The rules hold, but its Markdown and reStructuredText rule names the gallery's sphinx-gallery files and "the reference index's `autosummary`", while the reference moved to `old_python/` (ADR 0073) and `docs/conf.py` no longer loads sphinx-gallery. | — |
| `architecture/testing.md` | keep | Written for the current state: `tests/src/` empty, the old runners and benchmark scripts in `old_python/`, selection by group, the audit awaiting go-ahead. | — |
| `architecture/validation.md` | keep | Written for the current state: "None today" of runners, the 24 old ones in `old_python/validation/` (ADR 0073), and the method, the records and the plan for the new runners. | — |

### docs/agents/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `agents/domain.md` | keep | Agents' setup: how skills read `GLOSSARY.md` and `docs/adr/`, which is true of the repository. | — |
| `agents/issue-tracker.md` | amend | The `gh` conventions hold, but its list of milestones ("one per part of the overview") omits the open "Native engine" milestone, which the repository has (#78 to #84). | — |
| `agents/triage-labels.md` | keep | Agents' setup: the five labels CLAUDE.md names. | — |
| `agents/working-with-tomas.md` | keep | Current habits, citing ADRs 0070 and 0072. | — |

### docs/benchmarks/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `benchmarks/index.md` | keep | The section's toctree; it follows whichever pages stay, and its intro ("how fast sqlearn runs") then needs to say the pages measured the old Python. | — |
| `benchmarks/engine-profile.md` | amend | ADR 0072 keeps it for a rerun "before Phase 4's order is fixed" and `engine-inventory.md` orders Phase 4 from it, but its reproduce line runs `validation.benchmarks.engine_profile`, now under `old_python/` and never run (ADR 0073). | — |
| `benchmarks/gram-batches.md` | amend | ADR 0072 keeps it for a rerun "at the start of Phase 2", but its reproduce line runs `validation.benchmarks.gram_batches`, now under `old_python/` and never run (ADR 0073). | — |
| `benchmarks/explore-correlations.md` | keep | ADR 0072 keeps it for a rerun with the explore group; it has no script to repoint, and the exploration spec links it. | — |
| `benchmarks/explore-larger-than-memory.md` | keep | ADR 0072 keeps it for a rerun with the explore group; it says its probe scripts were never in the repository. | — |
| `benchmarks/generators-on-many-threads.md` | archive | Unsure: ADR 0072 says it "measures `devdata/`, which stays Python, and waits for #46", but ADR 0073 (later the same day) moved `devdata/` to `old_python/`, never run, and #46 is closed, so nothing it measures can be rerun. | Nothing |
| `benchmarks/onehot-second-run.md` | keep | Unsure: not named in ADR 0072 and only the old Python's pipeline, but it is the evidence the open question `onehot-list-column.md` (#22, open) cites; its reproduce line points at a script now in `old_python/`. | — |
| `benchmarks/category-lookup.md` | archive | Unsure: it measured the old encoders and set their `WARN_ABOVE` threshold (#31), and ADR 0072 does not name it; ADR 0036 cites it, so its fate follows that ADR's (keep as evidence if 0036 stays current). | Nothing yet; a C++ encoders' benchmark when that group is rewritten |
| `benchmarks/gram-streaming.md` | keep | Unsure: ADR 0072 does not name it though it says it was measured "heavily loaded"; the native-engine spec cites it, and Phase 2 replaces the Python Gram stream it measured; its reproduce line points at a script now in `old_python/`. | — |
| `benchmarks/median-reach.md` | keep | Unsure: not named in ADR 0072, it measured the old Python's exact median, but ADRs 0032 and 0051 and `multi-engine-support.md` cite it as the measured reach; its reproduce line points at a script now in `old_python/`. | — |
| `benchmarks/standard-deviation.md` | keep | Unsure: not named in ADR 0072, it measured the old Python's two-pass standard deviation, and ADR 0044 cites it; its fate follows that ADR's, and its reproduce line points at a script now in `old_python/`. | — |

### docs/validation/

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `validation/index.md` | keep | The placeholder for ADR 0016's published pages, which HANDOFF and `architecture/validation.md` say are still to be built. | — |

### docs/ (top level)

| file | verdict | why | what replaces it |
| --- | --- | --- | --- |
| `index.md` | keep | Already says sqlearn is rebuilt from scratch in C++ and that the API, guide and lessons return with the rebuild. | — |
| `bibliography.md` | keep | The site's one bibliography (ADR 0009, foundation spec), loaded by `conf.py`; `references.bib` has no entry yet and no page cites one. | — |

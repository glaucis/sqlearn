---
type: plan
tags: [feature-selection, library-breadth, select, plan]
summary: "Implementation plan for feature selection (sq.select.variance, best, percentile with f_classif, f_regression and chi2), the target step that does not cross-fit (ADR 0055) and settings kept out of the learn key (ADR 0056)."
related: [docs/specs/archived/library-feature-selection.md, docs/adr/0055-a-target-step-need-not-cross-fit.md, docs/adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md]
---
# Feature Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sq.select.variance`, `sq.select.best` and `sq.select.percentile`,
scoring by `f_classif`, `f_regression` or `chi2`, as scikit-learn 1.9.1's
`VarianceThreshold`, `SelectKBest` and `SelectPercentile`, computed in DuckDB.

**Architecture:** Two contract changes first: a target step may declare that
it does not cross-fit (`cross_fits = False`, ADR 0055), and a step may name
settings that stay out of its learn key (`output_settings`, ADR 0056). The
feature selectors are dynamic whole-row steps in a new package
`sqlearn.feature_selection`: `learn(x, y)` returns per-column aggregates (per
class through the existing grouped marker `target_stats`, with the target as
the category), the scores are finished in Python from the fetched sums, and
`apply_row` returns the kept columns.

**Tech Stack:** Python 3.12, DuckDB (the only runtime dependency), uv, just,
pytest, scikit-learn 1.9.1 and numpy as test-only references.

**Spec:** `docs/specs/library-feature-selection.md` (approved 2026-11-19).
Read it beside this plan; section numbers below are the spec's.

## Global Constraints

- Every task runs through `just`; Python through `uv run`, never pip or a
  bare `python` (ADR 0001, 0008).
- Computation is SQL in DuckDB; Python only ranks the few numbers fetched
  (spec §3 rule 2).
- Behaviour, defaults and edge rules are scikit-learn 1.9.1's; where the spec
  and scikit-learn disagree, build scikit-learn's and correct the spec in the
  same commit (spec §3 rule 1).
- Every refusal and warning has `Why:` and `Fix:` (ADR 0019, 0046).
- British English in prose, American spelling in identifiers (ADR 0010).
- A step of `sq.select` is a "feature selector" in prose, never a
  "selector" (spec §8).
- Commits: Conventional Commits, no scope but `hooks`, `site`, `deps`, header
  at most 72 characters, no AI attribution, issue number in the header.
- Before every commit: `just fmt`, `just check`, `just test`, naming every
  failure. Before calling the work done: `just verify`.
- TDD: watch each test fail for the right reason first; tests through public
  seams, named in `GLOSSARY.md` terms.

## Review Focus

1. **A text column chosen by name** (`sq.select.best("city")`): refused at
   `inputs` with a `Fix:` naming an encoder, never a DuckDB cast error.
   Test in Task 3.
2. **A target of text classes** (`"yes"`/`"no"`) with `f_classif` and
   `chi2`: scored as scikit-learn scores string labels. Test in Task 4.
3. **A later step after a feature selector** (`sq.scale()` with its default
   numeric columns): sees only the kept columns, in a pipeline and in each
   fold of a search. Test in Task 6.
4. **Columns differing only by case** (`a`, `A`) among the scored columns:
   both scored and ranked, as ADR 0035's naming keeps them apart. Test in
   Task 4.
5. **A NaN (not NULL) in a scored column** from a DuckDB table: refused for
   the scores, ignored by `variance`. Pandas hands NaN as NULL, so the test
   inserts into a DuckDB table (HANDOFF trap). Tests in Tasks 3 and 4.

---

### Task 0: Branch and issue

- [ ] **Step 1:** `git switch -c feature-selection` from `main`.
- [ ] **Step 2:** Open the area's issue with `gh issue create` (title
  "Library breadth: feature selection", label `enhancement`, body linking the
  spec, ADRs 0055 and 0056, and #64), add it to the board as the github-pm
  skill says, and use its number (written `#65` below) in every commit header.
- [ ] **Step 3:** Commit the spec, the two ADRs, `docs/adr/index.md`, this
  plan and the `Fwe` entry in `pyproject.toml`:
  `docs: specify feature selection (#65)`.

### Task 1: A target step that does not cross-fit (ADR 0055)

**Files:**
- Modify: `src/sqlearn/_step.py` (class attributes and docstring of `Step`)
- Modify: `src/sqlearn/_plan.py` (lines near 208, 218, 226, 346)
- Modify: `src/sqlearn/_pipeline.py` (near 348, 378, 895, 1130)
- Modify: `src/sqlearn/_compose.py` (near 397, 436, 568)
- Modify: `src/sqlearn/model_selection/search.py` (near 644)
- Modify: `src/sqlearn/preprocessing/target.py` (declares `cross_fits`)
- Test: `tests/src/sqlearn/test__pipeline.py`, `tests/src/sqlearn/test__plan.py`

**Interfaces:**
- Produces: `Step.cross_fits: ClassVar[bool] = True` (read only when
  `uses_target` is True; `TargetEncoder` keeps the default) and
  `sqlearn._step.cross_fitted(step: Step) -> bool` returning
  `step.uses_target and step.cross_fits`.

Each site that today reads `uses_target` to mean "cross-fits" reads
`cross_fitted(step)` instead: the `cv`/`seed` check (`_check_target_step`),
ending the run and the one-DOUBLE output in the planner, the placeholder skip
in `_plan.py:346`, `_derive`, `_after_unapplied`'s DOUBLE, the inner-fold
columns in `_features`, `_derived` and `_cross_fitted` in `_compose.py`, and
`_positioned` in the search. The sites meaning "learns from the target" keep
`uses_target`: the target passed to `learn` (`_compose.py:404`), `learn`
without `target=` refused (`_pipeline.py:676`), the store key holding the
target's name.

- [ ] **Step 1: Write the failing tests**, in `test__pipeline.py`, with a
  step defined in the test: `uses_target = True`, `cross_fits = False`,
  `dynamic = True`, no `cv` or `seed`, learning
  `{"r": duckdb.FunctionExpression("corr", x, y)}` and keeping a column when
  `r > 0`:
  - `test_a_target_step_that_does_not_cross_fit_learns_once_on_all_rows`:
    after `train`, its learned `r_` equals `numpy.corrcoef` on all rows
    (`rel=1e-12`), and the model was trained on the kept columns only.
  - `test_a_target_step_that_does_not_cross_fit_needs_no_cv_or_seed`: the
    pipeline plans and trains (no `StepError` about `cv`).
  - `test_learn_without_target_refuses_a_step_that_does_not_cross_fit`:
    `learn(data)` raises `StepError` matching `"learns from the target"`.
- [ ] **Step 2:** Run `uv run pytest tests/src/sqlearn/test__pipeline.py -k
  cross_fit`; expected FAIL on the `cv` check.
- [ ] **Step 3:** Add `cross_fits` and `cross_fitted`, document both in
  `Step`'s docstring (rewrite its `uses_target` entry so cv, seed, ending the
  run and one DOUBLE are said of a cross-fitting step), and switch the sites
  above.
- [ ] **Step 4:** Run the new tests, then `uv run pytest
  tests/src/sqlearn/preprocessing/test_target.py
  tests/src/sqlearn/model_selection`; expected all PASS, with
  `sq.encode.target`'s tests unchanged.
- [ ] **Step 5:** `just fmt`, `just check`, `just test`; commit
  `feat: a target step need not cross-fit (#65)`.

### Task 2: Settings kept out of the learn key (ADR 0056)

**Files:**
- Modify: `src/sqlearn/_step.py` (class attribute, docstring)
- Modify: `src/sqlearn/_store.py` (`step_key`)
- Test: `tests/src/sqlearn/test__store.py`,
  `tests/src/sqlearn/model_selection/test_search.py`

**Interfaces:**
- Produces: `Step.output_settings: ClassVar[frozenset[str]] = frozenset()`.
  `step_key` leaves these settings out of the chain entry of the step at
  `index` only; a step depending on it (in `depends_on`) keeps them all.

- [ ] **Step 1: Write the failing tests:**
  - `test__store.py::test_a_setting_that_only_chooses_the_output_is_not_in_the_learn_key`:
    two instances of a test step with `output_settings = frozenset({"k"})`
    differing only in `k` give equal `step_key(...)` at their own index; a step
    after them depending on them gets different keys.
  - `test_search.py::test_a_search_over_an_output_setting_learns_each_fold_once`:
    a search over `params={"pick__k": [1, 2, 3]}` with `sq.folds.kfold(3)` and a
    test step counting calls of its `learn` (a class-level counter) learns 3
    times per learned column (once per fold) plus the final training, not 9.
  - `test_search.py::test_a_search_over_a_learning_setting_learns_per_setting`:
    the same step with a second setting not in `output_settings` learns per
    setting.
- [ ] **Step 2:** Run them; expected FAIL (keys differ, 9 learns).
- [ ] **Step 3:** Implement the exclusion in `step_key`; document
  `output_settings` in `Step` and `step_key`'s docstring. `Entry.apply_sql`
  is informational (apply rebuilds from `values`), so nothing else changes;
  if a test shows otherwise, stop and report.
- [ ] **Step 4:** Run the tests and `uv run pytest tests/src/sqlearn`;
  expected PASS.
- [ ] **Step 5:** Checks; commit
  `feat: keep output-only settings out of the learn key (#65)`.

### Task 3: The group and `sq.select.variance` (spec §4, §4.1)

**Files:**
- Create: `src/sqlearn/feature_selection/__init__.py`,
  `src/sqlearn/feature_selection/_select.py` (the group),
  `src/sqlearn/feature_selection/variance.py`
- Modify: `src/sqlearn/__init__.py` (export `select`),
  `docs/reference/index.md`
- Test: `tests/src/sqlearn/feature_selection/test__select.py`,
  `tests/src/sqlearn/feature_selection/test_variance.py`

**Interfaces:**
- Produces: `class VarianceThreshold(Step)` with
  `__init__(self, threshold: float = 0.0, cols=_numeric())`, `dynamic = True`,
  `rowwise = True`, `keeps_inputs = True`,
  `output_settings = frozenset({"threshold"})`, `default_name() -> "variance"`,
  `__repr__` as `sq.select.variance(threshold=0.5)`; learned names
  `variance` (population variance, NULL and NaN ignored), `low`, `high`;
  property `variances_: dict[str, float]` as scikit-learn's (the smaller of
  the variance and `high - low` at `threshold=0`).
- Produces: `class SelectGroup(Group)`, `select = SelectGroup("select")` with
  `variance(*names, threshold=0.0, cols=None)`; Tasks 4 and 5 add `best` and
  `percentile`. Build it as `EncodeGroup` in
  `src/sqlearn/preprocessing/_encode.py` is built.
- Uses: `_numeric_inputs` from `src/sqlearn/preprocessing/scale.py` for the
  text refusal (move it to a shared module if importing it across packages
  reads badly).

- [ ] **Step 1: Write the failing tests** (`test_variance.py`), each
  comparing with `sklearn.feature_selection.VarianceThreshold` on the same
  frame:
  - `test_variance_keeps_the_columns_scikit_learn_keeps` (threshold 0 and
    0.5, columns kept and `columns_out_` order),
  - `test_variances_match_scikit_learn` (`rel=1e-12`),
  - `test_a_constant_column_is_dropped_whatever_its_rounding` (1,000 rows of
    0.1),
  - `test_variance_ignores_nan_and_null` (NaN inserted into a DuckDB table),
  - `test_variance_raises_when_no_column_passes` (match `"threshold"` and
    `"Fix:"`),
  - `test_variance_refuses_a_negative_threshold` and
    `test_variance_refuses_a_text_column` (match `"Fix:"`),
  - `test_a_search_over_the_threshold_learns_each_fold_once` (as Task 2's).
  - `test__select.py::test_the_shortcut_is_the_general_form`: `repr`,
    `settings()` and store key of `sq.select.variance(threshold=0.5)` equal
    those of `VarianceThreshold(threshold=0.5)`.
- [ ] **Step 2:** Run them; expected FAIL (`sq.select` missing).
- [ ] **Step 3:** Implement. The selection itself, in `apply_row`: at
  `threshold == 0`, keep a column when `high > low` and `variance > 0`; else
  when `variance > threshold`. Raise the no-column error there.
- [ ] **Step 4:** Run; expected PASS. Add `sqlearn.select.variance` and
  `sqlearn.feature_selection.VarianceThreshold` to `docs/reference/index.md`.
- [ ] **Step 5:** Checks; commit `feat: add sq.select.variance (#65)`.

### Task 4: The scores and `sq.select.best` (spec §4.2, §4.4, §5.1, §6)

**Files:**
- Create: `src/sqlearn/feature_selection/_scores.py`,
  `src/sqlearn/feature_selection/univariate.py`
- Modify: `_select.py`, `__init__.py`, `docs/reference/index.md`
- Test: `tests/src/sqlearn/feature_selection/test__scores.py`,
  `tests/src/sqlearn/feature_selection/test_univariate.py`

**Interfaces:**
- Produces in `_scores.py`: `SCORES = ("f_classif", "f_regression", "chi2")`;
  `learn_score(score: str, x: Expression, y: Expression) -> dict[str,
  Expression]`; `finish_score(score: str, values: Mapping[str, object]) ->
  float` (one column's score from what it learned, NaN where scikit-learn
  gives NaN).
  - `f_classif` and `chi2` learn `target_stats(y, x_shifted, const(0))`
    (`sqlearn._expr.target_stats` with the target as the category and the
    column as the value, one constant fold), plus `count`, `min(x)` and the
    missing count. `f_classif` is shift-invariant; `chi2` adds back
    `n_class * min(x)` per class. Check first that the marker accepts a
    constant fold; if not, stop and report.
  - `f_regression` learns `count`, `covar_pop(x, y)`, `var_pop(x)`,
    `var_pop(y)` and the missing count; F = r² / (1 - r²) · (n - 2), with
    `force_finite`: NaN (constant column or target) → 0, infinite → the
    largest double.
- Produces in `univariate.py`: `class SelectKBest(Step)` with
  `__init__(self, k: int | str = 10, score: str = "f_classif",
  cols=_numeric())`, `uses_target = True`, `cross_fits = False`,
  `dynamic = True`, `rowwise = True`, `keeps_inputs = True`,
  `output_settings = frozenset({"k"})`, `default_name() -> "best"`,
  property `scores_: dict[str, float]`. The ranking in `apply_row`: a NaN
  score lowest, then the k highest by a stable sort, ties to the later
  column (scikit-learn's `argsort(kind="mergesort")[-k:]`).
- Group: `select.best(*names, k=10, score="f_classif", cols=None)`.

- [ ] **Step 1: Write the failing tests:**
  - `test__scores.py::test_each_score_matches_scikit_learn` (parametrised
    over the three scores, 200 rows, 6 columns, `scores_` against
    `f_classif`/`f_regression`/`chi2` at `rel=1e-9`), with
    `test_scores_of_text_classes_match_scikit_learn` (Review Focus 2) and
    `test_columns_differing_only_by_case_are_scored_apart` (Review Focus 4).
  - `test_univariate.py`: `test_best_keeps_the_columns_scikit_learn_keeps`
    (k 1, 3, 6, "all"), `test_ties_keep_the_later_column`,
    `test_a_constant_column_ranks_last_and_is_warned_about` (f_classif
    NaN, one `SqlearnWarning` naming the column),
    `test_k_above_the_column_count_keeps_all_and_warns`,
    `test_k_zero_keeps_none_and_warns` (another column passes beside it),
    `test_learn_raises_when_no_column_would_remain` (`"Fix:"`),
    `test_chi2_refuses_a_negative_value`,
    `test_the_scores_refuse_a_missing_value` (NULL from pandas, NaN from a
    DuckDB table; Review Focus 5),
    `test_a_missing_target_is_refused`,
    `test_best_refuses_a_bad_k_or_score` (`-1`, `2.5`, `True`, `"f"`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement. Refusals that depend on the learned values
  (missing values, negative values for chi2, nothing left) raise `StepError`
  from `apply_row`, which runs for every fold; warnings (constant columns,
  `k` above the count, `k=0`) go in `learned()`, which runs once per
  `learn` or `train`. No `pvalues_` (spec §6): the class docstring says so
  and names the later p-value selectors.
- [ ] **Step 4:** Run; expected PASS. Reference entries added.
- [ ] **Step 5:** Checks; commit
      `feat: add sq.select.best and its scores (#65)`.

### Task 5: `sq.select.percentile` (spec §4.3)

**Files:**
- Modify: `univariate.py`, `_select.py`, `__init__.py`,
  `docs/reference/index.md`
- Test: `tests/src/sqlearn/feature_selection/test_univariate.py`

**Interfaces:**
- Consumes: Task 4's `learn_score`, `finish_score` and the base it shares
  with `SelectKBest` (put the shared learn and `scores_` in a private
  `_Univariate(Step)` base).
- Produces: `class SelectPercentile(_Univariate)` with
  `__init__(self, percentile: float = 10, score: str = "f_classif",
  cols=_numeric())`, `output_settings = frozenset({"percentile"})`,
  `default_name() -> "percentile"`. Its mask is scikit-learn's
  `SelectPercentile._get_support_mask` (spec §4.3): the threshold is
  `numpy.percentile`'s linear interpolation, computed in Python from the
  scores.

- [ ] **Step 1:** Failing tests:
  `test_percentile_keeps_the_columns_scikit_learn_keeps` (5, 10, 50, 99,
  100 on 13 columns), `test_percentile_ties_keep_the_earlier_columns`,
  `test_percentile_zero_keeps_none_and_warns`,
  `test_percentile_refuses_a_value_outside_0_to_100`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5:** Checks; commit `feat: add sq.select.percentile (#65)`.

### Task 6: Pipelines, searches and saving (spec §2, §7)

**Files:**
- Test: `tests/src/sqlearn/feature_selection/test_pipelines.py` (or the
  closest existing pipeline test file if the mirror check refuses a test
  file with no source module)

- [ ] **Step 1:** Failing or passing, these pin the integration:
  - `test_the_spec_script_predicts_as_scikit_learn` (spec §2's pipeline
    against `make_pipeline(SimpleImputer, VarianceThreshold, SelectKBest,
    LogisticRegression)`; predictions equal),
  - `test_a_search_over_k_picks_scikit_learns_setting` (sqlearn's folds
    handed to `GridSearchCV` as splits),
  - `test_a_later_step_sees_only_the_kept_columns` (Review Focus 3, in
    `train` and in a search fold),
  - `test_a_learned_feature_selector_is_found_in_the_store` (second `learn`
    runs nothing: `runs_ == []`),
  - `test_each_feature_selector_saves_and_loads` (`sq.save` then `sq.load`,
    same `apply` output; check `_saving` needs no class list change, and
    probe the load path as the HANDOFF's `sq.load` security note says).
- [ ] **Step 2:** Run; fix what fails in the module that owns it, test first.
- [ ] **Step 3:** One slow test: `variance` and `best` learned on Parquet
  larger than a `memory_limit` set below its size, marked as the earlier
  areas' slow tests are.
- [ ] **Step 4:** Checks; commit
  `test: feature selectors in pipelines, searches and files (#65)`.

### Task 7: Validation (spec §6, §7)

**Files:**
- Create: `validation/sqlearn/feature_selection/__init__.py`,
  `validation/sqlearn/feature_selection/validate_select.py`
- Modify: `validation/__main__.py` (`RUNNERS`)
- Results: `validation/sqlearn/feature_selection/select.results.json`,
  `validation/tests.json`

- [ ] **Step 1:** Write the runner as `validate_regression.py` is written:
  datasets from `validation/_cases.py`, each score and each variance against
  the exact value (fractions for the sums; mpmath for the F), against
  scikit-learn and numpy, with `BOUNDS` set from the first measurement and a
  comment saying why (ADR 0016); the kept columns compared exactly
  (`_cases.exact_case`).
- [ ] **Step 2:** Run it alone (one runner, as the HANDOFF says), and
  expect no `fail`, every anomaly explained in the module docstring:

  ```bash
  PYTHONPATH=. uv run python -c "
  import importlib, sys
  from validation.__main__ import main, ROOT
  name = 'validation.sqlearn.feature_selection.validate_select'
  sys.exit(main([importlib.import_module(name)], ROOT))
  "
  ```
- [ ] **Step 3:** Commit the runner and its results:
  `test: validate the feature selectors (#65)`.

### Task 8: Documentation and state (spec §8, §11)

**Files:**
- Create: `docs/guide/selecting-features.md`
- Modify: `docs/guide/index.md` (after "Making features"),
  `docs/guide/from-scikit-learn.md`, `GLOSSARY.md` (feature selector),
  `CLAUDE.md` (the area built), `HANDOFF.md`

- [ ] **Step 1:** The guide page as executed MyST code cells, like
  `docs/guide/making-features.md`: why select, each feature selector, the
  scores, the search over `k` learning once per fold, and the edge rules a
  reader meets (no column left, missing values).
- [ ] **Step 2:** `rm -rf docs/reference/generated docs/_build && just
  build-docs`; expected no warnings.
- [ ] **Step 3:** `just verify`; expected pass. Discard results files that
  differ only by thread-order ULPs (HANDOFF trap); keep `tests.json`.
- [ ] **Step 4:** Update `HANDOFF.md` (Just finished, Next up) and
  `CLAUDE.md`'s state line; commit `docs: the feature selectors are built
  (#65)`; summary comment on the issue with what landed and any departures.

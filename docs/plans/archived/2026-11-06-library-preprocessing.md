---
type: task
tags: [preprocessing, library-breadth, api, aggregates, impute, scale, encode, transform, bin, features, validation]
summary: "Implementation plan for the first area of sqlearn's library breadth: the grouped API, sq.agg, column naming, and the first preprocessing steps, in 16 tasks."
related: [docs/specs/archived/library-preprocessing.md, docs/adr/0034-a-grouped-api.md, docs/adr/0035-names-of-generated-columns.md, docs/specs/archived/library-core.md]
---
# Library Breadth: Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move sqlearn's public names into groups (ADR 0034), add `sq.agg`,
name created columns by one rule (ADR 0035), and build the first
preprocessing steps so that the script in spec §2 runs and matches
scikit-learn.

**Architecture:** A step group is an object: callable for the general form,
with one method per shortcut, each returning an ordinary `Step`. Aggregates
are `Aggregate` objects, usable as a step's value or called on a column;
sorted and grouped aggregates (quantiles, mode, per-category target stats)
are markers the compositor computes in stages of their own, generalising the
core's median. The step contract gains labels for created columns, a
whole-row form, and a target-learning form; the planner and compositor learn
each.

**Tech Stack:** Python 3.12+, duckdb 2.0 (the one runtime dependency); tests
and validation: pytest, scikit-learn 1.9.1, numpy, pandas, mpmath.

**Spec:**
[`docs/specs/library-preprocessing.md`](../../specs/archived/library-preprocessing.md).
"§N" below is a section of it; "core §N" is
[`library-core.md`](../../specs/archived/library-core.md); "ADR N" is
`docs/adr/00NN-*.md`. Read the spec, ADRs 0034 and 0035, and
`docs/guide/writing-a-step.md` before starting.

## Global Constraints

- Work on the branch `library-preprocessing` in the worktree
  `.claude/worktrees/library-preprocessing`
  (`superpowers:using-git-worktrees`). Merge only on Tomas's word.
- Runtime dependency: `duckdb>=2.0.0` only. `src/` never imports numpy,
  pandas, scipy or scikit-learn at module level; the spline basis is computed
  in pure Python.
- uv only (`uv run`); every task through `just`. Before every commit:
  `just fmt`, `just check`, `just test`. Never `--no-verify`. Conventional
  commits, scopes only `hooks`, `site`, `deps`; no AI attribution anywhere.
- Every module `src/sqlearn/X/Y.py` has `tests/src/sqlearn/X/test_Y.py`;
  every module under `preprocessing/`, `metrics/` and (from Task 2) `agg/`
  whose name does not start with `_` has `validation/sqlearn/X/validate_Y.py`
  (`just check-mirror`), listed in `validation/__main__.py`'s `RUNNERS`.
- British English in prose and docstrings, American spelling in identifiers.
  Public objects have numpydoc docstrings with an example
  (`just check-docstrings`).
- SQL is built from DuckDB expression objects; SQL text is written only by
  the compositor, every identifier through `quote()` (ADR 0015).
- DuckDB 2.0 facts: lambdas are `lambda x: ...`; NaN is not NULL and sorts
  greatest, so `max(x)` over a column with NaN is NaN (every aggregate
  filters with `present()`); column names ignore case; `error('msg')` raises
  `InvalidInputException` when evaluated; `create_view` is persistent (use
  `register`).
- Messages for a user's mistake follow ADR 0019: step name and position, what
  went wrong, why, the fix.
- Defaults follow scikit-learn 1.9.1's unless the spec says otherwise:
  `KBinsDiscretizer` defaults to `quantile_method="averaged_inverted_cdf"`
  and subsamples above 200,000 rows (validation passes `subsample=None`);
  `TargetEncoder(cv=...)` accepts an iterable of splits.
- Old public names are removed, not aliased (§3.1). Each task that moves a
  name updates every use of it in `src/`, `tests/`, `validation/`,
  `examples/` and `docs/` in the same commit, so the tree stays green.

## Review Focus

Inputs the spec implies but no task's main tests exercise, most likely first;
each has its test in the task named.

1. **Integer and decimal columns:** imputing and scaling `INTEGER`,
   `BIGINT` and `DECIMAL(10,2)` columns gives scikit-learn's DOUBLE values
   (the median and quantiles cast to DOUBLE): Task 7
   `test_scale_and_impute_integer_and_decimal_columns`.
2. **Unseen and missing categories in `encode.target`:** a category first met
   at `predict` and a NULL category both get the target's overall mean, as
   scikit-learn: Task 10 `test_target_unseen_and_null_get_the_overall_mean`.
3. **Constant columns in binning and splines:** `bin.uniform`,
   `bin.quantile` and `features.spline` on a column with one value give
   scikit-learn's output (one bin; constant basis), not a division by zero:
   Task 11 `test_bins_of_a_constant_column`, Task 13
   `test_spline_of_a_constant_column`.
4. **A dict naming a missing column:** `sq.impute({"agee": "median"})` is
   refused at `learn`, naming `agee` and the columns there: Task 6
   `test_a_dict_naming_a_missing_column_is_refused`.
5. **Equal aggregates built twice:** `sq.agg.quantile(q=0.9)` built in two
   places is one store key, so a search over it learns once per fold: Task 2
   `test_equal_aggregates_share_a_store_key`.

---

### Task 1: Groups for selectors, functions, output, errors and the store

**Files:**
- Create: `src/sqlearn/_group.py`, `src/sqlearn/fn.py`, `src/sqlearn/out.py`,
  `src/sqlearn/errors.py`, `src/sqlearn/store.py`
- Modify: `src/sqlearn/__init__.py`, `src/sqlearn/_selectors.py`,
  `src/sqlearn/_expr.py`, every use of the moved names
- Test: `tests/src/sqlearn/test__group.py`, `test_fn.py`, `test_out.py`,
  `test_errors.py`, `test_store.py`, `test__selectors.py`, `test_init.py`

**Interfaces:**
- Produces:
    <!-- markdownlint-disable-next-line MD013 -->
  - `sqlearn._group.columns_arg(names: tuple[object, ...], cols: object, *, allow_dict: bool) -> object`:
    `()` and `cols=None` give None (the group's default); one `str` gives that
    str; several give a list; one list or tuple gives a list; one dict gives the
    dict when `allow_dict`, else a `SqlearnError`; names and `cols=` together
    raise `SqlearnError` naming both.
  - `sqlearn._group.Group`: base for step groups; `__repr__` is
    `sq.<name>`; `__dir__` lists the shortcuts.
  - `sq.cols`: an object; `sq.cols("a", "b") -> Selector`,
    `sq.cols.numeric() -> Selector`, `sq.cols.string() -> Selector`.
  - `sq.fn`: module with `const`, `is_missing`, `ln`, `log10`, `exp`, `sqrt`,
    `abs`, `least`, `greatest`, `lower`, `upper`, `coalesce`, each
    `(*Expression | object) -> Expression`.
  - `sq.out`: `csv`, `json`, `parquet` (the core's `out_*`).
  - `sq.errors`: `SqlearnError`, `StepError`, `InternalError`,
    `SqlearnWarning`, `DefaultsUsedWarning`.
  - `sq.store.clear() -> None`: forgets every entry (closes #29).
  - `sq.metrics` stays the existing package.

- [ ] **Step 1: Write the failing tests**

```python
def test_cols_is_a_callable_group():
    assert sq.cols("a").resolve([("a", INTEGER), ("b", INTEGER)]) == ["a"]
    assert sq.cols.numeric().resolve([("a", INTEGER), ("b", VARCHAR)]) == ["a"]
    sel = sq.cols.numeric() - sq.cols("id")
    assert sel.resolve([("id", INTEGER), ("x", DOUBLE)]) == ["x"]


def test_the_top_level_holds_only_the_builders():
    public = {n for n in dir(sq) if not n.startswith("_")}
    for gone in [
        "Impute",
        "avg",
        "numeric",
        "out_csv",
        "accuracy",
        "StepError",
        "make_pipeline",
    ]:
        assert gone not in public  # moved names (the step ones go in Tasks 2-9)
    assert {"Pipeline", "Step", "Search", "set_config", "get_config"} <= public


def test_columns_arg_forms():
    assert columns_arg((), None, allow_dict=False) is None
    assert columns_arg(("a",), None, allow_dict=False) == "a"
    assert columns_arg(("a", "b"), None, allow_dict=False) == ["a", "b"]
    assert columns_arg((["a", "b"],), None, allow_dict=False) == ["a", "b"]
    with pytest.raises(SqlearnError, match="cols="):
        columns_arg(("a",), ["b"], allow_dict=False)
    with pytest.raises(SqlearnError, match="dict"):
        columns_arg(({"a": 1},), None, allow_dict=False)


def test_store_clear_relearns(con):
    pipe = sq.Pipeline([("scale", Scale())])  # the core's class until Task 7
    pipe.learn("t")
    sq.store.clear()
    pipe.learn("t")
    assert STORE.learns["scale"] == 1  # counts cleared, then one learn
```

`test_the_top_level_holds_only_the_builders` lists only the names this task
moves (`numeric`, `string`, `const`, `is_missing`, `out_*`, `Metric`,
`accuracy`, the errors); each later task adds its own to the list.

- [ ] **Step 2: Run them to see them fail**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run pytest tests/src/sqlearn/test__group.py tests/src/sqlearn/test_init.py tests/src/sqlearn/test_store.py -q`
Expected: FAIL (`ImportError` on `sqlearn._group`, moved names still present).

- [ ] **Step 3: Implement**

`sq.cols` is an instance of a small class in `_selectors.py` whose
`__call__` is today's `cols`. `fn.py` re-exports `const` and `is_missing`
from `_expr.py` and adds the rest as one-line `FunctionExpression`
builders. Remove the moved names from `sqlearn/__init__.py`'s imports and
`__all__`; add the modules `fn`, `out`, `errors`, `store`, `metrics` and
the object `cols`. Update every use (`sq.numeric()` →
`sq.cols.numeric()`, `sq.out_parquet` → `sq.out.parquet`, `sq.accuracy` →
`sq.metrics.accuracy`, `sq.StepError` → `sq.errors.StepError`) in `src/`,
`tests/`, `validation/`, `examples/`, `docs/`. Update
`docs/guide/inputs-and-the-store.md` to show `sq.store.clear()` as the
remedy instead of "waits for #23", and the `Pipeline.learn`/`train` and
`Search.train` docstrings likewise.

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: group selectors, functions, output, errors and the store` (body:
      `Closes #29`).

---

### Task 2: `sq.agg`

**Files:**
- Create: `src/sqlearn/agg/__init__.py`, `src/sqlearn/agg/aggregates.py`,
  `validation/sqlearn/agg/__init__.py`,
  `validation/sqlearn/agg/validate_aggregates.py`
- Modify: `src/sqlearn/_compose.py` (staged aggregates), `src/sqlearn/_expr.py`
  (remove `avg`, `median`, `stddev_pop`, `count`, `distinct_values`, `MEDIAN`),
  `src/sqlearn/preprocessing/_missing.py` (`present` moves to `agg`),
  `justfile` (`check-mirror`: add `agg|agg/*` beside `preprocessing`),
  `validation/__main__.py`, every use of the moved names
- Test: `tests/src/sqlearn/agg/test_aggregates.py`,
  `tests/src/sqlearn/test__compose.py`

**Interfaces:**
- Produces:
  - `class Aggregate` in `agg/aggregates.py`: `name: str`,
    `params: dict[str, object]`, `numeric_only: bool`;
    `__call__(self, x: Expression | None = None, **params) -> Expression | Aggregate`:
    with `x`, the expression; without, a new `Aggregate` with the params merged.
    Missing a required param with `x` raises `SqlearnError`. `__repr__` is
    `sq.agg.<name>` or `sq.agg.<name>(q=0.9)` (params sorted, defaults omitted);
    `__eq__`/`__hash__` on `(name, params)`.
  - Module attributes, each an `Aggregate`: `mean`, `median`, `quantile`
    (params `q`, `method="linear"`), `approx_quantile` (`q`), `iqr`
    (`q=(0.25, 0.75)`), `mode`, `min`, `max`, `range`, `maxabs`, `std`,
    `var`, `count`, `distinct`. `numeric_only` is False for `mode`, `min`,
    `max`, `count`, `distinct`.
  - `sqlearn.agg.aggregates.lookup(name: str) -> Aggregate | None`: the
    aggregate a string names (`"median"`), else None.
  - `sqlearn.agg.aggregates.present(x: Expression) -> Expression`: NULL for
    NULL and NaN (moved from `_missing.py`).
  - `quantile`'s `method` takes `"linear"` and `"averaged_inverted_cdf"`;
    another is refused naming both.
  - Compositor: a **staged marker** is any `__sqlearn_quantile(x, q, method)`
    or `__sqlearn_mode(x)` call. It may appear **anywhere** inside a learned
    expression (lifting the core's whole-value rule, so `iqr` is
    `quantile(0.75) - quantile(0.25)`). All quantile markers of a learn stage
    share one sort, as the core's medians do; mode is a `GROUP BY` stage
    (spills) ordered by count descending, then value ascending, first row.
    `median` is `quantile(q=0.5)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_aggregate_is_a_value_and_a_builder():
    x = duckdb.ColumnExpression("a")
    assert repr(sq.agg.median) == "sq.agg.median"
    assert repr(sq.agg.quantile(q=0.9)) == "sq.agg.quantile(q=0.9)"
    assert isinstance(sq.agg.quantile(x, q=0.9), duckdb.Expression)
    with pytest.raises(SqlearnError, match="q"):
        sq.agg.quantile(x)

def test_equal_aggregates_share_a_store_key():
    assert sq.agg.quantile(q=0.9) == sq.agg.quantile(q=0.9)
    assert hash(sq.agg.quantile(q=0.9)) == hash(sq.agg.quantile(q=0.9))
    # and a pipeline learning twice with separately built equal aggregates
    # records one learn (STORE.learns), via a test step using value=

def test_strings_name_aggregates():
    assert lookup("median") is sq.agg.median
    assert lookup("unknown") is None

@pytest.mark.parametrize("values,expected", [
    ([1.0, 2.0, 3.0, 4.0], {"median": 2.5, "q90": 3.7, "iqr": 1.5, "range": 3.0, "maxabs": 4.0}),
    ([1.0, None, float("nan"), 3.0], {"median": 2.0, "q90": 2.8, "iqr": 1.0, "range": 2.0, "maxabs": 3.0}),
])
def test_aggregates_leave_missing_out(values, expected): ...
    # learn each through a one-step pipeline; compare with numpy on the present values

def test_mode_ties_go_to_the_smallest():
    # values ["b", "a", "b", "a", "c"] → "a"; [3, 1, 1, 3] → 1

def test_quantile_markers_inside_an_expression_share_one_sort():
    # a step learning {"iqr": sq.agg.iqr(x), "med": sq.agg.median(x)} on two
    # columns: the learn statement holds exactly one row_number() window
```

- [ ] **Step 2: Run them to see them fail** —
      `uv run pytest tests/src/sqlearn/agg -q`; Expected:
      `ModuleNotFoundError: sqlearn.agg`.
- [ ] **Step 3: Implement**

Generalise `_median_of`/`_median_ctes` in `_compose.py` to find every staged
marker in a learned expression's text, compute each in the shared stages,
and substitute a reference to its column. Linear quantile of the `n` present
values sorted ascending (1-based ranks): position `h = (n - 1) * q + 1`,
value `x[floor(h)] + (h - floor(h)) * (x[floor(h)+1] - x[floor(h)])`.
`averaged_inverted_cdf`: `g = n * q`; if `g` is an integer, the mean of
`x[g]` and `x[g+1]`, else `x[ceil(g)]` (clamped to `[1, n]`). Every aggregate
wraps its column in `present()`. `std`/`var` are `stddev_pop`/`var_pop`;
`count` is `count(present(x))`; `distinct` is the core's histogram-based
`distinct_values`. Replace every `sq.avg`/`sq.median`/`sq.stddev_pop`/
`sq.count`/`sq.distinct_values` use with `sq.agg.*`. The validation runner
covers every aggregate per ADR 0016 (mpmath at 50 digits as the reference;
DuckDB's own function alone and at one thread; numpy; pandas where it has
one) on `validation/_cases.py`'s datasets, writing
`validation/sqlearn/agg/aggregates.results.json`; `approx_quantile` records
its error against the exact quantile and has no bound.

- [ ] **Step 4: Run `just test` and `uv run python -m validation`** — Expected:
      pass; the new results file is written.
- [ ] **Step 5: Commit** — `feat: add sq.agg with exact sorted aggregates`

---

### Task 3: Pipelines from plain lists, and step names

**Files:**
- Modify: `src/sqlearn/_pipeline.py`, `src/sqlearn/_step.py`,
  `src/sqlearn/__init__.py` (drop `make_pipeline`), every use of
  `make_pipeline`
- Test: `tests/src/sqlearn/test__pipeline.py`

**Interfaces:**
- Produces:
  - `Step.default_name(self) -> str`: the name a step gets in a plain list.
    `Step` returns `"step"`; a group's step returns the shortcut its
    settings match, else the group's name (Tasks 6–13 override it).
  - `Pipeline(steps: Sequence[Step | object | tuple[str, Step | object]])`:
    a plain item is named `step.default_name()`, or `"model"` for a model;
    names that clash are numbered from 1 in order (`median-1`, `median-2`);
    a given name never clashes silently (two equal given names are refused,
    as today).

The spec's §3.4 says a step built by the general form is named after its
group. Since a shortcut and the general form build equal steps, the name
follows the settings instead: `sq.scale(method="robust")` is named `robust`
too. Update §3.4's sentence in the spec in this task (plan's call, recorded
in the spec as "(spec's call)").

- [ ] **Step 1: Write the failing tests**

```python
def test_a_plain_list_names_its_steps():
    class Double(sq.Step):
        def apply(self, x, learned):
            return x * 2

    pipe = sq.Pipeline([Double("a"), Double("b"), LogisticRegression()])
    assert [n for n, _ in pipe.steps] == ["step-1", "step-2", "model"]


def test_pairs_and_plain_steps_mix():
    pipe = sq.Pipeline([("first", sq.Step("a")), sq.Step("b")])
    assert [n for n, _ in pipe.steps] == ["first", "step"]
```

- [ ] **Step 2: Run them to see them fail** — Expected: `TypeError` on a plain
      list.
- [ ] **Step 3: Implement** in `Pipeline.__init__`; remove `make_pipeline` and
      its tests, moving their numbering cases here.
- [ ] **Step 4: Run `just test`** — Expected: pass.
- [ ] **Step 5: Commit** — `feat: build pipelines from plain lists of steps`

---

### Task 4: A step from callables

**Files:**
- Modify: `src/sqlearn/_step.py`, `src/sqlearn/_store.py` (`_freeze`)
- Test: `tests/src/sqlearn/test__step.py`, `tests/src/sqlearn/test__store.py`

**Interfaces:**
- Produces:
  <!-- markdownlint-disable-next-line MD013 -->
  `Step.__init__(self, cols=None, keep=False, suffix=None, *, learn: Callable[[Expression], Mapping[str, Expression]] | None = None, apply: Callable[[Expression, Learned], Expression | Mapping[str, Expression]] | None = None)`.
  When given, they replace the methods of the same names for that instance;
  `settings()` includes them. `_freeze` keeps a function object itself (its
  identity) in the key, beside `module.qualname`, as Ruling R9 does for classes.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_step_from_callables_learns_and_applies(con):
    step = sq.Step(
        learn=lambda x: {"top": sq.agg.max(x)},
        apply=lambda x, learned: x / learned.top,
        cols=["a"],
    )
    out = sq.Pipeline([step]).learn("t").apply("t", out="numpy")
    assert out.max() == 1.0


def test_redefining_a_lambda_relearns(con):
    sq.Pipeline([sq.Step(apply=lambda x: x + 1, cols=["a"])]).learn("t")
    sq.Pipeline([sq.Step(apply=lambda x: x + 1, cols=["a"])]).learn("t")
    # two different function objects: two store entries
```

- [ ] **Step 2–4:** run (fail: unexpected keyword `apply`), implement, run
      `just test`.
- [ ] **Step 5: Commit** — `feat: let a step take learn and apply as callables`

---

### Task 5: Labels and the naming rule

**Files:**
- Create: `src/sqlearn/_names.py`
- Modify: `src/sqlearn/_step.py` (`output_names`), `src/sqlearn/_compose.py`
  (remove the clash refusal and the #26 link),
  `src/sqlearn/preprocessing/onehot.py`, `docs/guide/writing-a-step.md`
- Test: `tests/src/sqlearn/test__names.py`,
  `tests/src/sqlearn/test__compose.py`,
  `tests/src/sqlearn/preprocessing/test_onehot.py`

**Interfaces:**
- Produces:
  - **Contract change:** a mapping returned by `apply` is keyed by
    **labels**: the column `<column>_<label>` is created; the label `""`
    means the input column itself (replacing it). OneHot returns
    `{"Oslo": ..., "NULL": ...}`.
    <!-- markdownlint-disable-next-line MD013 -->
  - `sqlearn._names.name_columns(planned: Sequence[tuple[str, str]], taken: Sequence[str]) -> list[str]`:
    `planned` is `(column, label)` per output in order; returns the final names
    per ADR 0035: `<column>_<label>` (`<column>` for `""`), and among names
    equal without regard to case, including those in `taken` (the columns
    passing through), the first in sorted order of label keeps its name and the
    others get `_2`, `_3` in that order. A name in `taken` is never renamed.
  - `keep=True` with one expression: label `suffix or step name`.
  - Feature makers may return full names (Task 13) by setting the class
    attribute `names_are_labels: ClassVar[bool] = True` to False.

- [ ] **Step 1: Write the failing tests**

```python
def test_clashes_are_numbered_in_sorted_order():
    assert name_columns([("city", "oslo"), ("city", "Oslo"), ("city", "NULL")], []) == [
        "city_oslo_2", "city_Oslo", "city_NULL"]

def test_an_input_column_is_never_renamed():
    assert name_columns([("city", "Oslo")], ["city_oslo"]) == ["city_Oslo_2"]

def test_text_null_beside_a_real_null(con):
    # city holds the text 'NULL' and a real NULL: both have the label "NULL";
    # equal labels keep output order (learned categories first, the missing
    # category last) → city_NULL (the text), city_NULL_2 (the missing value)

def test_onehot_of_case_only_categories(con):
    # city: Oslo, oslo, NULL → columns_out_ == ["city_NULL", "city_Oslo", "city_oslo_2"]
```

- [ ] **Step 2–4:** run (fail), implement, run `just test`. Remove the core's
  OneHot refusal of `'NULL'` beside NULL and its test.
- [ ] **Step 5: Commit** — `feat: name created columns by one rule`

---

### Task 6: `sq.impute`

**Files:**
- Modify: `src/sqlearn/preprocessing/impute.py`,
  `src/sqlearn/preprocessing/__init__.py`, `src/sqlearn/__init__.py`,
  `validation/sqlearn/preprocessing/validate_impute.py`, every use of
  `sq.Impute` and `strategy=`
- Test: `tests/src/sqlearn/preprocessing/test_impute.py`

**Interfaces:**
- Consumes: `columns_arg`, `Group` (Task 1); `Aggregate`, `lookup` (Task 2);
  `default_name` (Task 3); labels (Task 5).
- Produces:
  - `class Impute(Step)`: settings `cols`, `value`, `indicator: bool`,
    `keep`, `suffix`. `value` is stored resolved: an `Aggregate`, a
    constant, None, or a dict of column to either. A string is resolved by
    `lookup`, else a constant; `sq.fn.const(...)` stays a constant.
  - `sq.impute`:
    <!-- markdownlint-disable-next-line MD013 -->
    `(*cols, value="median", indicator=False, cols=None, keep=False, suffix=None) -> Impute`
    and shortcuts `mean(*cols, **kw)`, `median(...)`, `mode(...)`,
    `constant(v, *cols, **kw)`, `indicator(*cols, **kw)`
    (`value=None, indicator=True`).
  - Default columns: `sq.cols.numeric()` when `value` is a `numeric_only`
    aggregate or a number; `sq.cols.string()` for a text constant; every
    column for `mode`.
  - `static` when `indicator` is False; dynamic with `creates = INTEGER`
    when True: the label `"missing"` is created only for columns with a
    missing value at `learn`; the filled column is label `""`.
  - `default_name()`: `mean`, `median`, `mode`, `constant`, `indicator`, else
    `impute`.

- [ ] **Step 1: Write the failing tests**

```python
def test_shortcut_equals_general_form():
    for a, b in [(sq.impute.median("age"), sq.impute("age", value="median")),
                 (sq.impute.constant(0, "s"), sq.impute("s", value=0)),
                 (sq.impute.indicator("age"), sq.impute("age", value=None, indicator=True))]:
        assert a.settings() == b.settings() and repr(a) == repr(b)

def test_impute_a_dict(con):
    step = sq.impute({"age": "median", "income": "mean", "city": "unknown"})
    # matches SimpleImputer per column; one stage; repr rebuilds it

def test_a_dict_naming_a_missing_column_is_refused(con):
    with pytest.raises(StepError, match="agee"):
        sq.Pipeline([sq.impute({"agee": "median"})]).learn("t")

def test_a_search_over_a_dict_step_is_refused(con): ...

def test_indicator_only_where_missing(con):
    # age has NULLs, income has none → columns_out_ adds age_missing only

def test_literal_text_constant():
    assert sq.impute("city", value=sq.fn.const("median")).value != sq.agg.median

def test_mode_on_text_and_constant_type_mismatch(con): ...
```

- [ ] **Step 2–4:** run (fail), implement, run `just test`. The validation
  runner adds `mode`, `constant` and `indicator` cases against
  `SimpleImputer` and `MissingIndicator`.
- [ ] **Step 5: Commit** — `feat: add sq.impute with values from sq.agg`

---

### Task 7: `sq.scale` (centre and spread)

**Files:**
- Modify: `src/sqlearn/preprocessing/scale.py`, `__init__.py` files,
  `validation/sqlearn/preprocessing/validate_scale.py`, every use of `sq.Scale`
- Test: `tests/src/sqlearn/preprocessing/test_scale.py`

**Interfaces:**
- Produces:
  - `class Scale(Step)`: settings `cols`, `method`, `center`, `spread`,
    `feature_range`, `keep`, `suffix`; `static = True`.
  - `sq.scale`:
    <!-- markdownlint-disable-next-line MD013 -->
    `(*cols, method="standard", center=<default>, spread=<default>, feature_range=<default>, norm="l2", cols=None, keep=False, suffix=None) -> Scale | Normalize`
    and shortcuts `standard`, `robust(quantile_range=(25.0, 75.0))`,
    `minmax(feature_range=(0, 1))`, `maxabs`, `normalize(norm="l2")` (Task 8).
  - Method defaults: standard `mean`/`std`; robust `median`/`iqr(q=...)`; minmax
    `min`/`range`, `feature_range=(0, 1)`; maxabs `None`/`maxabs`.
    `robust(quantile_range=(a, b))` stores
    `spread=sq.agg.iqr(q=(a/100, b/100))`.
  - Apply: `(x - center) / spread`, a spread of 0 or NULL treated as 1, then
    `* (b - a) + a` with `feature_range`; result DOUBLE; infinity refused
    (ADR 0030, `refuse_infinite`).
  - A dict maps column to method name (centre/spread methods only).
  - `repr` omits settings equal to the method's defaults; `default_name()`
    is the method.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    "shortcut,sklearn_scaler",
    [
        (sq.scale.standard, StandardScaler()),
        (sq.scale.robust, RobustScaler()),
        (sq.scale.minmax, MinMaxScaler()),
        (sq.scale.maxabs, MaxAbsScaler()),
    ],
)
def test_scalers_match_sklearn(con, shortcut, sklearn_scaler): ...


def test_shortcut_equals_general_form():
    assert sq.scale.robust("x").settings() == sq.scale("x", method="robust").settings()
    assert (
        repr(sq.scale.robust("x", quantile_range=(10, 90)))
        == "sq.scale.robust(cols='x', quantile_range=(10, 90))"
    )


def test_a_given_center_replaces_the_default():
    s = sq.scale.robust(center=sq.agg.mean)
    assert s.method == "robust" and s.center == sq.agg.mean


def test_scale_and_impute_integer_and_decimal_columns(con):
    ...
    # INTEGER, BIGINT, DECIMAL(10,2) columns through impute.median and
    # scale.robust equal scikit-learn's float64 output
```

- [ ] **Step 2–4:** run (fail), implement, run `just test`; the validation
  runner covers the four methods against scikit-learn and the formulae.
- [ ] **Step 5: Commit** —
      `feat: add sq.scale with centre and spread from sq.agg`

---

### Task 8: Whole-row steps and `scale.normalize`

**Files:**
- Modify: `src/sqlearn/_step.py`, `src/sqlearn/_plan.py`,
  `src/sqlearn/_compose.py`, `src/sqlearn/preprocessing/scale.py`,
  `docs/guide/writing-a-step.md`
- Test: `tests/src/sqlearn/test__plan.py`, `test__compose.py`,
  `tests/src/sqlearn/preprocessing/test_scale.py`

**Interfaces:**
- Produces:
  - `Step.rowwise: ClassVar[bool] = False`. A rowwise step defines
    <!-- markdownlint-disable-next-line MD013 -->
    `apply_row(self, xs: Mapping[str, Expression], learned: Mapping[str, Learned]) -> Mapping[str, Expression]`
    (input column name to expression; output name to expression, named by labels
    per Task 5 unless `names_are_labels` is False). `learn` stays per column.
    The selected inputs are replaced by the outputs.
  - Planner: every output of a rowwise step reads every selected input.
  - `class Normalize(Step)`: `rowwise = True`, `static = True`, settings
    `cols`, `norm` (`"l1"`, `"l2"`, `"max"`); a row whose norm is 0 stays
    zeros; a missing value in a selected column raises at fetch through
    `error()` with a message naming the column and saying to impute first
    (scikit-learn refuses NaN). `sq.scale.normalize` and
    `sq.scale(method="normalize")` build it; `center`, `spread` and
    `feature_range` with it are refused.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("norm", ["l1", "l2", "max"])
def test_normalize_matches_sklearn(con, norm): ...

def test_a_zero_row_stays_zero(con): ...

def test_a_rowwise_step_reads_every_input():
    # plan: a static step after a dynamic one that feeds one of normalize's
    # inputs makes normalize wait for that dynamic step
```

- [ ] **Step 2–4:** run (fail), implement, run `just test`.
- [ ] **Step 5: Commit** — `feat: add whole-row steps and scale.normalize`

---

### Task 9: `sq.encode` (onehot, ordinal)

**Files:**
- Modify: `src/sqlearn/preprocessing/onehot.py`, `ordinal.py`, `__init__.py`
  files, their validation runners, every use of `sq.OneHot`/`sq.Ordinal`
- Test: `test_onehot.py`, `test_ordinal.py`

**Interfaces:**
- Produces: `sq.encode`:
  `(*cols, method="onehot", cols=None, keep=False) -> OneHot | Ordinal | TargetEncoder`,
  shortcuts `onehot`, `ordinal`, (`target` in Task 10). `suffix=` removed from
  both classes (ADR 0035 rule 4); a dict refused. Default columns
  `sq.cols.string()`. `default_name()` is the method.

- [ ] **Step 1: Write the failing tests** — shortcut equals general form;
  `sq.encode.onehot(suffix="x")` raises `TypeError`; the core's OneHot and
  Ordinal tests pass under the new names.
- [ ] **Step 2–4:** run (fail), implement, run `just test`.
- [ ] **Step 5: Commit** — `feat: add sq.encode for onehot and ordinal`

---

### Task 10: Steps that learn from the target, and `encode.target`

**Files:**
- Create: `src/sqlearn/preprocessing/target.py`,
  `validation/sqlearn/preprocessing/validate_target.py`
- Modify: `src/sqlearn/_step.py`, `src/sqlearn/_plan.py`,
  `src/sqlearn/_compose.py`, `src/sqlearn/_pipeline.py`,
  `src/sqlearn/model_selection/search.py`, `docs/guide/writing-a-step.md`
- Test: `tests/src/sqlearn/preprocessing/test_target.py`, `test__pipeline.py`,
  `test__plan.py`, `tests/src/sqlearn/model_selection/test_search.py`

**Interfaces:**
- Produces:
  - `Step.uses_target: ClassVar[bool] = False`. Such a step's `learn` is
    `learn(self, x: Expression, y: Expression) -> Mapping[str, Expression]`.
  - Planner: a `uses_target` step ends its run (later readers wait, as for a
    dynamic step); its output names and types are known (`DOUBLE`, label
    `""`).
  - `Pipeline.learn(self, data, target: str | None = None)`: `target` is set
    aside as in `train`; a `uses_target` step without it raises
    `SqlearnError` saying to pass `target=`. `learn` then `apply` uses the
    values learned on all rows, no cross-fitting.
  - `train` (and every fold of a search): cross-fits. The inner fold of a
    row is `KFold(step.cv, step.seed).expression(...)` over the rows the step
    learns from. Values are learned once, grouped by inner fold and category,
    and derived in Python; the step's output for a training row is
    `CASE <inner fold> WHEN k THEN apply(x, learned_k) ... END`, built by the
    compositor from the step's ordinary `apply`. Later steps learn from that
    output. `predict` uses the values learned on all rows. The store entry
    holds `"all"` and `"0"` … `"k-1"`.
  - Grouped staged marker `__sqlearn_target_stats(x, y, fold)`: a `GROUP BY
    fold, x` stage returning, per inner fold and category, `count`, `sum(y)`,
    `sum(y*y)`; NULL is a category.
  - `class TargetEncoder(Step)`: settings `cols`, `smooth="auto"`, `cv=5`,
    `seed=0`, `target_type="auto"` (`binary`, `continuous`; a multiclass
    target is refused, saying it comes later). `sq.encode.target` and
    `sq.encode(method="target")` build it.
    <!-- markdownlint-disable-next-line MD013 -->
  - `TargetEncoder.encodings(self, stats: Sequence[tuple[int, object, int, float, float]], k: int) -> dict[str, dict[object, float]]`:
    for `"all"` and for each fold's complement, with `smooth="auto"`: overall
    mean `m` and variance `v` of y over the rows used; per category with count
    `n`, mean `μ` and variance `s²`: `λ = n·v / (n·v + s²)`, encoding
    `λ·μ + (1 − λ)·m`; with a number for `smooth`,
    `(n·μ + smooth·m) / (n + smooth)`. An unseen category at `apply`, and NULL
    when it was not seen, get `m`.

- [ ] **Step 1: Write the failing tests**

```python
def test_learn_then_apply_matches_fit_then_transform(con):
    # sq.Pipeline([sq.encode.target("plan")]).learn("t", target="y").apply(...)
    # equals TargetEncoder().fit(X, y).transform(X)

def test_train_cross_fits_like_fit_transform(con):
    # train's prepared rows equal TargetEncoder(cv=<sqlearn's inner splits>)
    # .fit_transform(X, y), row for row

def test_a_scaler_after_target_learns_from_cross_fitted_values(con): ...

def test_learn_without_target_is_refused(con): ...

def test_target_unseen_and_null_get_the_overall_mean(con): ...

def test_a_target_step_ends_its_run():
    # plan of [encode.target("plan"), scale.standard()]: two runs
```

- [ ] **Step 2–4:** run (fail), implement, run `just test`. The validation
  runner compares against `TargetEncoder` with sqlearn's folds as `cv`
  splits, binary and continuous targets.
- [ ] **Step 5: Commit** —
      `feat: add steps that learn from the target, and encode.target`

---

### Task 11: `sq.bin`

**Files:**
- Create: `src/sqlearn/preprocessing/bin.py`,
  `validation/sqlearn/preprocessing/validate_bin.py`
- Modify: `__init__.py` files
- Test: `tests/src/sqlearn/preprocessing/test_bin.py`

**Interfaces:**
- Produces:
  - `class Bin(Step)`: settings `cols`, `method` (`"uniform"`,
    `"quantile"`), `n=5`, `keep`, `suffix`; `static = True`; output INTEGER.
    Learns the edges as a list: uniform `min + i·(max − min)/n`, quantile
    `sq.agg.quantile(q=i/n, method="averaged_inverted_cdf")` for `i = 1 …
    n−1`. Equal edges are merged with a `SqlearnWarning`, as scikit-learn
    warns. Apply: the number of inner edges `≤ x`, clipped to
    `[0, bins − 1]` (scikit-learn's `searchsorted(side="right")`); NULL
    stays NULL.
  - `class Binarize(Step)`: settings `cols`, `threshold=0.0`; 1 where
    `x > threshold`, else 0, NULL stays NULL; learns nothing.
  - `sq.bin`: `(*cols, method="quantile", n=5, threshold=0.0, ...)`,
    shortcuts `uniform(n=5)`, `quantile(n=5)`, `binarize(threshold=0.0)`.

- [ ] **Step 1: Write the failing tests** — each against
  `KBinsDiscretizer(encode="ordinal", subsample=None)` and `Binarizer`;
  `test_bins_of_a_constant_column`; shortcut equals general form.
- [ ] **Step 2–4:** run (fail), implement, run `just test`.
- [ ] **Step 5: Commit** — `feat: add sq.bin`

---

### Task 12: `sq.transform`

**Files:**
- Create: `src/sqlearn/preprocessing/transform.py`,
  `validation/sqlearn/preprocessing/validate_transform.py`
- Modify: `src/sqlearn/fn.py` (any function the transforms need)
- Test: `tests/src/sqlearn/preprocessing/test_transform.py`

**Interfaces:**
- Produces: `class Transform(Step)`: settings `cols`, `method` (`log`, `log1p`,
  `sqrt`, `clip`, `lower`, `upper`), `lower=None`, `upper=None` (clip's bounds),
  `keep`, `suffix`; `static = True`; learns nothing.
  `sq.transform(*cols, method, ...)` (no default method: leaving it out is a
  `TypeError`) and shortcuts `log`, `log1p`, `sqrt`,
  `clip(lower=None, upper=None)`, `lower`, `upper`. Default columns: numeric,
  text for `lower`/`upper`. Bad input: `log` for `x <= 0`, `log1p` for
  `x <= -1`, `sqrt` for `x < 0` is
  `CASE WHEN <bad> THEN error(<message>) ELSE <f(x)> END`, the message naming
  `sq.transform.<method>`, the column and the fix (`clip` first, or `log1p`);
  NULL and NaN pass as numpy gives them.

- [ ] **Step 1: Write the failing tests** — each method against numpy;
  `test_log_of_zero_is_refused_with_the_fix` (`duckdb.InvalidInputException`
  whose text names the column and `log1p`); clip with one bound;
  `lower` on text.
- [ ] **Step 2–4:** run (fail), implement, run `just test`.
- [ ] **Step 5: Commit** — `feat: add sq.transform`

---

### Task 13: `sq.features`

**Files:**
- Create: `src/sqlearn/preprocessing/features.py`,
  `validation/sqlearn/preprocessing/validate_features.py`
- Test: `tests/src/sqlearn/preprocessing/test_features.py`

**Interfaces:**
- Produces:
  - `class Polynomial(Step)`: `rowwise = True`, `static = True`,
    `names_are_labels = False`; settings `cols`, `degree=2`,
    `interaction_only=False`, `include_bias=False`. Outputs in scikit-learn's
    `powers_` order, named `a`, `b`, `a^2`, `a*b`, `b^2` (scikit-learn's
    `get_feature_names_out` with `" "` written `*`); learns nothing.
  - `class Spline(Step)`: per column, `static = True`, `creates = DOUBLE`;
    settings `cols`, `n_knots=5`, `degree=3`, `knots="uniform"`
    (`"quantile"`), `extrapolation="constant"` (the only one). Learns `min`
    and `max` (uniform) or the knot quantiles
    (`sq.agg.quantile(q=..., method="linear")`); creates labels `sp_0` …
    `sp_{n_knots + degree − 2}`. The knot vector is extended by `degree`
    equal steps on each side, as scikit-learn's; the basis is written as one
    polynomial per knot interval (coefficients computed in pure Python by
    the Cox–de Boor recursion) in a `CASE` on the interval, Horner form;
    outside `[first knot, last knot]` the boundary values (constant
    extrapolation).
  - `sq.features(*cols, method, ...)` (no default method) and shortcuts
    `polynomial(degree=2, interaction_only=False, include_bias=False)`,
    `spline(n_knots=5, degree=3, knots="uniform")`.

The spec's §5.6 says each of these reads several inputs; `spline` works per
column (one input, several outputs), so only `polynomial` is rowwise. Fix
that sentence in the spec in this task.

- [ ] **Step 1: Write the failing tests** — against `PolynomialFeatures`
  (degrees 2 and 3, `interaction_only`) and `SplineTransformer` (uniform and
  quantile knots), `columns_out_` against `get_feature_names_out`;
  `test_spline_of_a_constant_column`; a value outside the training range.
- [ ] **Step 2–4:** run (fail), implement, run `just test`.
- [ ] **Step 5: Commit** — `feat: add sq.features`

---

### Task 14: The spec's script, end to end

**Files:**
- Create: `validation/pipelines/validate_preprocessing.py`,
  `tests/src/sqlearn/test_preprocessing_script.py`
- Modify: `validation/pipelines/validate_slice.py`,
  `tests/src/sqlearn/test_slice.py`, `examples/plot_slice.py`,
  `validation/__main__.py`

**Interfaces:**
- Consumes: every group (Tasks 1–13).

- [ ] **Step 1: Write the failing test** — §2's script on generated data
  (seed 0, 10,000 rows) gives the same `best_params_` and predictions as
  scikit-learn's `Pipeline` + `ColumnTransformer` + `GridSearchCV`, with
  scikit-learn handed sqlearn's outer folds (`GridSearchCV(cv=...)`) and
  inner folds (`TargetEncoder(cv=...)`); the core's slice, in the new names,
  still matches; a `slow` test runs §2's preparation under a memory limit
  smaller than the data (as `tests/test_environment.py`).
- [ ] **Step 2: Run it** — Expected: PASS if Tasks 1–13 are right; a
  failure here is a bug in one of them, fixed there.
- [ ] **Step 3: Write the validation runner** with the slice runner's shape.
- [ ] **Step 4: Run `just verify`** — Expected: pass.
- [ ] **Step 5: Commit** — `test: run the preprocessing script end to end`

---

### Task 15: Measure OneHot's second run (#22)

**Files:**
- Create: `docs/benchmarks/onehot-second-run.md`,
  `validation/benchmarks/onehot_runs.py`

- [ ] **Step 1:** Write the script: the core's slice preparation (impute,
  onehot, scale) on generated data at 1,000, 100,000 and 10,000,000 rows and
  once under a memory limit smaller than the data; record per size the wall
  time, the number of runs, and the bytes DuckDB reads (`EXPLAIN ANALYZE`'s
  totals), for the pipeline as it is and for the same preparation without
  OneHot (one run), five repetitions each, median reported.
- [ ] **Step 2:** Run it with
      `uv run python -m validation.benchmarks.onehot_runs`; write the table and
      the environment into the page.
- [ ] **Step 3: Commit** — `docs: measure the cost of OneHot's second run`

The decision on #22 is Tomas's; the page states the numbers only.

---

### Task 16: Documentation

**Files:**
- Create: `docs/guide/imputing.md`, `scaling.md`, `encoding.md`, `binning.md`,
  `transforming.md`, `making-features.md`, `column-names.md`,
  `from-scikit-learn.md`
- Modify: `docs/guide/index.md`, `docs/reference/index.md` (one autosummary
  section per group), `docs/guide/writing-a-step.md`,
  `docs/guide/inputs-and-the-store.md`, `docs/specs/library-preprocessing.md`
  (a "Built" line pointing to this plan and issue #30)

- [ ] **Step 1:** Write each family page: the group's general form, each
  shortcut with a runnable example (doctested), the scikit-learn
  counterpart, the edge cases.
- [ ] **Step 2:** `from-scikit-learn.md`: a table of every scikit-learn name
  covered (`SimpleImputer(strategy="median")` → `sq.impute.median()`,
  `RobustScaler()` → `sq.scale.robust()`, … `make_pipeline(...)` →
  `sq.Pipeline([...])`).
- [ ] **Step 3:** `column-names.md` explains ADR 0035 with the `Oslo`/`oslo`
  example and `columns_out_`.
- [ ] **Step 4: Run `just verify`** — Expected: pass, the docs build without
  warnings.
- [ ] **Step 5: Commit** — `docs: document the preprocessing groups`

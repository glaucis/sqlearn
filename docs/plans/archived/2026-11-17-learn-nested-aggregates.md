---
type: plan
tags: [aggregates, nested, compositor, median, std, learn]
summary: "Implementation plan for learning nested aggregates in levels (#49): a planner by level in the compositor, slice by slice (staged in staged, std in std, plain in staged, plain in plain, sharing and depth), then validation, reach, cost and docs."
related: [docs/specs/archived/learn-nested-aggregates.md, docs/adr/0051-aggregates-learn-in-levels.md]
---
# Learning nested aggregates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A step's `learn` may return any aggregate inside any other, at any
depth; sqlearn learns it in levels inside the run's one `WITH` query.

**Architecture:** `_learn_ctes` in `src/sqlearn/_compose.py` becomes a planner
by level. Each aggregate in a learned value's SQL text (a staged marker from
`_markers`, or a plain DuckDB aggregate from `_CALL` and `_aggregate_names`)
gets a height: 1 when its argument holds no aggregate, else one more than the
highest inside. Level `k` is today's machinery (one `_Staged` for its
quantiles, modes, statistics and std/var, plus one plain one-row select for
its plain aggregates) over the stage's input cross-joined with levels
`1 .. k-1`; an aggregate of height `< k` inside a level-`k` argument is
replaced by the plain column of its level's row. The learn stage's final
select reads the outermost results as today (`any_value` outside an
aggregate, plain inside). Every level is a `MATERIALIZED` CTE.

**Tech Stack:** Python 3.12, DuckDB 2.0 (SQL text and its relational API),
numpy and scipy (tests and validation only), pytest, `uv`, `just`.

**Spec:** `docs/specs/learn-nested-aggregates.md` (approved 2026-11-17); ADR
0051. Issue #49.

## Global Constraints

- One `WITH` query per run; nothing fetched to Python between levels.
- sqlearn's medians and quantiles at every level stay its sort
  (`_quantile_ctes`); never DuckDB's `median`, `quantile` or `mad` in what
  sqlearn builds.
- An inner NULL is fed to the outer aggregate as NULL; sqlearn wraps
  nothing (ADR 0046).
- No algebraic rewriting.
- Refusals left, house form (`StepError` naming step and position, a reason,
  `Fix:`): a marker `sq.agg` did not build; an aggregate inside a target
  statistic's arguments. No new refusal.
- A learned value with no nesting gives the same values (within ADR 0043's
  rounding) and the same number of passes as today.
- Tests named in `GLOSSARY.md` terms, through `sq.Pipeline(...).learn` or
  `step_stage` + `execute`; values against numpy.

## Review Focus

1. **A column or literal whose text looks like an aggregate** (a column
   named `"sum(x)"`, a string `'median('`) is not taken for one: the scanners
   skip quoted text. Test in Task 4.
2. **An aggregate with `FILTER (WHERE ...)` or `DISTINCT`** inside another
   (`sum(x - avg(x) FILTER (WHERE x > 0))`) keeps its clause in its level.
   Test in Task 4.
3. **A text column**: `mode(x)` of a VARCHAR beside a nested numeric value
   in the same step learns as today. Test in Task 5.
4. **The target encoder** (cross-fitted statistics) learns the same values
   and the same SQL shape as before. The existing target tests cover it; run
   them in Task 5 and assert the statistics stage count in one test.
5. **The learning store** reuses a nested value on a second learn of the
   same data (no new learn). Test in Task 5.

---

### Task 1: Levels, through the median absolute deviation

**Files:**
- Modify: `src/sqlearn/_compose.py` (`_learn_ctes`, `_Staged.reference`,
  new level planner beside them)
- Test: `tests/src/sqlearn/agg/test_aggregates.py`,
  `tests/src/sqlearn/test__compose.py`

**Interfaces:**
- Produces: `_levels(stage: Stage, learn: dict[str, Expression]) ->
  list[_Level]` (private), each `_Level` holding its `_Staged`, its plain
  aggregates `{column: sql}` and its CTE name; `_learn_ctes` keeps its
  signature and return type.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_median_absolute_deviation_is_learned():
    # _Learns(lambda x: sq.agg.median(sq.fn.abs(x - sq.agg.median(x))))
    # on [1.0, 2.0, 3.0, 4.0, 100.0] -> 1.0; on 1,000 normal values (seed 0)
    # == np.median(np.abs(v - np.median(v))) exactly

def test_a_median_of_a_median_is_learned():
    # replaces test_an_aggregate_of_an_aggregate_is_refused (test__compose):
    # Nested() learns the median of the column's median: equal to the median

def test_a_mode_of_an_expression_holding_a_median_is_learned():
    # sq.agg.mode(sq.fn.round(x - sq.agg.median(x))) == numpy/statistics' mode
```

- [ ] **Step 2: Run them; expect FAIL** with `StepError ... aggregate of an
  aggregate`.

- [ ] **Step 3: Implement the planner.** Peel heights bottom-up:

```text
for each learned value: find every aggregate (staged marker or plain call)
  and its span; height(a) = 1 + max(height(b) for b inside a's argument), 1
  if none
for k = 1 .. max height:
  level k computes every aggregate of height k (deduplicated by its text
  after inner replacements), over previous CROSS JOIN levels 1..k-1
  replace each in the texts above by its level's column reference
the learn select: the outermost texts, as today
```

  Delete `test_an_aggregate_of_an_aggregate_is_refused`; keep
  `test_a_marker_sq_agg_did_not_build_is_refused`.

- [ ] **Step 4: Run** `uv run pytest tests/src/sqlearn/agg
  tests/src/sqlearn/test__compose.py -q`, then `just test`. Expected: pass.

- [ ] **Step 5: Commit** `feat: a median of an expression holding a median
  is learned (#49)`.

### Task 2: A standard deviation inside another, and a quantile of one

**Files:** `src/sqlearn/_compose.py` (`_Staged._std`, the refusals in
`reference`); `tests/src/sqlearn/agg/test_aggregates.py`

- [ ] **Step 1: Failing tests** (replacing
  `test_a_std_the_stages_cannot_order_is_refused`):

```python
@pytest.mark.parametrize(("build", "numpy"), [
    (lambda x: sq.agg.std(x - sq.agg.std(x)), lambda v: np.std(v - np.std(v))),
    (lambda x: sq.agg.median(x / sq.agg.std(x)), lambda v: np.median(v / np.std(v))),
    (lambda x: sq.agg.var(sq.agg.std(x) * x), lambda v: np.var(np.std(v) * v)),
], ids=["std of std", "median of std", "var of std"])
def test_a_std_inside_another_aggregate_is_learned(build, numpy):
    # on [1.0, 2.0, 6.0] and 1,000 normal values: within 2 ULPs (ADR 0044)
```

- [ ] **Step 2: Run; expect FAIL** with `which cannot be staged`.
- [ ] **Step 3:** Remove both ordering refusals; a std/var of height `k`
  joins level `k`'s `_Staged.stds`.
- [ ] **Step 4: Run** the agg tests, then `just test`.
- [ ] **Step 5: Commit** `feat: a standard deviation inside another is
  learned (#49)`.

### Task 3: A plain aggregate inside a staged one

**Files:** `src/sqlearn/_compose.py` (`_refuse_plain_aggregate` removed;
plain inner aggregates lifted into their level's plain select);
`tests/src/sqlearn/agg/test_aggregates.py`

- [ ] **Step 1: Failing tests** (replacing
  `test_a_plain_aggregate_inside_a_staged_one_is_refused`,
  `test_the_advice_on_a_plain_aggregate_holds_for_a_median_too`,
  `test_var_of_an_expression_holding_a_plain_aggregate_is_refused`):

```python
@pytest.mark.parametrize(("build", "numpy"), [
    (lambda x: sq.agg.std(x - sq.agg.mean(x)), lambda v: np.std(v - np.mean(v))),
    (lambda x: sq.agg.var(x - sq.agg.mean(x)), lambda v: np.var(v - np.mean(v))),
    (lambda x: sq.agg.median(x - sq.agg.mean(x)), lambda v: np.median(v - np.mean(v))),
    (lambda x: sq.agg.mode(sq.fn.round(x - sq.agg.mean(x))), ...),
], ids=["std", "var", "median", "mode"])
def test_a_plain_aggregate_inside_a_staged_one_is_learned(build, numpy):
    # std/var within 2 ULPs, median exact, mode equal
```

- [ ] **Step 2: Run; expect FAIL** with `a plain aggregate inside a staged
  one`.
- [ ] **Step 3:** A plain aggregate of height `k` goes to level `k`'s plain
  one-row select (`SELECT <aggs> FROM previous CROSS JOIN <levels below>`);
  its text in the outer argument becomes the column of that row.
- [ ] **Step 4: Run** the agg tests, then `just test`.
- [ ] **Step 5: Commit** `feat: a plain aggregate inside a staged one is
  learned (#49)`.

### Task 4: A plain aggregate inside a plain one, and missing values

**Files:** `src/sqlearn/_compose.py`; `tests/src/sqlearn/agg/test_aggregates.py`

- [ ] **Step 1: Failing tests**

```python
def test_a_plain_aggregate_inside_a_plain_one_is_learned():
    # duckdb.FunctionExpression("sum", x - sq.agg.mean(x)) on [1, 2, 6.0]:
    # == np.sum(v - np.mean(v)) within 1e-12; no "Binder Error"

def test_an_inner_value_of_no_present_value_reaches_the_outer_as_null():
    # column all NULL: sq.agg.std(x - sq.agg.mean(x)) is None,
    # count(x - mean(x)) is 0, sum(x - NaN-producing inner) as DuckDB gives

def test_text_that_looks_like_an_aggregate_is_not_one():   # Review Focus 1
    # a column named "sum(a)" and a literal 'median(' inside a nested value

def test_an_inner_aggregate_keeps_its_filter():            # Review Focus 2
    # sum(x - avg(x) FILTER (WHERE x > 0)) == numpy with the filter

def test_duckdbs_own_median_written_by_a_user_is_learned_as_written():
    # FunctionExpression("median", abs(x - FunctionExpression("median", x)))
    # == numpy's MAD; the learn SQL holds DuckDB's median, not a sort
```

- [ ] **Step 2: Run; expect FAIL** (`Binder Error`, and the others).
- [ ] **Step 3:** A plain aggregate's height counts plain aggregates inside
  its argument (`_in_aggregates` spans), so `sum(x - avg(x))` has height 2.
  Its `FILTER` and `DISTINCT` belong to its call's text.
- [ ] **Step 4: Run**, then `just test`.
- [ ] **Step 5: Commit** `feat: a plain aggregate inside a plain one is
  learned (#49)`.

### Task 5: Sharing a level, depth, and what must not change

**Files:** `tests/src/sqlearn/agg/test_aggregates.py`,
`tests/src/sqlearn/test__compose.py`; code only if a test fails.

- [ ] **Step 1: Tests**

```python
def test_two_columns_share_each_level():
    # step_stage over columns a and b learning the MAD: the learn SQL has
    # exactly two quantile sorts (row_number() count == 2), one per level

def test_three_levels_deep_are_learned():
    # median(abs(x - median(abs(x - median(x))))) == numpy's

def test_a_value_without_nesting_keeps_its_passes():
    # Spread (two IQRs, two medians): still one row_number(); std alone:
    # still one _std_means pair

def test_a_nested_value_beside_a_text_mode():              # Review Focus 3
def test_a_nested_value_is_reused_from_the_store():        # Review Focus 5
    # STORE.learns unchanged on a second learn of the same frame

def test_an_aggregate_inside_a_target_statistic_is_refused():
    # house form, naming the step
```

  Run `uv run pytest tests/src/sqlearn/preprocessing/test_target.py -q`
  (Review Focus 4) and assert in one test that the target encoder's learn
  SQL has one `_stats` stage.
- [ ] **Step 2: Run.** Any test passing at once is recorded as such (it pins
  behaviour Tasks 1-4 built); a failing one gets its fix here.
- [ ] **Step 3: Commit** `test: levels are shared, deep and leave the rest
  alone (#49)`.

### Task 6: Validation, reach, cost and docs

**Files:**
- Modify: `validation/sqlearn/agg/validate_aggregates.py` (a MAD case
  against `scipy.stats.median_abs_deviation(scale=1.0)` and numpy, bound 1
  ULP as the median's)
- Modify: `docs/benchmarks/median-reach.md` (the MAD's reach under 32, 64
  and 128 MB on one thread, measured as the median's; `uptime` before and
  after; one probe per subprocess)
- Modify: ADR 0051 (measured cost per level on 20,000,000 rows from
  Parquet, as ADR 0044 measured std; the reach; Status accepted); ADR 0036
  and 0044 (a line under each amendment: superseded by 0051)
- Modify: `docs/guide/writing-a-step.md` (a nested example: the MAD)
- Modify: `HANDOFF.md`

- [ ] **Step 1:** The validation case; `just validate`. Expected: pass.
- [ ] **Step 2:** The reach and cost measurements. If the MAD's reach is
  below half the median's at a limit, or a level costs more than about twice
  the level below, stop and report to Tomas (spec §7).
- [ ] **Step 3:** The docs; `rm -rf docs/reference/generated docs/_build &&
  just build-docs`.
- [ ] **Step 4:** `just fmt`, `just verify`; name every failure.
- [ ] **Step 5: Commit** `docs: nested aggregates validated, measured and
  documented (#49)`.

---
type: task
tags: [model-selection, search, folds, hand-over, feed, stream, optuna, metrics, library-breadth, validation]
summary: "Implementation plan for the model-selection area of sqlearn's library breadth: grouped search names, fold schemes, prepared folds in tables, streamed prediction, the hand-over forms and streaming, the memory budget, kept preparations, random and Optuna search, and the metrics a search needs, in 15 tasks."
related: [docs/specs/library-model-selection.md, docs/specs/library-core.md, docs/adr/0022-one-search-with-pluggable-methods.md, docs/adr/0023-lazy-results-out-and-feed.md, docs/adr/0034-a-grouped-api.md]
---
# Library Breadth: Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hand prepared data to any model in the form the user picks
(numpy, pandas, Polars, Arrow, or a stream through `partial_fit`) without
ever swapping, and make the search usable for real tuning: grouped names,
fold schemes, random and Optuna methods, kept preparations, and the metrics a
search needs, so that the script in spec §2 runs.

**Architecture:** A search prepares each (preparation, fold) once into a
DuckDB table; training rows are fetched from it in the model's form, and
held-out rows are always streamed batch by batch into `predict`, the
predictions inserted back into DuckDB by row number. Fold schemes are objects
that number rows in SQL and give a training and a held-out predicate per
fold. One module, `_feed.py`, owns every hand-over: the forms, the stream
through `partial_fit`, the size check against the memory budget, and
streamed prediction. Kept preparations are the same fold tables written to a
DuckDB file under a key that survives a restart.

**Tech Stack:** Python 3.12+, duckdb 2.0 (the one runtime dependency;
`to_arrow_reader(batch_size=...)`, `to_arrow_table()`, `df()`, `pl()`); tests
and validation: pytest, scikit-learn 1.9.1, numpy, pandas, and new test-only
dependencies pyarrow, polars, catboost, lightgbm, optuna (ADR 0005 leaves tools
free).

**Spec:**
[`docs/specs/library-model-selection.md`](../specs/library-model-selection.md).
"§N" below is a section of it; "core §N" is
[`library-core.md`](../specs/library-core.md); "ADR N" is `docs/adr/00NN-*.md`.
Read the spec, ADRs 0014, 0022, 0023 and 0034, and
`src/sqlearn/model_selection/search.py` before starting.

## Global Constraints

- Work on the branch `library-model-selection` in the worktree
  `.claude/worktrees/library-model-selection`
  (`superpowers:using-git-worktrees`). Merge only on Tomas's word.
- Runtime dependency: `duckdb>=2.0.0` only. `src/` imports numpy, pandas,
  polars, pyarrow and optuna only inside the function that needs them, and
  each missing one is a `SqlearnError` naming `uv add <name>`, as `_numpy()`
  in `_model.py` does today.
- uv only (`uv run`); every task through `just`. Before every commit:
  `just fmt`, `just check`, `just test`, each checked by its own exit code
  (never piped through `tail` before `&&`). Never `--no-verify`.
  Conventional commits, scopes only `hooks`, `site`, `deps`; no AI
  attribution anywhere.
- Every module `src/sqlearn/X/Y.py` has `tests/src/sqlearn/X/test_Y.py`;
  every public module under `metrics/` has
  `validation/sqlearn/metrics/validate_Y.py`, listed in
  `validation/__main__.py`'s `RUNNERS` (`just check-mirror`).
- British English in prose and docstrings, American spelling in identifiers.
  Public objects have numpydoc docstrings with an example
  (`just check-docstrings`).
- SQL is built from DuckDB expression objects; SQL text is written only by
  the compositor and the fold schemes' `expression` methods, every identifier
  through `quote()` (ADR 0015).
- Messages for a user's mistake follow ADR 0019: what went wrong, why, the
  fix.
- Old public names are removed, not aliased (§8). Each task that moves a name
  updates every use of it in `src/`, `tests/`, `validation/`, `examples/` and
  `docs/` in the same commit.
- Wall-clock tests warm up first and set their limit between the normal time
  under load and the regression's (HANDOFF trap, 2026-11-07).
- Defaults from the spec, verbatim: `feed="numpy"`; stream batches of about
  100 MB (`megabytes=100`); `epochs=1`, `shuffle=True`, `seed=0`; memory
  budget 80% of physical memory, DuckDB's `memory_limit` on sqlearn's own
  connection half of it; `sq.search.random(trials=50, seed=0)`;
  `sq.search.optuna(trials=100, sampler=None, seed=0)`;
  `sq.folds.kfold(n=5, seed=0)`, `stratified(n=5, seed=0)`,
  `group(by, n=5, seed=0)`, `time(by, n=5, gap=0)`,
  `holdout(test=0.2, seed=0)`.

## Review Focus

Inputs the spec implies but no task's main tests exercise, most likely first;
each has its test in the task named.

1. **A NULL in a text column handed over as pandas, Polars or Arrow:** it
   arrives as a missing value (`None`/null), never the text `"NULL"`: Task 7
   `test_null_text_arrives_missing_in_every_form`.
2. **Text class labels predicted in several batches:** a classifier
   predicting `"yes"`/`"no"` over three batches gives a VARCHAR `prediction`
   column in the input's row order: Task 6
   `test_text_predictions_keep_order_across_batches`.
3. **A last batch smaller than the rest, and a fold smaller than one batch:**
   `partial_fit` is never called with zero rows, and the row count it sees
   sums to the fold's: Task 8 `test_stream_never_passes_an_empty_batch`.
4. **A held-out fold with one class under `roc_auc`:** refused with a message
   naming the fold and the fix (fewer folds or `stratified`), not a NaN
   score: Task 14 `test_roc_auc_on_a_one_class_fold_is_refused`.
5. **A data file changed between two sessions under `keep_prepared`:** a new
   modification time gives a new table; the old one is not reused: Task 10
   `test_a_changed_file_is_prepared_again`.

---

### Task 1: The search's names as groups

**Files:**
- Create: `src/sqlearn/model_selection/groups.py`,
  `docs/adr/0039-the-search-names-as-groups.md`
- Modify: `src/sqlearn/__init__.py`, `src/sqlearn/model_selection/__init__.py`,
  `docs/adr/index.md`, every use of `sq.Search`, `sq.Grid`, `sq.KFold`,
  `sq.range`
- Test: `tests/src/sqlearn/model_selection/test_groups.py`,
  `tests/src/sqlearn/test_init.py`

**Interfaces:**
- Consumes: `sqlearn._group.Group` (the base the step groups use).
- Produces:
  - `sq.search`: a `SearchGroup` instance; `sq.search(pipe, params=None,
    metric=accuracy, method=None, folds=None) -> Search` (the existing class,
    unchanged); attributes `grid() -> Grid`, `range(low, high, log=False) ->
    Range`. Task 11 adds `random`, Task 12 `optuna`.
  - `sq.folds`: a `FoldsGroup` instance; `kfold(n=5, seed=0) -> KFold`.
    Tasks 3 and 4 add the other schemes.
  - The top level loses `Search`, `Grid`, `KFold`, `range`; `Model` stays.

- [ ] **Step 1: Write the failing tests**

```python
def test_search_is_a_callable_group():
    pipe = sq.Pipeline([("model", LogisticRegression())])
    search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    assert isinstance(search, Search)
    assert repr(sq.search) == "sq.search"
    assert sq.search.grid().knows_all
    assert sq.search.range(0.01, 10, log=True) == Range(0.01, 10, True)


def test_folds_group_builds_kfold():
    assert sq.folds.kfold(3, seed=1) == KFold(3, seed=1)
    assert "kfold" in dir(sq.folds)
```

In `test_init.py`, the exact top-level list loses `Search`, `Grid`, `KFold`,
`range` and gains `search`, `folds`.

- [ ] **Step 2: Run them to see them fail**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run pytest tests/src/sqlearn/model_selection/test_groups.py tests/src/sqlearn/test_init.py -q`
Expected: FAIL (`ModuleNotFoundError: sqlearn.model_selection.groups`).

- [ ] **Step 3: Implement**

Both groups subclass `Group` as `sq.impute`'s does, so `help()`, tab
completion and the type checker see the shortcuts. Update every use
(`sq.Search(` → `sq.search(`, `sq.Grid()` → `sq.search.grid()`,
`sq.KFold(` → `sq.folds.kfold(`, `sq.range(` → `sq.search.range(`) including
`KFold`'s and `range`'s own messages and reprs that print `sq.range`. Write
ADR 0039 (the table of spec §8, `sq.Model` staying at the top level per
ruling F5) and list it in `docs/adr/index.md` under "Models and search".

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: group the search's names under sq.search and sq.folds` (body:
      `Refs #33`).

---

### Task 2: Fold schemes as an interface

**Files:**
- Modify: `src/sqlearn/model_selection/folds.py`, `src/sqlearn/_store.py`
  (`FoldKey`), `src/sqlearn/model_selection/search.py` (`_evaluate`),
  `src/sqlearn/_pipeline.py` (`_prepare_fold`'s `fold` argument)
- Create: `docs/adr/0040-fold-schemes-as-sql-over-rows.md`
- Test: `tests/src/sqlearn/model_selection/test_folds.py`,
  `tests/src/sqlearn/model_selection/test_search.py`

**Interfaces:**
- Produces, in `folds.py`:
  - `class Folds(Protocol)`: `splits: int` (how many folds are scored);
    `key: tuple[object, ...]` (settings, stable across processes, e.g.
    `("kfold", 5, 0)`); `numbered(rel, name: str, target: str | None) ->
    DuckDBPyRelation` (every row, plus `name` and any helper columns whose
    names start with `name`); `training(name: str, k: int) -> Expression`
    and `held(name: str, k: int) -> Expression` (predicates over the
    numbered relation).
  - `KFold` implements it: `splits == n`, `key == ("kfold", n, seed)`,
    `training` is `name != k`, `held` is `name == k`.
  - `_store.FoldKey = tuple[tuple[object, ...], int]` (scheme key, fold).
- `Search(folds=...)` accepts any `Folds`; `_evaluate` loops
  `range(folds.splits)` and filters with the scheme's predicates.

- [ ] **Step 1: Write the failing tests**

```python
def test_kfold_implements_the_scheme_interface(con):
    rel = con.sql("SELECT * FROM range(20) t(i)")
    folds = sq.folds.kfold(4, seed=0)
    assert isinstance(folds, Folds) and folds.splits == 4
    assert folds.key == ("kfold", 4, 0)
    numbered = folds.numbered(rel, "f", None)
    held = [
        numbered.filter(folds.held("f", k)).count("*").fetchone()[0] for k in range(4)
    ]
    train = [
        numbered.filter(folds.training("f", k)).count("*").fetchone()[0]
        for k in range(4)
    ]
    assert sum(held) == 20 and all(h + t == 20 for h, t in zip(held, train))


def test_a_search_takes_any_scheme():
    class Halves:  # a user's own scheme: even rows, odd rows
        splits = 2
        key = ("halves",)

        def numbered(self, rel, name, target):
            return rel.project("*, (row_number() OVER () % 2) AS " + name)

        def training(self, name, k):
            return duckdb.ColumnExpression(name) != duckdb.ConstantExpression(k)

        def held(self, name, k):
            return duckdb.ColumnExpression(name) == duckdb.ConstantExpression(k)

    search = sq.search(PIPE, params={"model__C": [1.0]}, folds=Halves())
    search.train(DATA, target="y")
    assert search.results_.count("*").fetchone()[0] == 2
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection -q`
Expected: FAIL (`ImportError: cannot import name 'Folds'`).

- [ ] **Step 3: Implement**

`_evaluate` keeps its shape (fold first, one preparation per group) but
filters `training` and `held` through the scheme; the fold key passed to
`_prepare_fold` and the store becomes `(folds.key, k)`. `_check_folds` asks
each `held` predicate for at least one row. `used_["folds"]` prints the
scheme's repr. Write ADR 0040 (spec §6: schemes as SQL over rows, the
interface above, value-dealt folds keep identical rows together, ADR 0038's
row-position folds stay inside the target encoder), indexed under "Models and
search".

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: let a search take any fold scheme` (body:
      `Refs #33`).

---

### Task 3: Stratified, grouped and hold-out folds

**Files:**
- Modify: `src/sqlearn/model_selection/folds.py`,
  `src/sqlearn/model_selection/groups.py`
- Test: `tests/src/sqlearn/model_selection/test_folds.py`

**Interfaces:**
- Consumes: `Folds` (Task 2).
- Produces: `sq.folds.stratified(n=5, seed=0) -> Stratified`,
  `sq.folds.group(by: str, n=5, seed=0) -> Grouped`,
  `sq.folds.holdout(test=0.2, seed=0) -> Holdout`, each a `Folds`;
  keys `("stratified", n, seed)`, `("group", by, n, seed)`,
  `("holdout", test, seed)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_stratified_balances_each_class(con):
    rel = con.sql(
        "SELECT i, (i % 10 = 0)::INT AS y FROM range(1000) t(i)"
    )  # 10% positive
    folds = sq.folds.stratified(5, seed=0)
    numbered = folds.numbered(rel, "f", "y")
    per_fold = numbered.aggregate("f, sum(y) AS pos, count(*) AS n", "f").fetchall()
    assert sorted(r[1] for r in per_fold) == [20] * 5
    assert sorted(r[2] for r in per_fold) == [200] * 5


def test_group_keeps_every_group_in_one_fold(con):
    rel = con.sql("SELECT i, i // 7 AS customer FROM range(700) t(i)")
    numbered = sq.folds.group("customer", 5, seed=0).numbered(rel, "f", None)
    spread = numbered.aggregate("customer, count(DISTINCT f) AS k", "customer")
    assert spread.filter("k > 1").count("*").fetchone()[0] == 0


def test_holdout_is_one_split_of_about_the_share(con):
    rel = con.sql("SELECT * FROM range(10000) t(i)")
    folds = sq.folds.holdout(test=0.2, seed=0)
    held = (
        folds.numbered(rel, "f", None)
        .filter(folds.held("f", 0))
        .count("*")
        .fetchone()[0]
    )
    assert folds.splits == 1 and 1900 < held < 2100
```

Plus: `stratified` without a target raises `SqlearnError` naming `target=`;
`group` naming a missing column raises naming the columns there;
`holdout(test=0)` and `test=1` are refused; each scheme's repr is
`sq.folds.<name>(...)`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection/test_folds.py -q`
Expected: FAIL (`AttributeError: ... has no attribute 'stratified'`).

- [ ] **Step 3: Implement**

`stratified`: within each class, order rows by `hash(row, seed)` and deal
`(row_number() OVER (PARTITION BY target ORDER BY hash) - 1) % n`, which is
how scikit-learn's `StratifiedKFold` spreads each class. `group`:
`hash(by, seed) % n`. `holdout`: held when
`hash(row, seed) / 2^64 < test`, `training` the rest, `splits == 1`. The
search passes its target to `numbered`.

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: add stratified, grouped and hold-out folds`
      (body: `Refs #33`).

---

### Task 4: Time-ordered folds

**Files:**
- Modify: `src/sqlearn/model_selection/folds.py`,
  `src/sqlearn/model_selection/groups.py`
- Test: `tests/src/sqlearn/model_selection/test_folds.py`

**Interfaces:**
- Produces: `sq.folds.time(by: str, n=5, gap=0) -> TimeSplit`, a `Folds`
  with `splits == n`, key `("time", by, n, gap)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_time_matches_time_series_split_without_ties(con):
    rel = con.sql("SELECT i AS t FROM range(103) r(i) ORDER BY hash(i)")  # shuffled
    folds = sq.folds.time("t", 4, gap=2)
    numbered = folds.numbered(rel, "f", None)
    for k, (train, test) in enumerate(TimeSeriesSplit(4, gap=2).split(range(103))):
        got_train = sorted(
            r[0]
            for r in numbered.filter(folds.training("f", k)).project("t").fetchall()
        )
        got_test = sorted(
            r[0] for r in numbered.filter(folds.held("f", k)).project("t").fetchall()
        )
        assert got_train == list(train) and got_test == list(test)


def test_time_keeps_a_tie_on_one_side(con):
    rel = con.sql("SELECT i // 10 AS day FROM range(100) r(i)")  # 10 rows per day
    folds = sq.folds.time("day", 3)
    numbered = folds.numbered(rel, "f", None)
    for k in range(3):
        train_days = {
            r[0]
            for r in numbered.filter(folds.training("f", k)).project("day").fetchall()
        }
        test_days = {
            r[0] for r in numbered.filter(folds.held("f", k)).project("day").fetchall()
        }
        assert not train_days & test_days
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection/test_folds.py -k time -q`
Expected: FAIL (`AttributeError: ... has no attribute 'time'`).

- [ ] **Step 3: Implement**

Per spec §6: rows ordered by `by`, positions `p` from 0; each row takes the
position of the last row of its tie (`max(p) OVER (PARTITION BY by)`), so a
boundary moves to the end of its tie. With `m` rows and
`size = m // (n + 1)`, fold k holds out positions
`[m - (n - k) * size, m - (n - k - 1) * size)` and trains on positions below
`m - (n - k) * size - gap`, as `TimeSeriesSplit` does. The helper columns
(position, tie position) are named with the `name` prefix (Task 2's
interface). A `by` that is NULL in any row is refused, naming the column.

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: add time-ordered folds` (body: `Refs #33`).

---

### Task 5: Each fold's prepared rows in a table

**Files:**
- Modify: `src/sqlearn/_pipeline.py` (`_prepare_fold`),
  `src/sqlearn/model_selection/search.py` (`_evaluate`, `train`)
- Test: `tests/src/sqlearn/model_selection/test_search.py`

**Interfaces:**
- Produces:
  - `Pipeline._prepare_fold(...) -> str`: instead of fetching, it writes the
    fold's prepared rows (features, `TARGET`, the fold columns, a row number
    `__sqlearn_row`) to a temporary DuckDB table and returns its name.
  - `Search._fold_tables: dict[tuple[str, FoldKey], str]` for one `train`
    call, keyed by (preparation, fold): a setting picked again (Optuna, a
    repeated preparation) reads the table, `transforms_` unchanged. Every
    table is dropped when `train` returns or raises.
  - Training rows are fetched from the table with the scheme's `training`
    predicate; held-out rows with `held`. Never the whole fold at once.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_setting_picked_twice_is_prepared_once():
    class Twice:  # asks the same setting twice, one at a time
        knows_all = False

        def start(self, space, *, maximize):
            self.left = [{"model__C": 1.0}] * 2

        def ask(self):
            return self.left.pop() if self.left else None

        def tell(self, params, score):
            pass

    search = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        method=Twice(),
        folds=sq.folds.kfold(3),
    )
    search.train(DATA, target="y")
    assert search.transforms_ == 3  # three folds, once each


def test_fold_tables_are_dropped_after_train():
    search = sq.search(
        PIPE_WITH_SCALE, params={"model__C": [1.0]}, folds=sq.folds.kfold(2)
    )
    search.train(DATA, target="y")
    temp = (
        connection()
        .sql("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        .fetchone()[0]
    )
    assert temp == 0
```

`Twice.start` takes `maximize`: add the keyword to `Method.start` and
`Grid.start` here (Task 12 uses it); the search passes
`maximize=self.metric.greater_is_better`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection/test_search.py -q`
Expected: FAIL (`transforms_ == 6`; `start() got an unexpected keyword
argument 'maximize'`).

- [ ] **Step 3: Implement**

Table names come from a counter (`__sqlearn_fold_<n>`), created with
`CREATE TEMP TABLE ... AS <the fold's prepared SQL>` so DuckDB spills it as
needed. Scores are unchanged: the existing search tests pass as they are.

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: keep each fold's prepared rows in a table for the search` (body:
      `Refs #33`).

---

### Task 6: Streamed prediction

**Files:**
- Create: `src/sqlearn/_feed.py`
- Modify: `src/sqlearn/_model.py` (`received`, `take`, `hand_over` move
  into `_feed.py`), `src/sqlearn/_pipeline.py` (`predict`),
  `src/sqlearn/model_selection/search.py` (fold scoring, `predict`)
- Test: `tests/src/sqlearn/test__feed.py` (the moved tests of
  `test__model.py` with them)

**Interfaces:**
- Produces, in `_feed.py`:
  - `BATCH_ROWS = 65_536`: the batch size of streamed prediction (spec's
    "always streamed"; the builder may tune it, Task 9 measures memory).
  - `predict_streamed(con, rel: DuckDBPyRelation, columns: Sequence[str],
    row: str, model: Model, *, method: str = "predict") -> DuckDBPyRelation`:
    reads `rel` with `to_arrow_reader(batch_size=BATCH_ROWS)`, hands each
    batch's `columns` to `getattr(model.estimator, method)` in the model's
    form (numpy until Task 7), and inserts each batch's results beside its
    `row` numbers into a temporary table; returns the relation sorted by
    `row`, one column `prediction` (or, for `method="predict_proba"`, one
    column per class, `__sqlearn_proba_0`, `__sqlearn_proba_1`, ...).
  - `take`, `hand_over`, `received` keep their signatures, now in
    `_feed.py`.
- `Pipeline.predict`, a search's scoring of each held-out fold, and
  `search.predict` all call `predict_streamed`.

- [ ] **Step 1: Write the failing tests**

```python
def test_predictions_come_in_batches_in_row_order(con, monkeypatch):
    monkeypatch.setattr(_feed, "BATCH_ROWS", 3)
    seen = []

    class Echo:
        def fit(self, x, y):
            return self

        def predict(self, x):
            seen.append(len(x))
            return x[:, 0] * 10

    rel = con.sql(
        "SELECT i::DOUBLE AS a, i + 1 AS r FROM range(8) t(i) ORDER BY hash(i)"
    )
    out = predict_streamed(con, rel, ["a"], "r", Model(Echo()))
    assert seen == [3, 3, 2]
    assert [v for (v,) in out.fetchall()] == [i * 10.0 for i in range(8)]


def test_text_predictions_keep_order_across_batches(con, monkeypatch):
    monkeypatch.setattr(_feed, "BATCH_ROWS", 2)

    class Words:
        def fit(self, x, y):
            return self

        def predict(self, x):
            return np.where(x[:, 0] > 2, "yes", "no")

    rel = con.sql("SELECT i::DOUBLE AS a, i + 1 AS r FROM range(6) t(i)")
    out = predict_streamed(con, rel, ["a"], "r", Model(Words()))
    assert str(out.types[0]) == "VARCHAR"
    assert [v for (v,) in out.fetchall()] == ["no", "no", "no", "yes", "yes", "yes"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/test__feed.py -q`
Expected: FAIL (`ModuleNotFoundError: sqlearn._feed`).

- [ ] **Step 3: Implement**

Streaming needs pyarrow: when it is missing, `predict_streamed` falls back to
one fetch with `fetchnumpy` and the search's results are the same (pyarrow
stays optional; the never-swap check of Task 9 covers that path). The
temporary predictions table is dropped with the relation, as `received`'s
registration is today.

- [ ] **Step 4: Run `just test`** — Expected: all pass; the core's predict
      and search tests unchanged.
- [ ] **Step 5: Commit** —
      `feat: stream every prediction through the model in batches` (body:
      `Refs #33`).

---

### Task 7: The hand-over forms

**Files:**
- Create: `docs/adr/0041-the-hand-over.md`
- Modify: `src/sqlearn/_feed.py`, `src/sqlearn/_model.py` (`Model`,
  `FEEDS`, `check_feed`), `src/sqlearn/_pipeline.py` (`_train`),
  `src/sqlearn/model_selection/search.py`, `pyproject.toml` (test group:
  `pyarrow`, `polars`, `catboost`, `lightgbm`)
- Test: `tests/src/sqlearn/test__feed.py`, `tests/src/sqlearn/test__model.py`

**Interfaces:**
- Produces:
  - `FEEDS = ("numpy", "pandas", "polars", "arrow", "stream")`.
  - `Model(estimator, feed="numpy", *, rows=None, megabytes=None, epochs=1,
    shuffle=True, seed=0)`: `rows`, `megabytes`, `epochs`, `shuffle`, `seed`
    are accepted only with `feed="stream"` (Task 8 uses them), else refused
    naming the setting; `__repr__` shows only what differs from the
    defaults.
  - `fetch(rel, feed: str, columns: Sequence[str], target: str | None) ->
    tuple[object, object | None]` in `_feed.py`: the features and the target
    in the form `feed` names: numpy (today's matrix and array), pandas
    (`DataFrame`, `Series`), polars (`DataFrame`, `Series`), arrow
    (`pyarrow.Table`, `pyarrow.ChunkedArray`). Text columns arrive as
    categories; they are refused only
    for numpy and stream.
- `_train`, the search's fold training and `predict_streamed` hand over
  through `fetch` in the model's form.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    "feed, kind",
    [("pandas", pd.DataFrame), ("polars", pl.DataFrame), ("arrow", pa.Table)],
)
def test_each_form_reaches_fit(feed, kind):
    seen = {}

    class Keep:
        def fit(self, x, y):
            seen["x"] = x
            return self

        def predict(self, x):
            return np.zeros(len(x))

    pipe = sq.Pipeline([sq.scale.standard(), sq.Model(Keep(), feed=feed)])
    pipe.train(DATA_WITH_CITY, target="y")
    assert isinstance(seen["x"], kind) and "city" in list(
        seen["x"].columns if feed != "arrow" else seen["x"].column_names
    )


def test_null_text_arrives_missing_in_every_form(con):
    rel = con.sql("SELECT * FROM (VALUES ('Oslo'), (NULL)) t(city)")
    assert fetch(rel, "pandas", ["city"], None)[0]["city"].isna().tolist() == [
        False,
        True,
    ]
    assert fetch(rel, "polars", ["city"], None)[0]["city"].is_null().to_list() == [
        False,
        True,
    ]
    assert fetch(rel, "arrow", ["city"], None)[0]["city"].null_count == 1
    assert str(fetch(rel, "pandas", ["city"], None)[0]["city"].dtype) == "category"


def test_lightgbm_takes_text_columns_through_pandas():
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.Model(LGBMClassifier(n_estimators=5, verbose=-1), feed="pandas"),
        ]
    )
    pipe.train(DATA_WITH_CITY, target="y")
    assert len(pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"]) == len(
        DATA_WITH_CITY
    )


def test_catboost_takes_text_columns_through_pandas():
    model = CatBoostClassifier(iterations=5, verbose=0, cat_features=["city"])
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(model, feed="pandas")])
    pipe.train(DATA_WITH_CITY, target="y")
    assert pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"].shape == (
        len(DATA_WITH_CITY),
    )


def test_one_model_gives_the_same_predictions_through_every_form():
    got = {}
    for feed in ("numpy", "pandas", "polars", "arrow"):
        pipe = sq.Pipeline(
            [sq.scale.standard(), sq.Model(LogisticRegression(), feed=feed)]
        )
        got[feed] = pipe.train(NUMERIC_DATA, target="y").predict(
            NUMERIC_DATA, out="numpy"
        )["prediction"]
    for feed in ("pandas", "polars", "arrow"):
        np.testing.assert_array_equal(got[feed], got["numpy"])


def test_settings_of_the_stream_need_the_stream():
    with pytest.raises(SqlearnError, match="rows="):
        sq.Model(LogisticRegression(), feed="pandas", rows=1000)
```

- [ ] **Step 2: Run them to see them fail**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run pytest tests/src/sqlearn/test__feed.py tests/src/sqlearn/test__model.py -q`
Expected: FAIL (`feed='pandas' is not built yet`).

- [ ] **Step 3: Implement**

Through DuckDB's own methods: `df()`, `pl()`, `to_arrow_table()`,
`fetchnumpy()`. Text columns become categories (spec §3.1): pandas `category`
dtype, Polars `Categorical`, Arrow dictionary-encoded, cast after the fetch
(DuckDB gives plain strings); NULL stays missing. In the search, training rows
come from Task 5's table in the model's form; no slicing of an in-memory fold
remains. Write ADR 0041 (spec §3: the forms, text as categories, streaming
through `partial_fit`, never swap, numpy staying the default), indexed under
"Models and search".

- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: hand data to models as numpy, pandas, polars or arrow` (body:
      `Refs #21`, `Refs #33`).

---

### Task 8: The stream: `partial_fit` in batches

**Files:**
- Modify: `src/sqlearn/_feed.py`, `src/sqlearn/_pipeline.py` (`_train`),
  `src/sqlearn/model_selection/search.py`
- Test: `tests/src/sqlearn/test__feed.py`

**Interfaces:**
- Produces: `train_streamed(con, rel, columns, target: str, model: Model) ->
  None` in `_feed.py`: computes `classes` in SQL (`SELECT DISTINCT target
  ORDER BY target`) when `partial_fit`'s signature has a `classes`
  parameter; per epoch `e` orders the rows by
  `hash(__sqlearn_row, model.seed, e)` (or keeps the input's order with
  `shuffle=False`), reads them with `to_arrow_reader(batch_size=rows)` and
  calls `partial_fit(X, y)` (plus `classes=` on the very first call). With
  `megabytes`, `rows = max(1, megabytes * 1_000_000 // (8 * len(columns)))`;
  with neither, `megabytes=100`.
- `_train` and the search's fold training call it when `feed="stream"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_stream_trains_in_batches_of_the_rows_given():
    sizes = []

    class Count:
        def partial_fit(self, x, y, classes=None):
            sizes.append(len(x))
            return self

        def fit(self, x, y):
            raise AssertionError("fit called")

        def predict(self, x):
            return np.zeros(len(x))

    pipe = sq.Pipeline([sq.Model(Count(), feed="stream", rows=40, epochs=2)])
    pipe.train(DATA_100_ROWS, target="y")
    assert sizes == [40, 40, 20] * 2


def test_stream_never_passes_an_empty_batch():
    sizes = []

    class Count:
        def partial_fit(self, x, y, classes=None):
            sizes.append(len(x))
            return self

        def fit(self, x, y):
            raise AssertionError

        def predict(self, x):
            return np.zeros(len(x))

    sq.Pipeline([sq.Model(Count(), feed="stream", rows=1000)]).train(
        DATA_100_ROWS, target="y"
    )
    assert sizes == [100] and 0 not in sizes


def test_stream_shuffles_by_seed_and_epoch():
    orders = record_first_rows(
        feed="stream", rows=10, epochs=2, seed=0
    )  # helper in the test file
    again = record_first_rows(feed="stream", rows=10, epochs=2, seed=0)
    assert orders == again and orders[0] != orders[1]


def test_stream_matches_sgd_on_the_same_order():
    sgd = SGDClassifier(random_state=0, shuffle=False)
    pipe = sq.Pipeline(
        [sq.Model(SGDClassifier(random_state=0), feed="stream", rows=25, shuffle=False)]
    )
    pipe.train(DATA_100_ROWS, target="y")
    x, y = numpy_of(DATA_100_ROWS)
    for start in range(0, 100, 25):
        sgd.partial_fit(
            x[start : start + 25], y[start : start + 25], classes=np.unique(y)
        )
    np.testing.assert_allclose(pipe["model"].estimator.coef_, sgd.coef_)
```

Plus: a model without `partial_fit` under `feed="stream"` is refused, naming
the other forms; `rows=` and `megabytes=` together are refused.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/test__feed.py -k stream -q`
Expected: FAIL (`feed='stream'` not handled by `_train`).

- [ ] **Step 3: Implement** `train_streamed` as its interface says; the
      pipeline's other bookkeeping (`_commit`, runs) is as for `fit`.
- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: stream training data to partial_fit in batches` (body: `Refs #21`,
      `Refs #33`).

---

### Task 9: The memory budget and never swapping

**Files:**
- Create: `src/sqlearn/_memory.py`
- Modify: `src/sqlearn/_config.py` (`Config.memory`, `set_config`, the
  shared connection), `src/sqlearn/_feed.py` (`fetch` checks first)
- Test: `tests/src/sqlearn/test__memory.py`,
  `tests/src/sqlearn/test__config.py`, `tests/src/sqlearn/test__feed.py`

**Interfaces:**
- Produces:
  - `Config.memory: int | None` (bytes; None means the default);
    `set_config(memory=...)` takes an int of bytes or a string DuckDB
    understands (`"8GB"`).
  - `_memory.physical() -> int`: physical memory without a new dependency
    (`os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")` on POSIX,
    `GlobalMemoryStatusEx` through `ctypes` on Windows).
  - `_memory.budget() -> int`: `Config.memory` or `0.8 * physical()`.
  - `_memory.allowance(con) -> int`: `budget() - duckdb_limit(con)`, where
    `duckdb_limit` reads `current_setting('memory_limit')`.
  - `_memory.estimate(rel, columns) -> int`: rows × (8 per number column,
    64 + the average length per text column), from one aggregate query.
  - The shared connection sets `memory_limit` to half the budget when it is
    created; a connection passed through `set_config` is never changed.
  - `fetch` (every form but `"stream"`) raises before fetching when
    `estimate > allowance`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_fold_too_big_is_refused_before_fetching(con):
    sq.set_config(memory="64MB")
    con.execute("SET memory_limit = '32MB'")
    sq.set_config(connection=con)
    big = con.sql(
        "SELECT i::DOUBLE AS a, i::DOUBLE AS b FROM range(5000000) t(i)"
    )  # ~80 MB
    with pytest.raises(SqlearnError, match="stream") as err:
        fetch(big, "numpy", ["a", "b"], None)
    assert "MB" in str(err.value)


def test_a_passed_connection_is_never_changed():
    con = duckdb.connect()
    con.execute("SET memory_limit = '1GB'")
    sq.set_config(connection=con, memory="4GB")
    assert (
        con.sql("SELECT current_setting('memory_limit')").fetchone()[0].startswith("1")
    )


def test_the_shared_connection_takes_half_the_budget():
    sq.set_config(connection=None, memory="4GB")
    assert duckdb_limit(connection()) == pytest.approx(2 * 10**9, rel=0.1)
```

- [ ] **Step 2: Run them to see them fail**

Run:
<!-- markdownlint-disable-next-line MD013 -->
`uv run pytest tests/src/sqlearn/test__memory.py tests/src/sqlearn/test__feed.py -q`
Expected: FAIL (`ModuleNotFoundError: sqlearn._memory`).

- [ ] **Step 3: Implement** as the interfaces say. The message: the fold's
      estimated size and the allowance, both in MB; why (it would swap);
      the fix: `feed="stream"` for a model with `partial_fit`, a larger
      `sq.set_config(memory=...)`, or fewer columns.
- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: refuse a hand-over that would swap` (body:
      `Refs #33`).

---

### Task 10: Kept preparations: `keep_prepared`

**Files:**
- Create: `src/sqlearn/model_selection/kept.py`
- Modify: `src/sqlearn/model_selection/search.py` (`Search(...,
  keep_prepared=None)`), `src/sqlearn/store.py` (`prepared`,
  `clear(prepared=...)`), `src/sqlearn/_inputs.py` (a stable key per input)
- Test: `tests/src/sqlearn/model_selection/test_kept.py`,
  `tests/src/sqlearn/test_store.py`

**Interfaces:**
- Consumes: Task 5's fold tables and `Folds.key`.
- Produces:
  - `Source.stable_key() -> tuple | None` in `_inputs.py`: a file by path,
    size and modification time; a pandas or Polars frame by its content
    hash; a table in a file database by file, name and row count; None for
    anything else.
  - `kept.table_name(stable: tuple, steps, folds_key, k: int) -> str`:
    `fold_<k>_<first 12 hex of sha256 of repr((stable, steps' qualified
    class names and settings, folds_key, k, sqlearn.__version__,
    duckdb.__version__))>`.
  - `kept.KeptFolds(path)`: attaches the file under the schema
    `sqlearn_prepared`, with `_index(table, data, steps, folds, fold,
    sqlearn_version, created)`; `get(name) -> str | None`, `put(name,
    sql, row)`.
  - `Search(..., keep_prepared: str | os.PathLike | None = None)`: fold
    tables are written to and read from the file instead of temporary
    tables; a found table is not prepared again (`transforms_` unchanged).
  - `sq.store.prepared(path) -> duckdb.DuckDBPyRelation` (the `_index`
    rows); `sq.store.clear(prepared=path)` drops every kept table and the
    index rows.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_second_search_prepares_nothing(tmp_path, data_file):
    kept = tmp_path / "kept.duckdb"
    first = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(3),
        keep_prepared=kept,
    )
    first.train(data_file, target="y")
    sq.store.clear()  # a new session's in-process store
    second = sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [0.5]},
        folds=sq.folds.kfold(3),
        keep_prepared=kept,
    )
    second.train(data_file, target="y")
    assert first.transforms_ == 3 and second.transforms_ == 0


def test_a_changed_file_is_prepared_again(tmp_path, data_file):
    kept = tmp_path / "kept.duckdb"
    run = lambda: sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept,
    ).train(data_file, target="y")
    run()
    os.utime(data_file, (time.time() + 10, time.time() + 10))
    assert run().transforms_ == 2
    assert sq.store.prepared(kept).count("*").fetchone()[0] == 4


def test_an_input_without_a_stable_identity_is_refused(tmp_path):
    rel = duckdb.sql("SELECT 1.0 AS x, 0 AS y")
    with pytest.raises(SqlearnError, match="keep_prepared"):
        sq.search(PIPE_WITH_SCALE, keep_prepared=tmp_path / "k.duckdb").train(
            rel, target="y"
        )


def test_clear_removes_the_kept_tables(tmp_path, data_file):
    kept = tmp_path / "kept.duckdb"
    sq.search(
        PIPE_WITH_SCALE,
        params={"model__C": [1.0]},
        folds=sq.folds.kfold(2),
        keep_prepared=kept,
    ).train(data_file, target="y")
    sq.store.clear(prepared=kept)
    assert sq.store.prepared(kept).count("*").fetchone()[0] == 0
```

The second test runs one search in a subprocess
(`subprocess.run([sys.executable, "-c", ...])`) as well, to prove the key
survives a restart.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/model_selection/test_kept.py -q`
Expected: FAIL (`unexpected keyword argument 'keep_prepared'`).

- [ ] **Step 3: Implement** as the interfaces say. The `writing-a-step` guide
      and `Search`'s docstring say a change to a user's step's code is not
      seen, and `sq.store.clear(prepared=path)` is the fix.
- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** —
      `feat: keep prepared folds in a DuckDB file across searches` (body:
      `Closes #25`, `Refs #33`).

---

### Task 11: Random search

**Files:**
- Modify: `src/sqlearn/model_selection/methods.py`,
  `src/sqlearn/model_selection/groups.py`
- Test: `tests/src/sqlearn/model_selection/test_methods.py`

**Interfaces:**
- Produces: `Random(trials=50, seed=0)` with `knows_all = True`;
  `sq.search.random(trials=50, seed=0)`. `start` draws `trials` settings with
  `random.Random(seed)`: a grid of the space chosen uniformly, then each
  setting a uniform choice of a list, or from a `Range` uniformly (or
  log-uniformly with `log=True`), an integer when both bounds are `int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_random_draws_the_same_settings_for_a_seed():
    space = [
        {
            "model__C": sq.search.range(0.01, 10, log=True),
            "model__penalty": ["l1", "l2"],
        }
    ]
    a, b = sq.search.random(trials=20, seed=3), sq.search.random(trials=20, seed=3)
    a.start(space, maximize=True)
    b.start(space, maximize=True)
    draws = [a.ask() for _ in range(20)]
    assert draws == [b.ask() for _ in range(20)] and a.ask() is None
    assert all(0.01 <= d["model__C"] <= 10 for d in draws)


def test_integer_bounds_draw_integers():
    m = sq.search.random(trials=30, seed=0)
    m.start([{"model__depth": sq.search.range(4, 10)}], maximize=True)
    assert all(
        isinstance(d["model__depth"], int) and 4 <= d["model__depth"] <= 10
        for d in iter(m.ask, None)
    )


def test_random_search_matches_scikit_learn_on_its_draws():
    # sqlearn's draws handed to GridSearchCV as a fixed list, on sqlearn's folds
    assert_scores_match_grid_search(
        method=sq.search.random(trials=8, seed=0)
    )  # helper in the test file
```

- [ ] **Step 2: Run them to see them fail**

Run:
`uv run pytest tests/src/sqlearn/model_selection/test_methods.py -k random -q`
Expected: FAIL (`AttributeError: ... has no attribute 'random'`).

- [ ] **Step 3: Implement** as the interface says; `trials=0` and negative
      values are refused; repr `sq.search.random(trials=20, seed=3)`.
- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: add random search` (body: `Refs #33`).

---

### Task 12: Optuna search

**Files:**
- Modify: `src/sqlearn/model_selection/methods.py`,
  `src/sqlearn/model_selection/groups.py`, `pyproject.toml` (test group:
  `optuna`)
- Test: `tests/src/sqlearn/model_selection/test_methods.py`

**Interfaces:**
- Produces: `Optuna(trials=100, sampler=None, seed=0)` with
  `knows_all = False`; `sq.search.optuna(...)`. `start(space, *, maximize)`
  creates `optuna.create_study(direction="maximize" if maximize else
  "minimize", sampler=sampler or TPESampler(seed=seed))` and the
  distributions: a list becomes `CategoricalDistribution` over its indices
  (so any value, a model among them, can be chosen); a `Range` becomes
  `FloatDistribution(low, high, log=log)`, or `IntDistribution` when both
  bounds are `int`; several grids add a categorical `__grid` index. `ask`
  calls `study.ask(fixed_distributions=...)` until `trials` were asked;
  `tell` calls `study.tell(trial, score)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_optuna_finds_the_better_setting():
    search = sq.search(
        PIPE,
        params={"model__C": sq.search.range(1e-4, 10, log=True)},
        method=sq.search.optuna(trials=15, seed=0),
        folds=sq.folds.kfold(3),
    )
    search.train(SEPARABLE, target="y")
    assert (
        search.best_params_["model__C"] > 0.1
        and search.results_.count("*").fetchone()[0] == 45
    )


def test_optuna_is_repeatable_for_a_seed():
    run = lambda: (
        sq.search(
            PIPE,
            params={"model__C": sq.search.range(1e-3, 10, log=True)},
            method=sq.search.optuna(trials=6, seed=1),
            folds=sq.folds.kfold(2),
        )
        .train(SEPARABLE, target="y")
        .best_params_
    )
    assert run() == run()


def test_optuna_chooses_among_models():
    search = sq.search(
        PIPE,
        params={"model": [LogisticRegression(), DecisionTreeClassifier()]},
        method=sq.search.optuna(trials=4, seed=0),
        folds=sq.folds.kfold(2),
    )
    assert type(search.train(SEPARABLE, target="y").best_params_["model"]).__name__ in {
        "LogisticRegression",
        "DecisionTreeClassifier",
    }
```

Plus: without optuna installed (monkeypatched import), the message says
`uv add optuna`; a minimising metric (`rmse`, Task 13) gives
`direction="minimize"`.

- [ ] **Step 2: Run them to see them fail**

Run:
`uv run pytest tests/src/sqlearn/model_selection/test_methods.py -k optuna -q`
Expected: FAIL (`AttributeError: ... has no attribute 'optuna'`).

- [ ] **Step 3: Implement** as the interface says; optuna's own logging is
      silenced to warnings while the search runs.
- [ ] **Step 4: Run `just test`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: add Optuna search over ask and tell` (body:
      `Refs #33`).

---

### Task 13: Regression metrics

**Files:**
- Create: `src/sqlearn/metrics/regression.py`,
  `validation/sqlearn/metrics/validate_regression.py`
- Modify: `src/sqlearn/metrics/__init__.py`, `validation/__main__.py`
- Test: `tests/src/sqlearn/metrics/test_regression.py`

**Interfaces:**
- Produces: `sq.metrics.rmse`, `sq.metrics.mae`, `sq.metrics.r2`, each a
  `Metric` (`greater_is_better` False, False, True), computed in one
  aggregate query; `r2` with `fsum` sums as `sq.agg.mean` is (ADR 0033).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    "metric, sk",
    [
        (sq.metrics.rmse, root_mean_squared_error),
        (sq.metrics.mae, mean_absolute_error),
        (sq.metrics.r2, r2_score),
    ],
)
def test_regression_metrics_match_scikit_learn(con, metric, sk):
    y, p = RNG.normal(size=500), RNG.normal(size=500)
    rel = con.sql("SELECT * FROM t")  # y and prediction from the arrays (fixture)
    assert metric.compute(rel, "y") == pytest.approx(sk(y, p), rel=1e-12)


def test_a_search_minimises_rmse():
    search = sq.search(
        REG_PIPE,
        params={"model__alpha": [0.01, 100.0]},
        metric=sq.metrics.rmse,
        folds=sq.folds.kfold(3),
    )
    assert search.train(REG_DATA, target="y").best_params_ == {"model__alpha": 0.01}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/metrics/test_regression.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**, and the validation runner against the
      mathematics (mpmath, exact sums) and scikit-learn, per ADR 0016, as
      `validate_accuracy.py` does.
- [ ] **Step 4: Run `just test`, then `just validate`** — Expected: all pass;
      `validation/sqlearn/metrics/regression.results.json` written.
- [ ] **Step 5: Commit** — `feat: add rmse, mae and r2` (body: `Refs #33`).

---

### Task 14: Probability metrics

**Files:**
- Create: `src/sqlearn/metrics/probability.py`,
  `validation/sqlearn/metrics/validate_probability.py`
- Modify: `src/sqlearn/metrics/accuracy.py` (`Metric`),
  `src/sqlearn/metrics/__init__.py`, `src/sqlearn/model_selection/search.py`
  (scoring through `predict_proba`), `validation/__main__.py`
- Test: `tests/src/sqlearn/metrics/test_probability.py`,
  `tests/src/sqlearn/model_selection/test_search.py`

**Interfaces:**
- Consumes: `predict_streamed(..., method="predict_proba")` (Task 6).
- Produces:
  - `Metric.needs: str = "predict"`, or `"predict_proba"`;
    `Metric.compute(rel, target, prediction="prediction", classes=None)`:
    for a `"predict_proba"` metric, `rel` holds `__sqlearn_proba_<i>` for
    each class of `classes` (the model's `classes_`, in order).
  - `sq.metrics.log_loss` (lower is better): rows' probabilities normalised
    to sum 1 and clipped to `[eps, 1 - eps]` with float64's eps, as
    scikit-learn 1.9.1.
  - `sq.metrics.roc_auc` (higher is better): two classes, the rank statistic
    with tied scores at their average rank; more than two, one-vs-rest
    averaged over classes (`multi_class="ovr"`, `average="macro"`).
  - The search scores a `"predict_proba"` metric through `predict_proba`.

- [ ] **Step 1: Write the failing tests**

```python
def test_log_loss_and_roc_auc_match_scikit_learn_binary_and_multiclass(con):
    for classes in (2, 4):
        y, proba = random_labels_and_probabilities(
            classes, rows=400, ties=True
        )  # helper
        rel = proba_relation(con, y, proba)
        assert sq.metrics.log_loss.compute(
            rel, "y", classes=list(range(classes))
        ) == pytest.approx(log_loss(y, proba), rel=1e-12)
        sk_auc = roc_auc_score(
            y,
            proba[:, 1] if classes == 2 else proba,
            multi_class="ovr",
            average="macro",
        )
        assert sq.metrics.roc_auc.compute(
            rel, "y", classes=list(range(classes))
        ) == pytest.approx(sk_auc, rel=1e-12)


def test_a_search_scores_by_log_loss():
    search = sq.search(
        PIPE,
        params={"model__C": [0.001, 10.0]},
        metric=sq.metrics.log_loss,
        folds=sq.folds.stratified(3),
    )
    assert search.train(SEPARABLE, target="y").best_params_ == {"model__C": 10.0}


def test_roc_auc_on_a_one_class_fold_is_refused():
    with pytest.raises(SqlearnError, match="stratified"):
        sq.search(
            PIPE,
            params={"model__C": [1.0]},
            metric=sq.metrics.roc_auc,
            folds=sq.folds.time("t", 3),
        ).train(SORTED_BY_CLASS, target="y")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/metrics/test_probability.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**; a model without `predict_proba` under a
      probability metric is refused before the first fold, naming the
      metric and the model. The validation runner as Task 13's.
- [ ] **Step 4: Run `just test`, then `just validate`** — Expected: all pass.
- [ ] **Step 5: Commit** — `feat: add log_loss and roc_auc` (body: `Refs #33`).

---

### Task 15: The script, larger than memory, and the docs

**Files:**
- Create: `tests/src/sqlearn/test_model_selection_script.py`,
  `validation/pipelines/validate_model_selection.py`,
  `docs/guide/tuning-a-model.md`, `docs/guide/handing-data-to-models.md`,
  `examples/plot_tuning.py`
- Modify: `docs/guide/index.md`, `docs/guide/from-scikit-learn.md`, the
  reference pages for `sq.search`, `sq.folds` and `sq.Model`,
  `validation/__main__.py`, every core guide page and example still showing
  the old names
- Test: as created

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_script_runs():
    run_the_script(
        tmp_data_files(rows=20_000)
    )  # spec §2, scaled down; helper in the file


@pytest.mark.slow
def test_the_stream_trains_larger_than_memory(tmp_path):
    """§2's streamed pipeline on 20 million rows within a 256 MB budget."""
    path = write_big_parquet(tmp_path, rows=20_000_000)  # ~1 GB of numbers
    sq.set_config(memory="256MB")
    peak_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.scale.standard(),
            sq.Model(SGDClassifier(loss="log_loss"), feed="stream", rows=100_000),
        ]
    )
    pipe.train(str(path), target="churned")
    grown = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - peak_before
    assert grown < PEAK_BOUND  # set from measurement, recorded in the test's docstring
    with pytest.raises(SqlearnError, match="stream"):
        sq.Pipeline([sq.impute.median(), sq.Model(LogisticRegression())]).train(
            str(path), target="churned"
        )
```

`ru_maxrss` is bytes on macOS and kilobytes on Linux: the test converts by
`sys.platform` before comparing.

The validation runner checks the §2 search against scikit-learn on
sqlearn's folds (`PredefinedSplit`): grid and random scores and best
settings equal within bounds set from measurement; each fold scheme against
its twin (`StratifiedKFold`, `GroupKFold`, `TimeSeriesSplit`) on class
balance, groups kept together and order kept; the same seeds give the same
`results_` byte for byte.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/src/sqlearn/test_model_selection_script.py -q`
Expected: FAIL on whatever the script still lacks (until every earlier task
is in, nothing should).

- [ ] **Step 3: Implement** the guide pages (spec §10: tuning a model —
      methods, folds, metrics, `keep_prepared`; handing data to models —
      each form, text columns, the stream, the memory budget), the gallery
      example, and the scikit-learn name map's new rows
      (`GridSearchCV` → `sq.search`, `RandomizedSearchCV` →
      `sq.search(method=sq.search.random(...))`, `StratifiedKFold` →
      `sq.folds.stratified`, `GroupKFold`, `TimeSeriesSplit`,
      `PredefinedSplit` → a user's own scheme).
- [ ] **Step 4: Run `just verify`** and, for the docs,
      `rm -rf docs/reference/generated docs/_build && just build-docs` —
      Expected: all pass, the slow tier included; results under
      `validation/` committed.
- [ ] **Step 5: Commit** — `docs: guide tuning a model and handing data to it`
      (body: `Closes #21`, `Refs #33`).

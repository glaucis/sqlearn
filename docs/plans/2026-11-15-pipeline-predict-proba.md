---
type: plan
tags: [pipeline, predict-proba, search, metrics, guide]
summary: "Implementation plan for Pipeline.predict_proba (#59): the target beside one __sqlearn_proba_<i> column per class in input order, Pipeline.classes_, Search.predict_proba, and the evaluating guide using them."
related: [docs/specs/pipeline-predict-proba.md, docs/adr/0050-predict-proba-keeps-the-target.md]
---
# Pipeline.predict_proba Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A trained `Pipeline` (and a trained `Search`) hands back the target
beside its model's probabilities, one column per class, so every probability
metric and curve reads the result directly.

**Architecture:** `Pipeline.predict` and `Pipeline.predict_proba` share one
private helper that prepares the numbered rows and streams them through
`predict_streamed` / `stream_into` with `method=`. For `predict_proba`, when
the data holds the trained target, the target is taken from the numbered
source by `__sqlearn_row` and joined, in DuckDB, beside the stream's
probability table, sorted by the row number. `Search.predict_proba` hands off
to `best_pipeline_`.

**Tech Stack:** Python 3.12, DuckDB 2.0 relational API, scikit-learn 1.9.1
(tests only), pytest, `uv`, `just`.

**Spec:** `docs/specs/pipeline-predict-proba.md`. ADR 0050. Issue #59.

## Global Constraints

- Computation is SQL in DuckDB; no row reaches Python but the features the
  model reads (ADR 0002). The target is joined in DuckDB.
- The probability columns are named `__sqlearn_proba_0`, `__sqlearn_proba_1`,
  ... (`sqlearn._feed.PROBA`), in the order of the model's `classes_`.
- The target column comes first, under the name and type it has in the data.
- Every refusal is a `SqlearnError` whose message ends in a `Fix:` sentence.
- British English in prose and docstrings, American spelling in identifiers.
- Docstrings in the numpydoc form of the neighbouring methods, with an
  `Examples` section that runs as a doctest.
- Tests are named in `GLOSSARY.md` terms (train, predict, target, pipeline).

## Review Focus

1. **Text labels:** a target of `"no"`/`"yes"` comes back as text beside
   `__sqlearn_proba_0` (`"no"`) and `__sqlearn_proba_1` (`"yes"`), and
   `classes_ == ["no", "yes"]`. Test in Task 1.
2. **A NULL target in the scored data** is handed back as NULL, not refused
   (only train refuses a missing target). Test in Task 1.
3. **A pipeline put back from a file** (`sq.save` / `sq.load`) predicts the
   same probabilities as before saving. Test in Task 1.
4. **A model trained with `feed="pandas"`** gets its `predict_proba` batches
   as a `DataFrame`, as `predict` does. Test in Task 1.
5. **Many rows read by several threads** keep the input's order, the target
   lining up with its probabilities. Test in Task 1.

---

### Task 1: `Pipeline.predict_proba` and `Pipeline.classes_`

**Files:**
- Modify: `src/sqlearn/_pipeline.py` (`predict` at 1476; new helper and two
  members beside it)
- Test: `tests/src/sqlearn/test__pipeline.py` (after
  `test_predictions_outlive_the_input`)

**Interfaces:**
- Consumes: `predict_streamed(con, rel, columns, row, model, *, method,
  categories)` and `PROBA` from `sqlearn._feed`.
- Produces: `Pipeline.predict_proba(self, data: object, out: str | Output |
  None = None) -> Any`; `Pipeline.classes_ -> list[object]` (property).

- [ ] **Step 1: Write the failing tests**

```python
def test_predict_proba_gives_the_target_beside_each_class_in_input_order():
    from sklearn.linear_model import LogisticRegression

    frame = pd.DataFrame({"x": [5.0, 1.0, 4.0, 2.0, 3.0], "y": [1, 0, 1, 0, 1]})
    pipe = sq.Pipeline([sq.scale.standard(), LogisticRegression()])
    pipe.train(frame, target="y")
    rel = pipe.predict_proba(frame)
    assert isinstance(rel, duckdb.DuckDBPyRelation)
    assert rel.columns == ["y", "__sqlearn_proba_0", "__sqlearn_proba_1"]
    got = rel.fetchnumpy()
    assert got["y"].tolist() == [1, 0, 1, 0, 1]
    scaled = (frame[["x"]] - 3.0) / frame["x"].std(ddof=0)
    want = pipe.model_.predict_proba(scaled.to_numpy())
    np.testing.assert_allclose(got["__sqlearn_proba_0"], want[:, 0], rtol=1e-12)
    np.testing.assert_allclose(got["__sqlearn_proba_1"], want[:, 1], rtol=1e-12)
    assert pipe.classes_ == [0, 1]
    assert len(pipe.runs_) == 1

def test_predict_proba_without_the_target_gives_the_probabilities_only(): ...
    # rel.columns == ["__sqlearn_proba_0", "__sqlearn_proba_1"]

def test_predict_proba_keeps_text_labels():  # Review Focus 1
    # DecisionTreeClassifier on y "no"/"yes": y comes back as text,
    # classes_ == ["no", "yes"]

def test_predict_proba_hands_back_a_null_target():  # Review Focus 2
    # scored data with y NULL in one row: that row's y is None, its
    # probabilities are numbers

def test_predict_proba_of_a_loaded_pipeline_matches(tmp_path):  # Focus 3
    # sq.save(pipe, path); sq.load(path).predict_proba(frame) equals
    # pipe.predict_proba(frame) (fetchall)

def test_predict_proba_uses_the_trained_feed():  # Review Focus 4
    # a classifier recording type(x) in predict_proba, trained with
    # feed="pandas": it saw a pd.DataFrame

def test_probabilities_line_up_with_a_large_parquet_input(tmp_path):  # 5
    # as test_predictions_line_up_with_a_large_parquet_input, a model
    # whose predict_proba is [[1 - x/1e6, x/1e6]]: y and proba_1 * 1e6
    # match the file's y and x row for row

def test_predict_proba_refuses_mistakes():
    # untrained: SqlearnError match "not been trained"
    # Echo (no predict_proba): match "has no predict_proba"
    # a model with predict_proba but no classes_: match "classes_"
    # pipe.classes_ before train: AttributeError match "train"
```

- [ ] **Step 2: Run them to watch them fail**

Run:
`uv run pytest tests/src/sqlearn/test__pipeline.py -v -k`
`"predict_proba or probabilities_line_up"`
Expected: each FAILS with
`AttributeError: 'Pipeline' object has no attribute 'predict_proba'` (or
`classes_`).

- [ ] **Step 3: Implement**

- Move the body of `predict` after the trained check into
  `_predicted(self, data: object, method: str) -> duckdb.DuckDBPyRelation`;
  `predict` becomes the check plus `to_output(self._predicted(data,
  "predict"), out ...)`. `predict`'s behaviour and messages do not change.
- `predict_proba`: the same trained check and message as `predict`; then
  refuse a model without a callable `predict_proba` ("the model {cls} has
  no predict_proba, so it gives no probabilities. Fix: use a classifier
  that has one, or call predict.") and one without `classes_` after
  training ("the fitted model {cls} has no classes_ naming its
  probability columns. Fix: use a classifier that sets classes_ when
  fitted, as scikit-learn's do."), before any query runs.
- In `_predicted` with `"predict_proba"`, when `self._target` is a column
  of the data: number the rows before dropping the target, so the
  target and the features share one `__sqlearn_row`; prepare and stream as
  now; join the stream's table to `SELECT __sqlearn_row, <target>` from the
  numbered source on the row number, order by it, project the target then
  the `PROBA` columns. Use `stream_into` directly when `predict_streamed`'s
  projection is in the way, keeping its `weakref.finalize` drop.
- `classes_`: a property returning `list(self.model_.estimator.classes_)`
  as Python values (`.tolist()` when it is an array); `AttributeError`
  with "Fix: call train(data, target=...) first." when untrained or the
  model has none.
- Docstrings: `predict_proba` names the columns, the target rule (ADR
  0050) and its example scoring `average_precision`; `classes_` says what
  it orders.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/src/sqlearn/test__pipeline.py -v` then `just test`
Expected: all pass; name every failure if not.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/_pipeline.py tests/src/sqlearn/test__pipeline.py tests.json
git commit -m "feat: a trained pipeline hands back its probabilities (#59)"
```

### Task 2: `Search.predict_proba`

**Files:**
- Modify: `src/sqlearn/model_selection/search.py` (beside `predict`, 792)
- Test: `tests/src/sqlearn/model_selection/test_search.py` (after
  `test_predict_uses_the_best_pipeline`)

**Interfaces:**
- Consumes: `Pipeline.predict_proba` from Task 1.
- Produces: `Search.predict_proba(self, data: object, out: str | Output |
  None = None) -> Any`.

- [ ] **Step 1: Write the failing test**

```python
def test_predict_proba_uses_the_best_pipeline():
    data = customers()
    search = sq.search(slice_pipe(), params=GRID)
    with pytest.raises(sq.errors.SqlearnError, match="train"):
        search.predict_proba(data)
    search.train(data, target="churned")
    got = search.predict_proba(data).fetchall()
    assert got == search.best_pipeline_.predict_proba(data).fetchall()
```

- [ ] **Step 2: Run it to watch it fail**

Run:
`uv run pytest tests/src/sqlearn/model_selection/test_search.py -v -k`
`test_predict_proba_uses_the_best_pipeline`
Expected: FAIL with
`AttributeError: 'Search' object has no attribute 'predict_proba'`.

- [ ] **Step 3: Implement** `predict_proba` as `predict` is: the same
  untrained message, then `best.predict_proba(data, out)`; numpydoc
  docstring with a runnable example.

- [ ] **Step 4: Run it, then `just test`**

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/model_selection/search.py tests/src/sqlearn/model_selection/test_search.py tests.json
git commit -m "feat: a search hands back its best pipeline's probabilities (#59)"
```

### Task 3: The guide, the docs and the handoff

**Files:**
- Modify: `docs/guide/evaluating-a-model.md` (the code cells at 27-55 and
  78-86 and the prose around them)
- Modify: any reference page or glossary entry that lists `Pipeline`'s or
  `Search`'s members (search with `qmd query "Pipeline predict members" -c
  sqlearn` and `grep -rn "predict(" docs/`)
- Modify: `HANDOFF.md`, `CLAUDE.md` (the state of work line, if it names
  #59)

- [ ] **Step 1:** Rewrite the guide's first cell: drop `prepare`,
  `features`, `pipe.model_.predict_proba` and the pandas frame; build
  `rows` from `pipe.predict_proba(held)` with the prediction beside it
  (or score `fbeta` from `pipe.predict(held)` with the target), keeping
  every later cell's output meaning the same. The `average_precision`
  cell becomes `sq.metrics.average_precision.compute(pipe.predict_proba(
  held), "target", classes=pipe.classes_)`; the curves read
  `__sqlearn_proba_1`.
- [ ] **Step 2:** Rebuild the docs from clean and check the guide's cells
  run: `rm -rf docs/reference/generated docs/_build && just build-docs`.
  Expected: no errors or warnings from the guide.
- [ ] **Step 3:** `just fmt`, `just check`, `just verify`. Expected: pass on
  each interpreter; name every failure.
- [ ] **Step 4:** Update `HANDOFF.md` (move #59 to "Just finished") and
  comment on #59 with a summary; commit.

```bash
git add docs HANDOFF.md
git commit -m "docs: the guide scores held-out rows with predict_proba (#59)"
```

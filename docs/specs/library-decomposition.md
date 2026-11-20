---
type: spec
tags: [decomposition, pca, library-breadth, numpy, gram-matrix, streaming]
summary: "Spec for PCA in sqlearn (overview 3.3): sq.decompose.pca as scikit-learn 1.9.1's PCA with svd_solver='covariance_eigh', learned by streaming centred batches from DuckDB into numpy to build XᵀX, applied in SQL; numpy becomes a runtime dependency and the core gains a learn that builds XᵀX."
related: [docs/architecture/overview.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0034-a-grouped-api.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md, docs/adr/0016-validation-method.md]
---
# Library breadth: decomposition (PCA)

The tenth area of part 3.3 of [the overview](../architecture/overview.md),
after [feature selection](library-feature-selection.md).

Status: approved by Tomas on 2026-11-20.

## 1. Purpose

PCA replaces many correlated numeric columns with a few that carry most of
their variance. It makes wide data cheaper to train on and easier to look at.
In sqlearn it learns from data larger than memory. Applying it is a weighted
sum per output column, which is plain SQL, so it runs in one query with the
steps around it.

It is also the first step whose learning needs linear algebra that SQL cannot
do well: the eigenvectors of a matrix. The way this spec solves that (the core
builds XᵀX, numpy finishes it) is the way linear and ridge regression will
learn later, so the core part (§5) is written for them too.

## 2. What it looks like

```python
pipe = sq.Pipeline([sq.impute(), sq.scale(), sq.decompose.pca(n_components=3)])
pipe.learn("data/sales/*.parquet")
pipe["pca"].explained_variance_ratio_  # [0.52, 0.21, 0.09]
pipe["pca"].components_  # 3 lists of 50 numbers
pipe.apply("data/sales/*.parquet")  # columns pca0, pca1, pca2

sq.decompose.pca(n_components=0.95)  # as many as keep 95% of the variance
sq.decompose.pca(whiten=True)  # each output of variance 1
sq.decompose(method="pca", n_components=3)  # the general form

pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(), LogisticRegression()])
sq.search(pipe, params={"pca__n_components": [5, 10, 20]}, metric=sq.metrics.f1)
```

## 3. Rules

1. **It behaves as scikit-learn 1.9.1's `PCA` with
   `svd_solver="covariance_eigh"`**: the same components, signs, explained
   variances, output names, defaults and refusals. Where this text and
   scikit-learn disagree, scikit-learn is built and this spec is corrected.
   How the numbers are computed may differ (§4.3 centres first), as in the
   earlier areas: the results are measured against the exact mathematics and
   against scikit-learn within bounds (ADR 0016), and that is not a departure
   from the API under ADR 0003.
2. **SQL does the pass over the data; numpy does the small matrix.** The
   means and the prepared rows come from DuckDB. numpy multiplies batches into
   XᵀX and finds its eigenvectors. Applying is SQL only.
3. **It learns from data larger than memory**: at most one batch of rows and
   one p × p matrix are in Python's memory at a time.
4. **sqlearn warns and the user chooses** (ADR 0046): where scikit-learn
   warns, sqlearn warns too, with a `Fix:` line.

## 4. The group: `sq.decompose`

A group in the manner of ADR 0034: `sq.decompose(*names, method="pca", ...,
cols=None)` and the shortcut `sq.decompose.pca(*names, n_components=None,
whiten=False, cols=None)`. Positional arguments are columns, as in every
group; the settings are keyword-only. By default it takes the numeric columns.
`pca` is the only method in this spec.

### 4.1 Settings

- `n_components`: `None` (all: the smaller of the row count and the column
  count), a whole number from 0 up to that, or a fraction strictly between 0
  and 1 (the fewest components whose cumulative explained variance ratio is
  above it, scikit-learn's `searchsorted(..., side="right") + 1`). Anything
  else is refused when the step is built, with a `Fix:`; a whole number above
  the smaller of the row count and the column count is refused at learn, as
  scikit-learn refuses it at fit.
- `whiten`: divide each output by the square root of its explained variance,
  as scikit-learn does, including its floor of machine epsilon on that square
  root.

### 4.2 Learned values

As scikit-learn's attributes, each a plain Python value:

- `components_`: `n_components_` lists of p floats, the rows of scikit-learn's
  array, in its order.
- `explained_variance_`, `explained_variance_ratio_`, `singular_values_`:
  `n_components_` floats each.
- `mean_`: p floats. `n_components_`, `n_samples_`: whole numbers.
  `noise_variance_`: a float, as scikit-learn computes it.

What is learned and kept (in the store and in `sq.save`) is the whole
decomposition: the means, the row count, all p eigenvalues and all p
components, sign-chosen and largest first. It does not depend on
`n_components` or `whiten`. The attributes above, `n_components_` included
(found from the ratios when `n_components` is a fraction), are cut from it
when read, and the apply SQL is written from the cut. So a change of
`n_components` or `whiten` never learns again (§5.4).

### 4.3 Learning

1. The means of the input columns come from SQL, one aggregate per column.
2. DuckDB runs the steps before PCA, subtracts the means, and hands the rows
   over in batches. numpy adds each batch's `xᵀx` into a running p × p sum.
   Centring first keeps the sum accurate (scikit-learn subtracts the means
   from the uncentred sum afterwards, which this spec does not copy).
3. The covariance is the sum divided by `n - 1`; numpy's `eigh` gives its
   eigenvalues and eigenvectors; then scikit-learn's steps in order: largest
   first, negative eigenvalues set to 0, the sign of each component chosen so
   its largest entry in absolute value is positive (`svd_flip` with
   `u_based_decision=False`), the ratios, the singular values
   `sqrt(eigenvalue * (n - 1))`, the truncation to `n_components_`, and the
   noise variance.

Refused at learn, each with a `Fix:`: a missing value (NULL or NaN) in an
input (scikit-learn refuses NaN; impute first), an infinite value, fewer than
two rows, a non-numeric column chosen by name.

### 4.4 Applying

The output replaces the input columns: `pca0`, …, `pca{k-1}` (scikit-learn's
`get_feature_names_out`), in the place of the first input column, named by ADR
0035 when they clash. Each is one SQL expression,
`w₀·(x₀ − mean₀) + … + wₚ·(xₚ − meanₚ)`, divided by the whitening scale when
`whiten`. The weights and means are constants in the SQL, so applying is one
query, in parallel, on data of any size. A missing value in a row at apply is
refused as in §4.3.

## 5. The contract: a learn that builds XᵀX

### 5.1 What a step declares

A step declares that it learns from the Gram matrix of its input columns. The
core then:

1. learns the means of the step's input columns (an ordinary SQL learn);
2. streams the step's centred input rows from DuckDB and builds `XᵀX` in numpy,
   as §4.3 step 2 (`Xᵀy` against the target is not built here: linear
   regression, its first user, adds it);
3. hands the step the matrix, the means and the row count, and keeps what the
   step returns as its learned values, as for any other step: in the learning
   store, on the step after `learn`, in `sq.save`.

The step never sees a row. Its learned values are what it returns from the
matrix, so the store, saving and validation treat it like any other step.

The declaration is internal for now: sqlearn's own steps use it, and a
user's step (ADR 0019) cannot yet. It becomes public, with its own docs and
messages, once linear regression has used it and its shape has held.

### 5.2 Where it sits in the runs

Learned values reach the apply SQL as constants, so a Gram step is learned in
its own run: the steps before it are learned first (their values are needed to
prepare its rows), and the steps after it in a later run. As with a dynamic
step (ADR 0012), `n_components` as a fraction makes the number of outputs
known only after learning. `pipe.runs_` lists the streaming query with its
run.

### 5.3 Batches

- Batches come from DuckDB as numpy arrays (`fetchnumpy`), with no pandas or
  pyarrow: the runtime dependencies are `duckdb` and `numpy`.
- A batch's size comes from the memory budget, as the streamed training
  batches' (`MEGABYTES` in `_feed.py`) and counts against it.
- The matrix on 1 thread and on many agrees within the bounds of ADR 0043,
  not to the bit: the means come from a SQL sum, which DuckDB adds in the
  order its threads finish.
- The p × p matrix and its decomposition count against the memory budget
  with the batch. When they would not fit (about 10,000 columns needs 800 MB
  per copy of the matrix), the learn is refused before any batch, with a
  `Fix:` (fewer columns, a larger budget).
- How the rows are cut into batches is the builder's (§10). The spike that led
  to this spec numbered the rows into a temporary table (DuckDB spills it to
  disk) and fetched them by row range: correct, but it writes and reads the
  data a second time, about half the learn time. A cheaper way is preferred,
  measured against that one.

### 5.4 Folds and the store

A Gram step is keyed in the store as any other step. `n_components` and
`whiten` choose only the output (ADR 0056) and stay out of the key, since the
whole decomposition is kept (§4.2): a search over them learns once per fold
and cuts per setting. A search over the columns or the steps before it learns
again.

## 6. Decisions to record

Both were decided by Tomas on 2026-11-20 in the conversation that led to this
spec; approving the spec accepts them, and the plan writes them first.

- **ADR 0057: numpy is a runtime dependency.** Amends ADR 0005 ("nothing
  NumPy-shaped"). The reason: SQL computes the small matrix, but DuckDB has no
  solver or eigen function, and a pure-Python one is too slow beyond about 100
  columns (measured: a 500 × 500 solve takes 1.75 s in pure Python and 4 ms in
  numpy). numpy's licence is BSD-3. Its comment goes beside it in
  `pyproject.toml`.
- **ADR 0058: a step may learn from XᵀX built in numpy.** Amends ADR 0002 ("no
  step may fall back to pulling data into Python"). The reason, measured on 1M
  rows on 2026-11-20 (load about 3 to 7): XᵀX in SQL alone took 1.4 s at 50
  columns, 26 s at 200 and ran out of memory at 500 (12.7 GB); streamed into
  numpy it took 0.2 s, 0.9 s and 4.6 s. On 12.5M rows × 200 columns (20 GB as
  doubles, more than the 17 GB of RAM) at a 2 GB DuckDB limit, the learn took
  about 2 minutes at a peak of 3.0 GB, and agreed with DuckDB's `covar_pop` to
  3e-14. The ADR keeps the rule for everything else: the data passes through
  Python only in batches, only for a Gram step, and applying stays SQL.

## 7. Tests and validation

- **Against scikit-learn:** on generated data and on `devdata`'s datasets,
  each setting of §4.1 gives `PCA(svd_solver="covariance_eigh")`'s learned
  values (§4.2) and outputs within bounds, the signs included. The edge
  rules one test each: `n_components` 0, `None`, a fraction met exactly by a
  cumulative ratio, above the limit; a constant column; all columns constant;
  more columns than rows; two rows; `whiten` with a zero variance.
- **Against the mathematics:** the covariance against exact fractions, and the
  eigenvalues and eigenvectors against `mpmath`'s at high precision, in a
  validation runner `validate_decompose` (ADR 0016). Components of nearly
  equal eigenvalues are ill-defined one by one; they are compared through the
  outputs they produce, or left out of the per-component bounds with a note.
- **The contract (§5):** a Gram step learns in its own run; the run counts of
  pipelines with steps before and after it; a search over `n_components`
  learns once per fold; the matrix on 1 and on many threads within bounds;
  a matrix over the memory budget refused before any batch.
- **In a pipeline and a search:** `train` then `predict` gives scikit-learn's
  `Pipeline` its predictions with the same model.
- **Saving:** `sq.save` then `sq.load` gives the same output. The learned
  lists of lists reach the loader's checks as every learned value does: each
  number a plain `int` or `float`, every tag probed end to end (HANDOFF's
  `sq.load` security trap).
- **Larger than memory:** a slow test learning PCA on data larger than the
  memory limit, and a benchmark recording §6's measurements properly under
  `docs/benchmarks/`, on a quiet machine with `uptime` before and after.

## 8. Documentation

- A reference page for `sq.decompose` and `sq.decompose.pca`, from the
  docstrings, with examples.
- A user guide page, "Reducing columns", after "Selecting features".
- The scikit-learn mapping page: `PCA(n_components=3)` →
  `sq.decompose.pca(n_components=3)`.
- The architecture docs: the Gram learn (§5) where learning is described, and
  ADR 0002's and 0005's amendments wherever those rules are quoted
  (`CLAUDE.md` included: "the only runtime dependency is duckdb").
- `GLOSSARY.md`: **Gram step**, a step that learns from XᵀX of its columns.

## 9. Not in this spec

- `svd_solver` (always the covariance method), `tol`, `iterated_power`,
  `n_oversamples`, `power_iteration_normalizer`, `random_state`, `copy`.
- `n_components="mle"`, `inverse_transform`, `get_covariance`,
  `get_precision`, `score`, `score_samples`.
- `IncrementalPCA` (streaming already makes PCA incremental), `KernelPCA` (an
  n × n matrix), `TruncatedSVD` and sparse input, `FactorAnalysis`, `NMF`,
  `FastICA`.
- Linear and ridge regression: the next users of §5, each its own area.

## 10. Left to the builder

- How the rows are cut into batches (§5.3), measured against the
  temporary-table way.
- The form of a step's declaration that it is a Gram step, and of what the
  core hands it.
- How the run planner places a Gram step (§5.2) within ADR 0018's rules.
- Module layout, internal names, message text beyond ADR 0019's form.
- The bounds of §7, measured as the earlier areas' were.
- The order of the work; the dependency (ADR 0057) and the contract (§5) come
  first.

## 11. Done when

- §2's examples run end to end.
- ADRs 0057 and 0058 are written and accepted.
- §7's tests and validations pass in `just verify`, the slow tier included,
  with their results committed under `validation/`.
- §8's documentation builds.

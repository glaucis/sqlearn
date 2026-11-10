---
type: spec
tags: [datasets, generators, bundled-data, random-numbers, library-breadth]
summary: "Spec for the datasets area of sqlearn's library breadth (overview 3.3): three small bundled datasets and four generators written in SQL, every one returned as a DuckDB relation, the generators repeatable from a seed at any size (bit for bit on one machine, within rounding across machines)."
related: [docs/architecture/overview.md, docs/adr/0003-scikit-learn-style-api.md, docs/adr/0006-local-and-offline.md, docs/adr/0016-validation-method.md, docs/adr/0034-a-grouped-api.md]
---
# Library breadth: datasets

The fourth area of part 3.3 of [the overview](../architecture/overview.md).

Status: written on 2026-11-10 at Tomas's request without a design talk ("just
do it"); every decision below is the spec's call. Tomas reviews it with the
build.

## 1. Purpose

sqlearn has no data of its own. Its examples build data with numpy and write
it to Parquet (`examples/plot_tuning.py`), the learning site's lessons will
need data from their first page, and nothing shows sqlearn on data larger than
memory without a file to download.

This area gives sqlearn data in two ways:

1. **Generators written in SQL.** The data is built inside DuckDB, row by row,
   from a seed: any number of rows, larger than memory included, no file, no
   download. The same seed gives the same rows on every thread count: bit for
   bit on one machine, and on every machine and DuckDB version within rounding
   (ADR 0043), exactly for the uniforms. A class derived from a normal by a
   threshold (`customers`' target) can differ across platforms on the rare row
   that lies on the threshold, since normals agree only within rounding there.
2. **Three small classic datasets bundled in the package**, the ones
   scikit-learn's own tutorials start from: iris, wine and breast cancer.

Nothing is fetched (ADR 0006). A fetcher of larger real datasets is a later
idea, and would be a call whose name says it fetches.

## 2. What it looks like

```python
import sqlearn as sq

iris = sq.datasets.iris()  # a DuckDB relation: 4 features and "target"
pipe = sq.Pipeline([sq.scale.standard(), sq.Model(...)]).train(iris, "target")

big = sq.datasets.classification(rows=100_000_000, seed=0)  # nothing built yet
big.limit(5).fetchall()  # five rows, at once
sq.Pipeline([sq.scale.standard()]).learn(big)  # streamed, larger than memory

customers = sq.datasets.customers(rows=5_000, seed=0)  # gaps, text, a target
```

## 3. The contract (ADR 0045)

- **A group, `sq.datasets`**, of functions named for what they give: no
  `load_` or `make_` prefix (ADR 0034's short names; `sq.metrics.f1`, not
  `f1_score`).
- **Every function returns a `duckdb.DuckDBPyRelation`** on sqlearn's
  connection (`sqlearn._config.connection()`), not scikit-learn's `Bunch` or
  an `(X, y)` pair. A relation is what every sqlearn verb takes, it is lazy,
  and it can be written anywhere with DuckDB (`rel.to_parquet(path)`).
- **The target is a column named `target`**, last, as in scikit-learn's
  `as_frame=True` frame.
- **Settings keep scikit-learn's names** (`n_features`, `centers`,
  `cluster_std`, `n_informative`, `noise`, `flip_y`, `class_sep`, ...) with
  two departures, both sqlearn's existing words: **`rows=`** for `n_samples`
  and **`seed=`** for `random_state` (an `int`, default 0, as
  `sq.encode.target`'s and `sq.folds`'s).
- **A generated relation is a query, not a table.** Creating it reads and
  writes nothing; each use computes its rows again, the same ones.
- **Bad settings are refused** with a `SqlearnError` in the house form (what,
  `Why:`, `Fix:`), where scikit-learn raises `ValueError`: a non-integer or
  non-positive `rows`, `n_informative + n_redundant > n_features`,
  `n_classes * n_clusters_per_class > 2 ** n_informative`, `weights` not
  summing to at most 1 or of the wrong length, a negative `noise`,
  `cluster_std` or `flip_y` outside `[0, 1]`, a `seed` that is not an `int`.

## 4. Random numbers in SQL

Every random value is a pure function of `(seed, row, stream)`: no state, no
order, so rows can be computed in any order on any thread, and a slice of a
huge relation is the same rows as in the whole.

- **The generator is SplitMix64**, written in SQL over `UBIGINT` with the
  multiplications in `UHUGEINT` taken modulo `2**64`, so it does not depend on
  DuckDB's `hash()` (which may change between versions) or on `random()`
  (which is not repeatable across threads). Its input is one 64-bit key mixed
  from the seed, the row number and the stream number (each value of each
  column has its own stream).
- **A uniform** in `[0, 1)` is the top 53 bits of the output times `2**-53`.
- **A normal** is Box-Muller over two uniforms of their own streams:
  `sqrt(-2 ln(1 - u1)) * cos(2 pi u2)`.
- **Small constants are drawn in Python** with the same SplitMix64 (a
  reference implementation in Python, tested equal to the SQL one bit for
  bit): cluster centres, regression coefficients, the classification's
  mixing matrices. They are settings of the query, a handful of numbers, never
  data (ADR 0002).
- **How far the values repeat.** Keys and uniforms are exact integer arithmetic,
  so they are the same bit for bit on every machine, thread count and DuckDB
  version. Normals go through `ln`, `cos` and `sqrt`, which libm does not
  promise to round alike on every platform or build: on one machine they are the
  same bit for bit (tested, SQL against Python), elsewhere the same within
  rounding (ADR 0043). A class derived from a normal by a threshold
  (`customers`' target) can differ across platforms on the rare row that lies on
  the threshold, since normals agree only within rounding there.
- The values are sqlearn's own: the same distributions as scikit-learn's,
  never the same numbers (numpy's generator is not reproducible in SQL).

## 5. The generators

Feature columns are `DOUBLE`, named `x0`, `x1`, ...; `target` is `BIGINT` for
classes, `DOUBLE` for regression. Row `i` runs from 0 to `rows - 1`; the
rows come in row order while DuckDB's `preserve_insertion_order` is on (its
default, and sqlearn's predict refuses a connection with it off); there is no
`ORDER BY`, which would sort every row and lose the laziness. The row number
itself is not a column.

- **`blobs`** (`rows=100`, `n_features=2`, `centers=3`, `cluster_std=1.0`,
  `center_box=(-10.0, 10.0)`, `seed=0`): as `make_blobs`. `centers` is a count
  (centres drawn uniformly in the box) or a list of points; `cluster_std` one
  number or one per centre. Each row picks its centre uniformly at random
  (scikit-learn deals equal counts; a row of its own cannot, so the counts are
  equal only in expectation); `target` is the centre's number.
- **`regression`** (`rows=100`, `n_features=100`, `n_informative=None` (10, or
  `n_features` when fewer), `bias=0.0`, `noise=0.0`, `seed=0`): as
  `make_regression` without its rank and tail settings. Features are standard
  normal; the first `n_informative` coefficients are uniform in `[0, 100)`, the
  rest 0; `target = x @ coef + bias + noise * N(0, 1)`.
- **`classification`** (`rows=100`, `n_features=20`, `n_informative=2`,
  `n_redundant=2`, `n_classes=2`, `n_clusters_per_class=2`, `weights=None`,
  `flip_y=0.01`, `class_sep=1.0`, `seed=0`): as `make_classification` without
  `n_repeated`, `hypercube=False`, `shift`, `scale` and `shuffle`. Clusters sit
  at vertices of a hypercube of side `2 * class_sep` in the informative space;
  each row picks its cluster by the class weights (equal by default), its
  informative features are standard normal times the cluster's random matrix
  plus its vertex, the redundant features random combinations of the informative
  ones, the rest noise. With probability `flip_y` the label is replaced by a
  class drawn uniformly. The columns come in that order: informative, redundant,
  noise.
- **`customers(rows=1000, seed=0)`**: sqlearn's own, the table its examples
  and lessons need, with the gaps and text that scikit-learn's generators lack:
  `age` (DOUBLE, normal mean 40 sd 12, a tenth NULL), `income` (DOUBLE,
  log-normal, mu 10.5, sigma 0.5, a twentieth NULL), `city` (VARCHAR, one of
  Oslo, Lima, Kyoto, Cairo, uniform), `plan` (VARCHAR: basic 0.5, plus 0.3, pro
  0.2), and `churned` as `target` (BIGINT 0/1) from the signal of
  `examples/plot_tuning.py`, with the income median replaced by the
  distribution's own, `exp(10.5)`. Its target column is named `target`, as
  every dataset's.

## 6. The bundled datasets

- **`iris()`, `wine()`, `breast_cancer()`**: the rows of scikit-learn 1.9.1's
  `load_iris`, `load_wine` and `load_breast_cancer` with `as_frame=True`:
  the same column names (scikit-learn's `feature_names`, spaces included,
  quoted as every identifier is), the same values, `target` the class code
  (`BIGINT`), the same row order.
- **The files** are CSV under `src/sqlearn/datasets/data/`, copied once from
  the installed scikit-learn (its `datasets/data/` files, rewritten with a
  header of column names), read with explicit column types. Together about
  140 kB.
- **Licence:** the three come from the UCI Machine Learning Repository, which
  licenses them under CC BY 4.0; a `README.md` beside the files gives each
  one's source, creators and citation, as the licence asks. scikit-learn
  redistributes them under its BSD licence. ADR 0005 allows a permissive
  licence; CC BY 4.0 is one for data.

## 7. Validation (ADR 0016)

`validation/sqlearn/datasets/`, run by `just validate`:

- **Bundled:** each dataset equal to scikit-learn's `as_frame=True` frame,
  value for value (0 ULPs: the same decimal text read as DOUBLE).
- **Generators**, at 1,000,000 rows, against the distributions they promise,
  each within a bound set from the measurement and its standard error
  (several standard errors, so a correct generator does not fail by chance
  under a fixed seed): the uniform's and the normal's mean, variance and
  quantiles; `blobs`' per-centre means and spreads; `regression`'s target
  equal to `x @ coef + bias` within rounding when `noise=0`, and its residual
  spread equal to `noise` otherwise; `classification`'s class shares against
  `weights` and its flip rate; `customers`' missing shares and category
  shares.
- **Repeatability:** the same seed gives the same rows on 1 and on 8 threads,
  and the first 1,000 rows of a 1,000,000-row relation equal a 1,000-row one.

## 8. Done when

- The seven functions exist under `sq.datasets`, documented with an example
  each, refusing bad settings in the house form.
- SplitMix64 in SQL equals the Python reference bit for bit.
- A generated relation of 10**9 rows is created at once and its first rows
  come back at once; a pipeline learns from one of 10**7 rows under a 64 MB
  memory limit on one thread (the exact median's reach, #27).
- `examples/plot_tuning.py` takes its customers from `sq.datasets.customers`.
- The validation above passes; ADR 0045 records the contract; `check-mirror`
  asks a validation of every public datasets module.

## 9. Not in this area

Fetchers of real datasets (a later idea, ADR 0006); scikit-learn's other
generators (`make_moons`, `make_circles`, `make_friedman*`, sparse and
multilabel ones); text and image datasets; returning numpy arrays or a
`Bunch` (`sq.out` and the hand-over already turn a relation into those).

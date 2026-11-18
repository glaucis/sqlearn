---
type: adr
tags: [datasets, generators, bundled-data, random-numbers, splitmix64, api]
summary: "Records that sq.datasets returns DuckDB relations (target a column named target, last), keeps scikit-learn's setting names but for rows= and seed=, generates data in SQL from SplitMix64 keyed by (seed, row, stream) rather than hash() or random(), bundles iris, wine and breast cancer under CC BY 4.0, and fetches nothing."
related: [docs/specs/library-datasets.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/adr/0034-a-grouped-api.md, docs/adr/0043-repeatable-within-rounding.md]
---
# 0045: Datasets are relations built in SQL

Status: accepted (2026-11-10). Amended 2026-11-18 by
[ADR 0052](0052-meta-sqlearn.md). Spec:
[library datasets](../specs/library-datasets.md), sections 3 and 4.

## Context

sqlearn had no data of its own: its examples built data with numpy, and the
learning site needs data from its first page. scikit-learn's loaders return a
`Bunch` or an `(X, y)` pair of in-memory arrays, and its generators draw from
numpy's generator, which cannot be reproduced in SQL and cannot build data
larger than memory.

## Decision

- **A group, `sq.datasets`**, of functions named for what they give, without
  a `load_` or `make_` prefix ([ADR 0034](0034-a-grouped-api.md)'s short
  names).
- **Every function returns a `duckdb.DuckDBPyRelation`** on sqlearn's
  connection: what every sqlearn verb takes, lazy, and writable anywhere with
  DuckDB. A generated relation is a query, not a table: creating it computes no
  data row, and each use computes the same rows again. (The first generator
  call on a connection makes a small table of work tickets in `meta_sqlearn`,
  [ADR 0052](0052-meta-sqlearn.md).)
- **The target is a column named `target`**, last, as in scikit-learn's
  `as_frame=True` frame.
- **Settings keep scikit-learn's names** with two departures, both sqlearn's
  existing words: `rows=` for `n_samples` and `seed=` for `random_state` (an
  `int`, default 0). Bad settings are refused with a `SqlearnError` in the
  house form, where scikit-learn raises `ValueError`. An explicit
  `n_informative` above `n_features` in `regression` is clipped to
  `n_features`, with a `SqlearnWarning` (ADR 0046), where scikit-learn clips
  silently.
- **Random numbers are SplitMix64 in SQL.** Every value is a pure function of
  `(seed, row, stream)`: the key is
  `splitmix64(splitmix64(splitmix64(seed mod 2**64) ^ row) ^ stream)`,
  computed over `UBIGINT` with additions and multiplications in `UHUGEINT`
  taken modulo `2**64`. A uniform in `[0, 1)` is the key's top 53 bits times
  `2**-53`; a normal is Box-Muller over two uniforms of streams `2s` and
  `2s + 1`. Not DuckDB's `hash()`, which may change between versions, nor
  `random()`, which is not repeatable across threads. Each mixing step is a
  subquery over the previous one, so the SQL grows linearly with the columns.
- **Constants are drawn in Python** with a reference SplitMix64, equal to the
  SQL one bit for bit, at rows from `2**63` on, which no data row reaches: a
  handful of numbers (centres, coefficients, matrices), never data
  ([ADR 0002](0002-sql-on-duckdb-execution-engine.md)).
- **Iris, wine and breast cancer are bundled** as CSV, copied once from
  scikit-learn. They come from the UCI Machine Learning Repository under CC
  BY 4.0, a permissive licence for data
  ([ADR 0005](0005-runtime-dependencies.md)); a `README.md` beside them gives
  each one's source, creators and citation.
- **Nothing is fetched** ([ADR 0006](0006-local-and-offline.md)). A fetcher
  of larger datasets is a later idea, and would be a call whose name says it
  fetches.

## Consequences

- The same seed gives the same rows on every thread count, and a slice of a huge
  relation holds the same rows as the whole. Keys and uniforms are exact integer
  arithmetic, so they are the same bit for bit on every machine and DuckDB
  version. Normals go through `ln`, `cos` and `sqrt`, which libm does not
  promise to round alike on every platform or build: on one machine they are the
  same bit for bit (tested, SQL against Python), elsewhere the same within
  rounding ([ADR 0043](0043-repeatable-within-rounding.md)). A class derived
  from a normal by a threshold (`customers`' target) can differ across platforms
  on the rare row that lies on the threshold, since normals agree only within
  rounding there.
- The values are sqlearn's own: the same distributions as scikit-learn's,
  never the same numbers. Validation checks the distributions, not the draws.
- A normal costs two keys, a logarithm and a cosine per value: 10,000,000 rows
  of 20 normals summed take about 22.5 s on one thread (2026-11-10; the machine
  has 8 cores). DuckDB's `range()` is one thread, so the generators number their
  rows from work tickets in a stored table, which DuckDB shares between threads
  ([ADR 0052](0052-meta-sqlearn.md); `parallel=False` gives `range` and one
  thread); the low 64 bits are taken with a mask, the same value as `% 2**64`
  and about twelve times faster.
- A generated relation's rows come in row order while DuckDB's
  `preserve_insertion_order` is on (its default; sqlearn's predict refuses a
  connection with it off). The SQL has no `ORDER BY` by default, which would
  sort every row and lose the laziness: `limit` stops after the rows it needs.
  Each generator takes `ordered=True` to opt in: it sorts by the row number, so
  the rows come in row order whatever the setting, at the cost of a sort and of
  the laziness (#48).
- Code that expects scikit-learn's `Bunch` or `(X, y)` must read the relation
  instead (`rel.df()`, or a selection of columns).

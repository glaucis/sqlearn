---
type: adr
tags: [api, namespaces, steps, aggregates, scikit-learn, usability]
summary: "Records that sqlearn's public names live in groups named for what they hold (sq.impute, sq.scale, sq.agg, sq.cols...), each step group callable with shortcuts, instead of scikit-learn's class names and module map."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/adr/0013-learn-apply-train-predict.md, docs/specs/archived/library-preprocessing.md]
---
# 0034: A grouped API

Status: accepted (2026-11-05). A departure from
[ADR 0003](0003-scikit-learn-style-api.md), as that ADR requires. Amended by
[ADR 0039](0039-the-search-names-as-groups.md): `sq.Search` leaves the top
level, which gains the groups `sq.search` and `sq.folds`. Amended by
[ADR 0047](archived/0047-a-pipeline-saves-as-json.md): `sq.save` and
`sq.load` join the top level.

## Context

scikit-learn names a step by a class in a module the user must know
(`sklearn.impute.SimpleImputer`, `sklearn.preprocessing.RobustScaler`) and
picks its behaviour by a string setting (`strategy="median"`). Combining steps
needs `ColumnTransformer` and a `(name, step)` pair per step. sqlearn will
cover all of scikit-learn's preprocessing, so the names it picks now are the
names of hundreds of steps later. They should be easy to find, easy to
remember and short to type.

Every sqlearn step is a `Step` (learn if needed, then apply); a group of steps
is a way to find them, not a class hierarchy.

## Decision

- **The top level holds only what a pipeline is built with:** `sq.Pipeline`,
  `sq.Step`, `sq.Search`, `sq.set_config`, `sq.get_config`. Every other public
  name belongs to a group named for what it holds.
- **Step groups are named for what they do:** `sq.impute`, `sq.scale`,
  `sq.encode`, `sq.transform`, `sq.bin`, `sq.features`. A group is callable for
  the general form and holds shortcuts for the common presets; both build the
  same step:

  ```python
  sq.impute("age", value="median")
  sq.impute.median("age")  # the same step
  sq.scale("x", method="robust")
  sq.scale.robust("x")  # the same step
  sq.scale("x", center=sq.agg.median, spread=sq.agg.iqr)  # centre and spread chosen
  ```

- **Aggregates are a group, `sq.agg`**, and steps take them as values. A
  string naming an aggregate is shorthand for it (`"median"` is
  `sq.agg.median`); `sq.fn.const("median")` is the literal text.
- **The other groups:** `sq.cols` (selectors, callable: `sq.cols("a")`,
  `sq.cols.numeric()`), `sq.fn` (SQL functions for one's own steps),
  `sq.out` (`csv`, `json`, `parquet`), `sq.metrics`, `sq.errors`, `sq.store`.
  How the search's methods and folds are grouped is the model-selection
  spec's.
- **Columns come first, positionally:** a name, several names, a list, or a
  dict giving each column its own setting. `cols=` still takes a selector.
- **A pipeline is a plain list of steps;** a step's name is given only when
  wanted. `(name, step)` pairs still work.
- A page maps every scikit-learn name to sqlearn's.

## Consequences

- The core's names move before any release: `sq.Impute`, `sq.Scale`,
  `sq.OneHot`, `sq.Ordinal` become `sq.impute`, `sq.scale.standard`,
  `sq.encode.onehot`, `sq.encode.ordinal`; `strategy=` becomes `value=`;
  `sq.avg`, `sq.median`, `sq.stddev_pop`, `sq.count`, `sq.distinct_values`
  move into `sq.agg`; `sq.numeric`, `sq.string` into `sq.cols`; `sq.const`,
  `sq.is_missing` into `sq.fn`; `sq.out_*` into `sq.out`; `sq.accuracy` and
  `sq.Metric` into `sq.metrics`; the errors and warnings into `sq.errors`.
- An aggregate is validated once, and every step using it inherits that
  accuracy.
- A search covers a step's whole family with one setting
  (`params={"impute__value": ["mean", "median", 0]}`).
- Code written against scikit-learn's names needs the mapping page.

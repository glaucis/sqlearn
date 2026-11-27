---
type: question
tags: [scikit-learn, api-design, survey, sqlearn, preprocessing]
summary: "Open question on which parts of scikit-learn's API sqlearn should copy, adapt, or skip, based on earlier attempts."
related: [docs/specs, docs/questions/earlier-attempts/README.md]
mdindex: [type=1f5087, tags=0866c9, summary=fef2c5, related=d5023e]
---
# Which parts of scikit-learn's API do we copy, and where do we improve it?

Planned work: survey scikit-learn's API before designing sqlearn's components.

To cover:

- Estimator contract: `fit`, `transform`, `fit_transform`, `get_params` /
  `set_params`, `get_feature_names_out`, `set_output`.
- Composition: `Pipeline`, `make_pipeline`, `ColumnTransformer`,
  `FeatureUnion`.
- Preprocessing: scalers, encoders, imputers, discretizers.
- Known pain points worth improving (for example column handling and
  output-type confusion).

For each item, record one of: copy as is, adapt (with reason), or skip. Then
turn the results into specs in `docs/specs/` and ADRs for any departures.

## What the earlier attempts show

Evidence from the ten earlier attempts ([the map](earlier-attempts/README.md));
the survey itself is still to be done.

- **Renaming did not survive contact with use.** v0.4, the April repo,
  `sqlearn_000` and the war room used `learn`/`apply` and dropped
  `get_params`, `set_params` and `clone`, then added bridges back
  (`as_sklearn()`, `from_sklearn()`); serialisation had to guess parameter
  names stored as `_name`. The attempts that kept scikit-learn's names
  (`ducklearn`, `Tomosius/sqlearn`, `sql_learn_test`) needed none.
  `sql_learn_test` made the public API identical, signatures and fitted
  attribute names included, and changed the SQL where the two disagreed.
- **Departures every attempt made, each needing an ADR:** `y` as a column
  name and `fit` taking a data source (path, table, SQL) rather than `X, y`;
  the target never excluded from the default columns, so `Scale()` would
  scale it.
- **Column handling:** automatic routing by column type, a selector algebra
  and a `ColumnTransformer` equivalent (`Columns`) recurred; `Columns` was
  broken in v0.4 and `sqlearn_000`. Steps that return only the columns they
  change, with the rest passing through, worked in every attempt that had it.
- **Semantics to copy exactly**, each found wrong at least once:
  `StandardScaler`'s population standard deviation; `SimpleImputer`'s
  smallest value on a tie (`MODE(x ORDER BY x)`); interpolated quantiles
  (`QUANTILE_CONT`, not `QUANTILE`); RobustScaler's scale of 1 when the IQR is
  0; a constant column scaled to 0; `MissingIndicator` flagging only columns
  missing in fit; rounding half to even (`ROUND_EVEN`); NULL kept through
  clipping (`LEAST`/`GREATEST` drop it); unseen categories.
- **Output:** a numpy default built by fetching every row into Python was the
  opposite of larger-than-memory; result objects with `to_dict()` and
  `_repr_html_` and no plotting dependency were worth keeping.

---
type: question
tags: [scikit-learn, api-design, components, survey]
summary: "Open question on which parts of scikit-learn's API to copy, adapt, or skip when designing sqlearn's components."
related: [docs/specs/]
mdindex: [type=1f5087, tags=b27beb, summary=ecf7b6, related=06b3cc]
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

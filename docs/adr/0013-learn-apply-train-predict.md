---
type: adr
tags: [api, naming, learn, apply, train, predict, scikit-learn]
summary: "Records sqlearn's own verbs, one per task: learn and apply for steps that prepare data, train and predict for models; a departure from scikit-learn's fit and transform."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/adr/archived/0012-static-and-dynamic-steps.md, docs/questions/scikit-learn-api-survey.md]
---
# 0013: learn, apply, train and predict

Status: accepted (2026-11-04). A departure from
[ADR 0003](0003-scikit-learn-style-api.md), which asks for one.

## Context

scikit-learn uses `fit` for two different tasks: learning a step's values (a
scaler's mean) and training a model. `transform` and `predict` then return two
different kinds of output, and `fit_transform` joins two calls. sqlearn
separates the stage that prepares data from the stage that models it, and
wants each verb to say what it does.

Four earlier attempts used `learn` and `apply` and later added bridges back to
scikit-learn's names
([earlier attempts](../questions/archived/earlier-attempts/README.md)). sqlearn
accepts that risk: scikit-learn's names can be added later as thin aliases if
ever needed.

## Decision

One verb per task:

| Stage | Verb | What it does |
|---|---|---|
| preparing data | `learn` | learns values from the data (means, modes, categories) |
| | `apply` | applies the steps (imputers, scalers, encoders) with those values |
| modelling | `train` | trains a model on prepared data |
| | `predict` | uses the trained model to produce answers for each row |

A step that prepares data (imputers, scalers, encoders, PCA) has `learn` and
`apply`. A model (regression, classification, clustering) has `train` and
`predict`. A pipeline without a model has `learn` and `apply`; a pipeline that
ends in a model has `train`, which learns and applies its steps and then trains
the model, and `predict`, which applies the steps with the values already
learned and then predicts.

Everything else in ADR 0003 stands: composition into pipelines,
hyperparameters set in `__init__`, learned state in attributes ending in `_`.

## Consequences

- Docs, lessons and errors use these four verbs; `fit`, `transform` and
  `fit_transform` do not appear in sqlearn's API.
- If interoperability with scikit-learn's tools is wanted later, `fit` and
  `transform` (or `predict`) can be added as aliases; those tools also need
  `get_params`, `set_params` and `clone`, so steps keep their parameters in a
  form that makes those easy to add.
- Names for further model outputs (probabilities, scores) are decided with the
  models (overview 3.3).

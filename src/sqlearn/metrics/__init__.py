"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, MissingClassError, accuracy
from sqlearn.metrics.classification import ClassificationMetric, f1, precision, recall
from sqlearn.metrics.probability import log_loss, roc_auc
from sqlearn.metrics.regression import mae, r2, rmse

__all__ = [
    "ClassificationMetric",
    "Metric",
    "MissingClassError",
    "accuracy",
    "f1",
    "log_loss",
    "mae",
    "precision",
    "r2",
    "recall",
    "rmse",
    "roc_auc",
]

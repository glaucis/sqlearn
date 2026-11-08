"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, MissingClassError, accuracy
from sqlearn.metrics.probability import log_loss, roc_auc
from sqlearn.metrics.regression import mae, r2, rmse

__all__ = [
    "Metric",
    "MissingClassError",
    "accuracy",
    "log_loss",
    "mae",
    "r2",
    "rmse",
    "roc_auc",
]

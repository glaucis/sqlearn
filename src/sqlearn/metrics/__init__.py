"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, MissingClassError, accuracy
from sqlearn.metrics.classification import (
    ClassificationMetric,
    f1,
    fbeta,
    precision,
    recall,
)
from sqlearn.metrics.curves import precision_recall_curve, roc_curve
from sqlearn.metrics.probability import log_loss, roc_auc
from sqlearn.metrics.regression import mae, r2, rmse
from sqlearn.metrics.tables import classification_report, confusion_matrix

__all__ = [
    "ClassificationMetric",
    "Metric",
    "MissingClassError",
    "accuracy",
    "classification_report",
    "confusion_matrix",
    "f1",
    "fbeta",
    "log_loss",
    "mae",
    "precision",
    "precision_recall_curve",
    "r2",
    "recall",
    "rmse",
    "roc_auc",
    "roc_curve",
]

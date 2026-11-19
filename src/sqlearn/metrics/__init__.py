"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, MissingClassError, accuracy
from sqlearn.metrics.balanced import CountMetric, balanced_accuracy, mcc
from sqlearn.metrics.classification import (
    ClassificationMetric,
    f1,
    fbeta,
    precision,
    recall,
)
from sqlearn.metrics.curves import precision_recall_curve, roc_curve
from sqlearn.metrics.probability import (
    AveragePrecision,
    BrierScore,
    average_precision,
    brier,
    log_loss,
    roc_auc,
)
from sqlearn.metrics.regression import (
    explained_variance,
    mae,
    mape,
    max_error,
    median_absolute_error,
    mse,
    r2,
    rmse,
)
from sqlearn.metrics.tables import classification_report, confusion_matrix

__all__ = [
    "AveragePrecision",
    "BrierScore",
    "ClassificationMetric",
    "CountMetric",
    "Metric",
    "MissingClassError",
    "accuracy",
    "average_precision",
    "balanced_accuracy",
    "brier",
    "classification_report",
    "confusion_matrix",
    "explained_variance",
    "f1",
    "fbeta",
    "log_loss",
    "mae",
    "mape",
    "max_error",
    "mcc",
    "median_absolute_error",
    "mse",
    "precision",
    "precision_recall_curve",
    "r2",
    "recall",
    "rmse",
    "roc_auc",
    "roc_curve",
]

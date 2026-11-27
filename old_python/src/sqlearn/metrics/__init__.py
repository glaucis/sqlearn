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
    LogError,
    PinballLoss,
    TweedieDeviance,
    d2_absolute_error,
    d2_pinball,
    d2_tweedie,
    explained_variance,
    gamma_deviance,
    mae,
    mape,
    max_error,
    median_absolute_error,
    mse,
    msle,
    pinball_loss,
    poisson_deviance,
    r2,
    rmse,
    rmsle,
    tweedie_deviance,
)
from sqlearn.metrics.tables import classification_report, confusion_matrix

__all__ = [
    "AveragePrecision",
    "BrierScore",
    "ClassificationMetric",
    "CountMetric",
    "LogError",
    "Metric",
    "MissingClassError",
    "PinballLoss",
    "TweedieDeviance",
    "accuracy",
    "average_precision",
    "balanced_accuracy",
    "brier",
    "classification_report",
    "confusion_matrix",
    "d2_absolute_error",
    "d2_pinball",
    "d2_tweedie",
    "explained_variance",
    "f1",
    "fbeta",
    "gamma_deviance",
    "log_loss",
    "mae",
    "mape",
    "max_error",
    "mcc",
    "median_absolute_error",
    "mse",
    "msle",
    "pinball_loss",
    "poisson_deviance",
    "precision",
    "precision_recall_curve",
    "r2",
    "recall",
    "rmse",
    "rmsle",
    "roc_auc",
    "roc_curve",
    "tweedie_deviance",
]

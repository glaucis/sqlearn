"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, accuracy
from sqlearn.metrics.regression import mae, r2, rmse

__all__ = ["Metric", "accuracy", "mae", "r2", "rmse"]

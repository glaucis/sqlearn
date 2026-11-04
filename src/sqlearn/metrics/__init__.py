"""Metrics, computed as one aggregate query in DuckDB.

Examples
--------
>>> from sqlearn.metrics import accuracy
>>> accuracy.name
'accuracy'
"""

from sqlearn.metrics.accuracy import Metric, accuracy

__all__ = ["Metric", "accuracy"]

"""Feature selection: keep the columns that tell a model something.

Examples
--------
>>> from sqlearn.feature_selection import VarianceThreshold
>>> VarianceThreshold().threshold
0.0
"""

from sqlearn.feature_selection.variance import VarianceThreshold

__all__ = ["VarianceThreshold"]

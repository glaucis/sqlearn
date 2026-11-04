"""Preprocessing steps: fill gaps and put columns on a common scale.

Examples
--------
>>> from sqlearn.preprocessing import Impute, Scale
>>> Impute().strategy, Scale().keep
('median', False)
"""

from sqlearn.preprocessing.impute import Impute
from sqlearn.preprocessing.scale import Scale

__all__ = ["Impute", "Scale"]

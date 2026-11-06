"""Preprocessing steps: fill gaps and put columns on a common scale.

Examples
--------
>>> from sqlearn.preprocessing import Impute, Scale
>>> Impute().value, Scale().method
(sq.agg.median, 'standard')
"""

from sqlearn.preprocessing.impute import Impute
from sqlearn.preprocessing.onehot import OneHot
from sqlearn.preprocessing.ordinal import Ordinal
from sqlearn.preprocessing.scale import Scale

__all__ = ["Impute", "OneHot", "Ordinal", "Scale"]

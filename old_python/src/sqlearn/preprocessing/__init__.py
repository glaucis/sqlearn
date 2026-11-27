"""Preprocessing steps: fill gaps, scale, encode and bin columns.

Examples
--------
>>> from sqlearn.preprocessing import Impute, Scale
>>> Impute().value, Scale().method
(sq.agg.median, 'standard')
"""

from sqlearn.preprocessing.bin import Bin, Binarize
from sqlearn.preprocessing.features import Polynomial, Spline
from sqlearn.preprocessing.impute import Impute
from sqlearn.preprocessing.onehot import OneHot
from sqlearn.preprocessing.ordinal import Ordinal
from sqlearn.preprocessing.scale import Normalize, Scale
from sqlearn.preprocessing.target import TargetEncoder
from sqlearn.preprocessing.transform import Transform

__all__ = [
    "Bin",
    "Binarize",
    "Impute",
    "Normalize",
    "OneHot",
    "Ordinal",
    "Polynomial",
    "Scale",
    "Spline",
    "TargetEncoder",
    "Transform",
]

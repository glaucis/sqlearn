"""Model selection: the search over settings, its methods and its folds.

Examples
--------
>>> from sqlearn.model_selection import Grid, KFold
>>> Grid().knows_all, KFold().n
(True, 5)
"""

from sqlearn.model_selection.defaults import DEFAULT_SPACES
from sqlearn.model_selection.folds import (
    Folds,
    Grouped,
    Holdout,
    KFold,
    Stratified,
    TimeSplit,
)
from sqlearn.model_selection.groups import FoldsGroup, SearchGroup
from sqlearn.model_selection.methods import (
    Grid,
    Method,
    Optuna,
    Random,
    Range,
    range,
)
from sqlearn.model_selection.search import Search

__all__ = [
    "DEFAULT_SPACES",
    "Folds",
    "FoldsGroup",
    "Grid",
    "Grouped",
    "Holdout",
    "KFold",
    "Method",
    "Optuna",
    "Random",
    "Range",
    "Search",
    "SearchGroup",
    "Stratified",
    "TimeSplit",
    "range",
]

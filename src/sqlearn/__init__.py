"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib.metadata import version

from sqlearn import errors, fn, metrics, out, store
from sqlearn._config import get_config, set_config
from sqlearn._expr import avg, count, distinct_values, median, stddev_pop
from sqlearn._model import Model
from sqlearn._output import Output
from sqlearn._pipeline import Pipeline, make_pipeline
from sqlearn._selectors import cols
from sqlearn._step import Learned, Step
from sqlearn.model_selection import Grid, KFold, Search, range
from sqlearn.preprocessing import Impute, OneHot, Ordinal, Scale

__all__ = [
    "Grid",
    "Impute",
    "KFold",
    "Learned",
    "Model",
    "OneHot",
    "Ordinal",
    "Output",
    "Pipeline",
    "Scale",
    "Search",
    "Step",
    "__version__",
    "avg",
    "cols",
    "count",
    "distinct_values",
    "errors",
    "fn",
    "get_config",
    "make_pipeline",
    "median",
    "metrics",
    "out",
    "range",
    "set_config",
    "stddev_pop",
    "store",
]

__version__: str = version("sqlearn")

"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib.metadata import version

from sqlearn import agg, errors, fn, metrics, out, store
from sqlearn._config import get_config, set_config
from sqlearn._model import Model
from sqlearn._output import Output
from sqlearn._pipeline import Pipeline
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
    "agg",
    "cols",
    "errors",
    "fn",
    "get_config",
    "metrics",
    "out",
    "range",
    "set_config",
    "store",
]

__version__: str = version("sqlearn")

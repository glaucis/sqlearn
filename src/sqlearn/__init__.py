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
from sqlearn.preprocessing._encode import encode
from sqlearn.preprocessing.impute import impute
from sqlearn.preprocessing.scale import scale

__all__ = [
    "Grid",
    "KFold",
    "Learned",
    "Model",
    "Output",
    "Pipeline",
    "Search",
    "Step",
    "__version__",
    "agg",
    "cols",
    "encode",
    "errors",
    "fn",
    "get_config",
    "impute",
    "metrics",
    "out",
    "range",
    "scale",
    "set_config",
    "store",
]

__version__: str = version("sqlearn")

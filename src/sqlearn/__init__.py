"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib import metadata as _metadata

from sqlearn import agg, datasets, errors, fn, metrics, out, store
from sqlearn._config import get_config, set_config
from sqlearn._model import Model
from sqlearn._output import Output
from sqlearn._pipeline import Pipeline
from sqlearn._saving.files import load, save
from sqlearn._selectors import cols
from sqlearn._step import Learned, Step
from sqlearn.model_selection.groups import folds, search
from sqlearn.preprocessing._encode import encode
from sqlearn.preprocessing.bin import bin
from sqlearn.preprocessing.features import features
from sqlearn.preprocessing.impute import impute
from sqlearn.preprocessing.scale import scale
from sqlearn.preprocessing.transform import transform

__all__ = [
    "Learned",
    "Model",
    "Output",
    "Pipeline",
    "Step",
    "__version__",
    "agg",
    "bin",
    "cols",
    "datasets",
    "encode",
    "errors",
    "features",
    "fn",
    "folds",
    "get_config",
    "impute",
    "load",
    "metrics",
    "out",
    "save",
    "scale",
    "search",
    "set_config",
    "store",
    "transform",
]

__version__: str = _metadata.version("sqlearn")

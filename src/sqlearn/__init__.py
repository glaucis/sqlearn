"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib import metadata as _metadata

# The start-up check, before anything imports duckdb: the engine is compiled
# into DuckDB's binary, and the official duckdb has none (ADR 0061).
import _duckdb

from sqlearn import _native

_native.load(_duckdb.__file__)

from sqlearn import agg, errors, explore, fn, metrics, out, store
from sqlearn._config import get_config, set_config
from sqlearn._model import Model
from sqlearn._output import Output
from sqlearn._pipeline import Pipeline
from sqlearn._saving.files import load, save
from sqlearn._selectors import cols
from sqlearn._step import Learned, Step
from sqlearn.decomposition._decompose import decompose
from sqlearn.feature_selection._select import select
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
    "decompose",
    "encode",
    "errors",
    "explore",
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
    "select",
    "set_config",
    "store",
    "transform",
    "version",
]

__version__: str = _metadata.version("sqlearn")


def version() -> str:
    """Return what this sqlearn was built as, in one line.

    The engine answers it: sqlearn's version, DuckDB's version and commit,
    the C++ compiler and the build type. ``SELECT sqlearn_version()`` gives
    the same line in any DuckDB database.

    Returns
    -------
    str
        ``sqlearn <version>, DuckDB <version> (<commit>), <compiler>,
        <build type>``, the commit cut to its first ten digits.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.version()  # doctest: +ELLIPSIS
    'sqlearn ..., DuckDB ... (...), ...'
    """
    return _native.describe()

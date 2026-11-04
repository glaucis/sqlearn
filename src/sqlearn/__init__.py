"""Machine learning computed inside DuckDB, on data larger than memory.

Examples
--------
>>> import sqlearn
>>> isinstance(sqlearn.__version__, str)
True
"""

from importlib.metadata import version

from sqlearn._config import get_config, set_config
from sqlearn._errors import (
    DefaultsUsedWarning,
    InternalError,
    SqlearnError,
    SqlearnWarning,
    StepError,
)
from sqlearn._expr import (
    avg,
    const,
    count,
    distinct_values,
    is_missing,
    median,
    stddev_pop,
)
from sqlearn._model import Model
from sqlearn._output import Output, out_csv, out_json, out_parquet
from sqlearn._pipeline import Pipeline, make_pipeline
from sqlearn._selectors import cols, numeric, string
from sqlearn._step import Learned, Step
from sqlearn.metrics import Metric, accuracy
from sqlearn.preprocessing import Impute, OneHot, Ordinal, Scale

__all__ = [
    "DefaultsUsedWarning",
    "Impute",
    "InternalError",
    "Learned",
    "Metric",
    "Model",
    "OneHot",
    "Ordinal",
    "Output",
    "Pipeline",
    "Scale",
    "SqlearnError",
    "SqlearnWarning",
    "Step",
    "StepError",
    "__version__",
    "accuracy",
    "avg",
    "cols",
    "const",
    "count",
    "distinct_values",
    "get_config",
    "is_missing",
    "make_pipeline",
    "median",
    "numeric",
    "out_csv",
    "out_json",
    "out_parquet",
    "set_config",
    "stddev_pop",
    "string",
]

__version__: str = version("sqlearn")

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

__all__ = [
    "DefaultsUsedWarning",
    "InternalError",
    "SqlearnError",
    "SqlearnWarning",
    "StepError",
    "__version__",
    "avg",
    "const",
    "count",
    "distinct_values",
    "get_config",
    "is_missing",
    "median",
    "set_config",
    "stddev_pop",
]

__version__: str = version("sqlearn")

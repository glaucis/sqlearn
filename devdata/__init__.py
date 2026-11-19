"""Datasets: sample data and generators, each a DuckDB relation built in SQL.

Every function returns a relation on sqlearn's connection, its target a
column named ``target``, last (ADR 0045).

Examples
--------
>>> import sqlearn as sq
>>> devdata.__name__
'devdata'
"""

from devdata.bundled import breast_cancer, iris, wine
from devdata.generated import blobs, classification, customers, regression

__all__ = [
    "blobs",
    "breast_cancer",
    "classification",
    "customers",
    "iris",
    "regression",
    "wine",
]

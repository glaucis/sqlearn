"""Datasets: sample data and generators, each a DuckDB relation built in SQL.

Every function returns a relation on sqlearn's connection, its target a
column named ``target``, last (ADR 0045).

Examples
--------
>>> import sqlearn as sq
>>> sq.datasets.__name__
'sqlearn.datasets'
"""

from sqlearn.datasets.bundled import breast_cancer, iris, wine

__all__ = ["breast_cancer", "iris", "wine"]

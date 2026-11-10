"""The bundled datasets: iris, wine and breast cancer, read from CSV files.

The files sit beside this module in ``data/`` with their sources and licence
(CC BY 4.0, see ``data/README.md``). Each function returns a relation over
its file, read on use, so nothing is loaded until a query asks for it.
"""

import csv
from importlib import resources

import duckdb

from sqlearn._config import connection

__all__ = ["breast_cancer", "iris", "wine"]


def _read(name: str) -> duckdb.DuckDBPyRelation:
    """Return the bundled CSV `name` as a relation: DOUBLE features, BIGINT target."""
    path = resources.files("sqlearn.datasets") / "data" / f"{name}.csv"
    with path.open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    columns = dict.fromkeys(header[:-1], "DOUBLE") | {header[-1]: "BIGINT"}
    return connection().read_csv(str(path), header=True, columns=columns)


def iris() -> duckdb.DuckDBPyRelation:
    """Return Fisher's iris data: 150 flowers, 4 measurements, 3 species.

    The rows of scikit-learn's ``load_iris(as_frame=True).frame``, in the same
    order with the same column names: the four measurements in centimetres
    (``DOUBLE``), then ``target`` (``BIGINT``), the species code 0, 1 or 2
    (setosa, versicolor, virginica), 50 rows each. From the UCI Machine
    Learning Repository, licensed CC BY 4.0.

    Returns
    -------
    duckdb.DuckDBPyRelation
        The dataset, on sqlearn's connection.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.iris()
    >>> rel.columns[-1], rel.count("*").fetchall()[0][0]
    ('target', 150)
    """
    return _read("iris")


def wine() -> duckdb.DuckDBPyRelation:
    """Return the wine recognition data: 178 wines, 13 analyses, 3 cultivars.

    The rows of scikit-learn's ``load_wine(as_frame=True).frame``, in the same
    order with the same column names: thirteen chemical measurements
    (``DOUBLE``), then ``target`` (``BIGINT``), the cultivar code 0, 1 or 2
    (59, 71 and 48 rows). From the UCI Machine Learning Repository, licensed
    CC BY 4.0.

    Returns
    -------
    duckdb.DuckDBPyRelation
        The dataset, on sqlearn's connection.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.wine()
    >>> rel.columns[0], rel.count("*").fetchall()[0][0]
    ('alcohol', 178)
    """
    return _read("wine")


def breast_cancer() -> duckdb.DuckDBPyRelation:
    """Return the Wisconsin diagnostic breast cancer data: 569 tumours, 30 features.

    The rows of scikit-learn's ``load_breast_cancer(as_frame=True).frame``, in
    the same order with the same column names: thirty measurements of cell
    nuclei (``DOUBLE``), then ``target`` (``BIGINT``), 0 for malignant (212
    rows) and 1 for benign (357). From the UCI Machine Learning Repository,
    licensed CC BY 4.0.

    Returns
    -------
    duckdb.DuckDBPyRelation
        The dataset, on sqlearn's connection.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.breast_cancer()
    >>> rel.columns[0], rel.count("*").fetchall()[0][0]
    ('mean radius', 569)
    """
    return _read("breast_cancer")

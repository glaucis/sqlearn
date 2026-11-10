"""The checks every label metric makes before it scores (spec §4).

`check_labels` refuses what scikit-learn refuses in a target and a
prediction column, from one aggregate over the relation. A metric that wants
its own aggregate computed in the same pass gives it to `check_labels_with`.
"""

from collections.abc import Sequence
from typing import Any

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import const

__all__ = ["check_labels", "check_labels_with"]

_FLOATS = frozenset({"FLOAT", "DOUBLE"})

_NUMBERS = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        *_FLOATS,
    }
)

_COMPARISON_ERRORS = (duckdb.ConversionException, duckdb.BinderException)
"""The DuckDB errors that say two columns cannot be compared.

Any other DuckDB error (out of memory, an interrupt, a failing aggregate)
passes through as DuckDB raised it.
"""


def _first_line(exc: duckdb.Error) -> str:
    """Return the first line of DuckDB's message, without its SQL and caret."""
    return str(exc).split("\n", 1)[0].rstrip()


def _isnan(x: Expression) -> Expression:
    return duckdb.FunctionExpression("isnan", x)


def _count(x: Expression) -> Expression:
    """Count the non-NULL values of `x`, NaN among them (unlike `sq.agg.count`)."""
    return duckdb.FunctionExpression("count", x)


def _column_types(
    name: str, rel: duckdb.DuckDBPyRelation, columns: Sequence[str]
) -> dict[str, str]:
    """Return each column's type, refusing a column not in the relation."""
    names = list(rel.columns)
    types = {n: str(t) for n, t in zip(names, rel.types, strict=True)}
    for column in columns:
        if column not in types:
            msg = (
                f"{name} cannot be computed: column {column!r} is "
                f"not in the relation (columns: {names}). Pass the name "
                "of an existing column."
            )
            raise SqlearnError(msg)
    return types


def _noun(column: str, target: str, proba: bool) -> str:
    """Name what a column holds: a label, or a probability."""
    return "probability" if proba and column != target else "label"


def _refuse_gaps(
    name: str,
    target: str,
    columns: Sequence[str],
    floats: Sequence[str],
    total: int,
    seen: Sequence[int],
    nan_counts: Sequence[int],
    *,
    proba: bool = False,
) -> None:
    """Refuse no rows, and a column holding NULL or NaN, from their counts."""
    if total == 0:
        msg = (
            f"{name} cannot be computed: the relation has no rows. "
            "A score needs at least one row; check the data was not "
            "filtered away."
        )
        raise SqlearnError(msg)
    for column, n_seen in zip(columns, seen, strict=True):
        if n_seen != total:
            msg = (
                f"{name} cannot be computed: column {column!r} has "
                f"{total - n_seen} NULL of {total} rows. A missing "
                f"{_noun(column, target, proba)} has no right answer; "
                "drop or fill those rows first."
            )
            raise SqlearnError(msg)
    for column, n_nan in zip(floats, nan_counts, strict=True):
        if n_nan:
            msg = (
                f"{name} cannot be computed: column {column!r} has "
                f"{n_nan} NaN of {total} rows. A NaN "
                f"{_noun(column, target, proba)} has no right answer; "
                "drop or fill those rows first."
            )
            raise SqlearnError(msg)


def _isinf(x: Expression) -> Expression:
    return duckdb.FunctionExpression("isinf", x)


def _is_nested(dtype: str) -> bool:
    """Whether a DuckDB type holds a LIST, ARRAY, STRUCT, MAP or UNION."""
    return dtype.endswith("]") or dtype.startswith(("STRUCT", "MAP", "UNION"))


def _is_text(dtype: str) -> bool:
    """Whether a DuckDB type holds text labels."""
    return dtype.startswith(("VARCHAR", "ENUM"))


def _kind(dtype: str) -> str:
    """Name the kind of label a column type holds: text, number or its type."""
    if _is_text(dtype):
        return "text"
    if dtype in _NUMBERS or dtype.startswith("DECIMAL"):
        return "number"
    return dtype


def check_labels(
    name: str, rel: duckdb.DuckDBPyRelation, target: str, prediction: str
) -> dict[str, str]:
    """Refuse labels scikit-learn refuses, and return each column's type.

    Refused: a missing column, no rows, NULL, NaN, infinity, list or record
    labels, columns DuckDB cannot compare, text labels against numbers, and
    numbers that are not whole.

    Parameters
    ----------
    name : str
        The metric's name, for the message.
    rel : duckdb.DuckDBPyRelation
        The rows.
    target : str
        The target column.
    prediction : str
        The prediction column.

    Returns
    -------
    dict
        Each of the two columns' DuckDB type name.

    Raises
    ------
    SqlearnError
        If a label check fails.

    Examples
    --------
    >>> import duckdb
    >>> check_labels("accuracy", duckdb.sql("SELECT 1 AS y, 1 AS p"), "y", "p")
    {'y': 'INTEGER', 'p': 'INTEGER'}
    """
    return check_labels_with(name, rel, target, prediction, ())[0]


def check_labels_with(
    name: str,
    rel: duckdb.DuckDBPyRelation,
    target: str,
    prediction: str,
    extra: Sequence[Expression],
) -> tuple[dict[str, str], list[Any]]:
    """Check the labels in the same aggregate that computes `extra`.

    Parameters
    ----------
    name : str
        The metric's name, for the message.
    rel : duckdb.DuckDBPyRelation
        The rows.
    target : str
        The target column.
    prediction : str
        The prediction column.
    extra : sequence of Expression
        Aggregates to compute in the same pass over `rel`.

    Returns
    -------
    tuple
        Each column's type, and the value of each `extra` aggregate.

    Raises
    ------
    SqlearnError
        If a label check fails, or DuckDB cannot compare the two columns.
    duckdb.Error
        Any other DuckDB error over the aggregate, `extra`'s among them,
        passes through as DuckDB raised it.

    Examples
    --------
    >>> import duckdb
    >>> from duckdb import ColumnExpression
    >>> rel = duckdb.sql("SELECT 1 AS y, 1 AS p")
    >>> types, (rows,) = check_labels_with(
    ...     "accuracy",
    ...     rel,
    ...     "y",
    ...     "p",
    ...     [duckdb.FunctionExpression("count", ColumnExpression("y"))],
    ... )
    >>> rows
    1
    """
    columns = [target, prediction]
    types = _column_types(name, rel, columns)
    for c in columns:
        if _is_nested(types[c]):
            msg = (
                f"{name} cannot be computed: column {c!r} has the type "
                f"{types[c]}, which holds lists or records, not class "
                "labels. scikit-learn refuses such labels too. Fix: pass "
                "a column of one number or one text per row."
            )
            raise SqlearnError(msg)
    if _is_text(types[target]) != _is_text(types[prediction]):
        msg = (
            f"{name} cannot be computed: column {target!r} "
            f"({types[target]}) holds {_kind(types[target])} labels and "
            f"column {prediction!r} ({types[prediction]}) "
            f"{_kind(types[prediction])} labels, so no label can match. "
            "scikit-learn refuses such a mix too. Fix: cast one so both "
            "hold the same kind of label."
        )
        raise SqlearnError(msg)
    floats = [c for c in columns if types[c] in _FLOATS]
    fractional = [
        c for c in columns if types[c] in _FLOATS or types[c].startswith("DECIMAL")
    ]
    column = ColumnExpression
    floor = duckdb.FunctionExpression
    # Every count, named, so a check is added without shifting the others.
    counts: dict[str, Expression] = {"rows": _count(const(1))}
    for c in columns:
        counts[f"seen {c}"] = _count(column(c))
    for c in floats:
        counts[f"nan {c}"] = _count(
            duckdb.CaseExpression(_isnan(column(c)), const(1)),
        )
    for c in floats:
        counts[f"inf {c}"] = _count(
            duckdb.CaseExpression(_isinf(column(c)), const(1)),
        )
    # Compared in the pass, so two columns DuckDB cannot compare fail here.
    counts["comparable"] = _count(
        duckdb.CaseExpression(column(target) == column(prediction), const(1)),
    )
    for c in fractional:
        counts[f"fraction {c}"] = _count(
            duckdb.CaseExpression(column(c) != floor("floor", column(c)), const(1)),
        )
    try:
        row = rel.aggregate([*counts.values(), *extra]).fetchall()[0]
    except _COMPARISON_ERRORS as exc:
        msg = (
            f"{name} cannot be computed: DuckDB cannot compare column "
            f"{target!r} ({types[target]}) with column {prediction!r} "
            f"({types[prediction]}): {_first_line(exc)} Fix: cast one so both "
            "hold the same kind of label."
        )
        raise SqlearnError(msg) from exc
    got = dict(zip(counts, row, strict=False))
    _refuse_gaps(
        name,
        target,
        columns,
        floats,
        got["rows"],
        [got[f"seen {c}"] for c in columns],
        [got[f"nan {c}"] for c in floats],
    )
    for c in floats:
        if got[f"inf {c}"]:
            msg = (
                f"{name} cannot be computed: column {c!r} has "
                f"{got[f'inf {c}']} infinite of {got['rows']} rows. "
                "scikit-learn refuses infinity too, since it is not a class "
                "label. Fix: drop or replace those rows first."
            )
            raise SqlearnError(msg)
    for c in fractional:
        if got[f"fraction {c}"]:
            msg = (
                f"{name} cannot be computed: column {c!r} has "
                f"{got[f'fraction {c}']} of {got['rows']} rows that are not "
                "whole numbers, so it holds continuous values, not class "
                "labels. scikit-learn refuses continuous values here too. Fix: "
                "score a classifier's predict, or a regression with "
                "sq.metrics.rmse, mae or r2."
            )
            raise SqlearnError(msg)
    return types, list(row[len(counts) :])

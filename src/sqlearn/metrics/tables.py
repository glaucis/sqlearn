"""Metrics that are tables: the confusion matrix (spec §4, ADR 0049).

Each is a function over a relation that hands back a lazy DuckDB relation,
or what ``out=`` names, not a `Metric`: a table cannot rank a search.
"""

import warnings
from typing import Any

import duckdb

from sqlearn._errors import InternalError, SqlearnError, SqlearnWarning
from sqlearn._expr import quote
from sqlearn._output import Output, to_output
from sqlearn.metrics._labels import check_labels

__all__ = ["confusion_matrix"]

_NORMALIZE = (None, "true", "pred", "all")


_SOURCE = "_sqlearn_rows"
"""The name the rows go by inside the SQL of a table metric."""


def _pairs(target: str, prediction: str) -> str:
    """Return the SQL of the two label columns, as ``t`` and ``p``."""
    return f"SELECT {quote(target)} AS t, {quote(prediction)} AS p FROM {_SOURCE}"


def _select(rel: duckdb.DuckDBPyRelation, sql: str) -> duckdb.DuckDBPyRelation:
    """Return the relation of a SELECT over `rel`, which the SQL names as _SOURCE."""
    got = rel.query(_SOURCE, sql)
    if got is None:  # a SELECT always gives a relation
        msg = "DuckDB gave no relation for a SELECT"
        raise InternalError(msg)
    return got


def _label_rows(
    rel: duckdb.DuckDBPyRelation, target: str, prediction: str
) -> list[tuple[object, str]]:
    """Return each label and its text, sorted: the labels of both columns.

    One query. The two columns are stacked, so DuckDB gives them one type
    and an INTEGER 1 meeting a DOUBLE 1.0 is one label.
    """
    sql = (
        f"WITH pairs AS ({_pairs(target, prediction)}) "
        "SELECT label, CAST(label AS VARCHAR) FROM ("
        "SELECT DISTINCT label FROM ("
        "SELECT t AS label FROM pairs UNION ALL SELECT p FROM pairs)) "
        "ORDER BY label"
    )
    return [(a, b) for a, b in _select(rel, sql).fetchall()]


def _labels_of(
    rel: duckdb.DuckDBPyRelation, target: str, prediction: str
) -> list[object]:
    """Return the sorted labels of the target and the prediction, one query."""
    return [label for label, _ in _label_rows(rel, target, prediction)]


def confusion_matrix(
    rel: duckdb.DuckDBPyRelation,
    target: str,
    prediction: str = "prediction",
    *,
    normalize: str | None = None,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401  (the form `out` names)
    """Count the rows of each true label by predicted label.

    As scikit-learn 1.9.1's ``confusion_matrix`` without ``labels=`` and
    ``sample_weight=``: one row per label, one column per label, both the
    labels of the target and the prediction sorted. The first column holds
    the true label, named as `target`; the others are named by the label's
    text. The matrix is one grouped count in DuckDB (ADR 0049).

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The rows, holding a target and a prediction column.
    target : str
        The column of true labels.
    prediction : str, default "prediction"
        The column of predicted labels.
    normalize : {None, "true", "pred", "all"}, default None
        Divide each count by its row total (``"true"``), column total
        (``"pred"``) or the grand total (``"all"``). Cells are then `DOUBLE`,
        and 0 where the total is 0.
    out : {"pandas", "polars", "numpy", "arrow"} or Output or None
        What to hand back; None is a lazy relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        The matrix, or it as `out` names.

    Raises
    ------
    SqlearnError
        If `normalize` is unknown, a label is named as `target`, or the
        labels fail precision's checks (no rows, NULL, NaN, infinity,
        continuous or mixed-kind labels).

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0), (1, 0), (1, 1)) t(y, prediction)"
    ... )
    >>> sq.metrics.confusion_matrix(rel, "y").fetchall()
    [(0, 1, 0), (1, 1, 1)]
    """
    if normalize not in _NORMALIZE:
        msg = (
            f"confusion_matrix cannot be computed: normalize={normalize!r} "
            "is not a normalisation. Why: scikit-learn takes None, 'true', "
            "'pred' or 'all'. Fix: pass one of them."
        )
        raise SqlearnError(msg)
    check_labels("confusion_matrix", rel, target, prediction)
    rows = _label_rows(rel, target, prediction)
    for label, text in rows:
        if text == "":
            msg = (
                "confusion_matrix cannot be computed: a label is empty text. "
                "Why: each label is a column named by its text, and DuckDB "
                "cannot name a column with no text. Fix: replace the empty "
                "label first, for example with 'none'."
            )
            raise SqlearnError(msg)
        if text == target:
            msg = (
                f"confusion_matrix cannot be computed: the label {label!r} "
                f"has the same text as the target column {target!r}. Why: "
                "each label is a column named by its text, beside the "
                f"column {target!r} of true labels. Fix: rename the target "
                "column, or the label."
            )
            raise SqlearnError(msg)
    if len(rows) == 1:
        warnings.warn(
            "A single label was found in the target and the prediction. "
            "For the confusion matrix to have the correct shape there "
            "should be a label for every class. Fix: this is the 1 by 1 "
            "matrix of the one label; check the data holds every class.",
            SqlearnWarning,
            stacklevel=2,
        )
    names = [quote(text) for _, text in rows]
    cells = ", ".join(
        f"CAST(coalesce(sum(CASE WHEN pi = {i} THEN n END), 0) AS BIGINT) AS {name}"
        for i, name in enumerate(names)
    )
    counted = (
        f"WITH pairs AS ({_pairs(target, prediction)}), "
        "labels AS (SELECT label, row_number() OVER (ORDER BY label) - 1 "
        "AS idx FROM (SELECT DISTINCT label FROM ("
        "SELECT t AS label FROM pairs UNION ALL SELECT p FROM pairs))), "
        "counts AS (SELECT lt.idx AS ti, lp.idx AS pi, count(*) AS n "
        "FROM pairs JOIN labels lt ON pairs.t = lt.label "
        "JOIN labels lp ON pairs.p = lp.label GROUP BY ALL) "
        f"SELECT labels.label AS {quote(target)}, {cells} "
        "FROM labels LEFT JOIN counts ON labels.idx = counts.ti "
        "GROUP BY labels.label ORDER BY labels.label"
    )
    if normalize is None:
        sql = counted
    else:
        row = " + ".join(names)
        grand = " + ".join(f"sum({n}) OVER ()" for n in names)
        total = {"true": f"({row})", "pred": None, "all": f"({grand})"}[normalize]
        divided = ", ".join(
            "CASE WHEN {t} = 0 THEN 0.0 ELSE CAST({c} AS DOUBLE) / {t} END "
            "AS {c}".format(c=n, t=total if total is not None else f"sum({n}) OVER ()")
            for n in names
        )
        sql = (
            f"WITH matrix AS ({counted}) "
            f"SELECT {quote(target)}, {divided} FROM matrix "
            f"ORDER BY {quote(target)}"
        )
    return to_output(_select(rel, sql), out)

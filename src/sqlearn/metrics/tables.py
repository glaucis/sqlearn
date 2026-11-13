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


def _cell(i: int, normalize: str | None) -> str:
    """Return the SQL of column `i`'s cell in a label's row of the grouped query.

    Counts and totals are read by label index, never by column name, so
    nothing depends on how DuckDB resolves the columns' names.
    """
    count = f"coalesce(sum(CASE WHEN pi = {i} THEN n END), 0)"
    if normalize is None:
        return f"CAST({count} AS BIGINT)"
    total = {
        "true": "coalesce(sum(n), 0)",
        "pred": f"(SELECT coalesce(sum(n), 0) FROM counts WHERE pi = {i})",
        "all": "(SELECT coalesce(sum(n), 0) FROM counts)",
    }[normalize]
    return f"CASE WHEN {total} = 0 THEN 0.0 ELSE CAST({count} AS DOUBLE) / {total} END"


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
    seen: dict[str, tuple[object, str]] = {target.lower(): (target, target)}
    for label, text in rows:
        if text == "":
            msg = (
                "confusion_matrix cannot be computed: a label is empty text. "
                "Why: each label is a column named by its text, and DuckDB "
                "cannot name a column with no text. Fix: replace the empty "
                "label first, for example with 'none'."
            )
            raise SqlearnError(msg)
        other = seen.get(text.lower())
        if other is not None and other[1] == target and other[0] == target:
            msg = (
                f"confusion_matrix cannot be computed: the label {label!r} "
                f"has the same text as the target column {target!r}, ignoring "
                "case. Why: each label is a column named by its text, beside "
                f"the column {target!r} of true labels, and DuckDB names do "
                "not differ by case. Fix: rename the target column, or the "
                "label."
            )
            raise SqlearnError(msg)
        if other is not None:
            msg = (
                f"confusion_matrix cannot be computed: the labels "
                f"{other[0]!r} and {label!r} differ only by case. Why: each "
                "label is a column named by its text, and DuckDB names do "
                "not differ by case (it would rename one to "
                f"{text + '_1'!r}). Fix: make the labels differ by more than "
                "case, for example by lower-casing the target and the "
                "prediction first."
            )
            raise SqlearnError(msg)
        seen[text.lower()] = (label, text)
    if len(rows) == 1:
        warnings.warn(
            "A single label was found in the target and the prediction. "
            "For the confusion matrix to have the correct shape there "
            "should be a label for every class. Fix: this is the 1 by 1 "
            "matrix of the one label; check the data holds every class.",
            SqlearnWarning,
            stacklevel=2,
        )
    cells = ", ".join(
        f"{_cell(i, normalize)} AS {quote(text)}" for i, (_, text) in enumerate(rows)
    )
    sql = (
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
    return to_output(_select(rel, sql), out)

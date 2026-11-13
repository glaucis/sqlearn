"""Metrics that are tables: the confusion matrix (spec §4, ADR 0049).

Each is a function over a relation that hands back a lazy DuckDB relation,
or what ``out=`` names, not a `Metric`: a table cannot rank a search.
"""

import math
import warnings
from fractions import Fraction
from typing import Any

import duckdb

from sqlearn._config import connection
from sqlearn._errors import InternalError, SqlearnError, SqlearnWarning
from sqlearn._expr import quote
from sqlearn._output import Output, to_output
from sqlearn.metrics._labels import check_labels
from sqlearn.metrics.classification import (
    _counts,
    _nanmean,
    _valid_zero_division,
    f1,
    precision,
    recall,
)

__all__ = ["classification_report", "confusion_matrix"]

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


def _text_sql(label: object) -> str:
    """Return the SQL of a label's text, as DuckDB renders the label."""
    if isinstance(label, bool):
        return "'true'" if label else "'false'"
    if isinstance(label, int):
        return f"CAST({label} AS VARCHAR)"
    if isinstance(label, float):
        return f"CAST({label!r}::DOUBLE AS VARCHAR)"
    return "'" + str(label).replace("'", "''") + "'"


def _as_float(value: Fraction | None) -> float:
    """Return a score as a double; an undefined one (None) is NaN."""
    return math.nan if value is None else float(value)


def _double_sql(value: float | None) -> str:
    """Return the SQL of a DOUBLE, NULL for None and NaN for nan."""
    if value is None:
        return "CAST(NULL AS DOUBLE)"
    if math.isnan(value):
        return "'NaN'::DOUBLE"
    return f"{value!r}::DOUBLE"


def classification_report(
    rel: duckdb.DuckDBPyRelation,
    target: str,
    prediction: str = "prediction",
    *,
    zero_division: str | float = "warn",
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401  (the form `out` names)
    """Report each class's precision, recall, F1 and support, and the averages.

    As scikit-learn 1.9.1's ``classification_report`` with
    ``output_dict=True``, as rows of a relation: one per class in label
    order, then ``accuracy`` (precision and recall NULL, `f1_score` the
    accuracy, `support` every row), ``macro avg`` and ``weighted avg``. The
    scores are exact arithmetic on one grouped count per class, as precision,
    recall and F1 (ADR 0049); only those counts reach Python.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The rows, holding a target and a prediction column.
    target : str
        The column of true labels.
    prediction : str, default "prediction"
        The column of predicted labels.
    zero_division : {"warn", 0.0, 1.0, nan}, default "warn"
        The score of a class whose score divides by zero. ``"warn"`` sets
        it to 0.0 and warns, once for each kind of score; nan leaves the
        class out of the averages.
    out : {"pandas", "polars", "numpy", "arrow"} or Output or None
        What to hand back; None is a relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        The report, with columns `label` (`VARCHAR`, the class's text as
        DuckDB renders it), `precision`, `recall`, `f1_score` (`DOUBLE`)
        and `support` (`BIGINT`), or it as `out` names.

    Raises
    ------
    SqlearnError
        If `zero_division` is not one of its values, or the labels fail
        precision's checks (no rows, NULL, NaN, infinity, continuous or
        mixed-kind labels).

    Warns
    -----
    UndefinedMetricWarning
        Under ``zero_division="warn"``, for the classes never predicted
        (precision) or never true (recall).

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0), (1, 0), (1, 1)) t(y, prediction)"
    ... )
    >>> sq.metrics.classification_report(rel, "y").fetchall()[-3]
    ('accuracy', None, None, 0.6666666666666666, 3)
    """
    if not _valid_zero_division(zero_division):
        msg = (
            f"classification_report was given zero_division={zero_division!r}. "
            'Why: it takes "warn", 0.0, 1.0 or nan, as scikit-learn. Fix: '
            "use one of them."
        )
        raise SqlearnError(msg)
    check_labels("classification_report", rel, target, prediction)
    counts = _counts(rel, target, prediction)
    scores = [
        metric(zero_division=zero_division)._per_class(counts)
        for metric in (precision, recall, f1)
    ]
    support = [c[1] for c in counts]
    total = sum(support)
    accuracy = float(Fraction(sum(c[3] for c in counts), total))
    texts = [_text_sql(c[0]) for c in counts]
    rows = [
        (texts[i], *(_as_float(sc[i]) for sc in scores)) for i in range(len(counts))
    ]
    values = [
        f"({t}, {_double_sql(p)}, {_double_sql(r)}, {_double_sql(f)}, "
        f"CAST({n} AS BIGINT))"
        for (t, p, r, f), n in zip(rows, support, strict=True)
    ]
    for name, weights in (("macro avg", None), ("weighted avg", support)):
        p, r, f = (_nanmean(s, weights) for s in scores)
        values.append(
            f"('{name}', {_double_sql(p)}, {_double_sql(r)}, {_double_sql(f)}, "
            f"CAST({total} AS BIGINT))"
        )
    values.insert(
        len(counts),
        f"('accuracy', {_double_sql(None)}, {_double_sql(None)}, "
        f"{_double_sql(accuracy)}, CAST({total} AS BIGINT))",
    )
    sql = (
        "SELECT * FROM (VALUES "
        + ", ".join(values)
        + ") t(label, precision, recall, f1_score, support)"
    )
    return to_output(connection().sql(sql), out)

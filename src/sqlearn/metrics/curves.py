"""Metrics that are curves: the ROC and precision-recall curves (spec §4, ADR 0049).

A curve is a function over a relation that hands back a lazy DuckDB
relation, or what ``out=`` names, not a `Metric`: it cannot rank a search.
Both curves read the same steps (`_steps`): one row per distinct score, with
the running counts of positive and negative rows at or above it.
"""

import warnings
from typing import Any

import duckdb

from sqlearn._errors import InternalError, SqlearnError, UndefinedMetricWarning
from sqlearn._expr import const, quote
from sqlearn._output import Output, to_output
from sqlearn.metrics._labels import (
    _COMPARISON_ERRORS,
    _FLOATS,
    _NUMBERS,
    _column_types,
    _first_line,
    check_labels,
)

__all__ = ["precision_recall_curve", "roc_curve"]

_SOURCE = "_sqlearn_rows"
"""The name the rows go by inside the SQL of a curve."""

_STEPS = "_sqlearn_steps"
"""The name the steps go by inside the SQL of a curve."""

_ACCEPTED = (
    frozenset({0, 1}),
    frozenset({-1, 1}),
    frozenset({0}),
    frozenset({1}),
    frozenset({-1}),
)
"""The label sets scikit-learn 1.9.1 takes without a ``pos_label``."""


def _query(
    rel: duckdb.DuckDBPyRelation, name: str, sql: str
) -> duckdb.DuckDBPyRelation:
    """Return the relation of a SELECT over `rel`, which the SQL calls `name`."""
    got = rel.query(name, sql)
    if got is None:  # a SELECT always gives a relation
        msg = "DuckDB gave no relation for a SELECT"
        raise InternalError(msg)
    return got


def _positive(
    name: str, rel: duckdb.DuckDBPyRelation, target: str, pos_label: object
) -> str:
    """Return the SQL that says a row is positive, refusing labels without one.

    As scikit-learn 1.9.1: with no `pos_label` the labels must be among
    {0, 1}, {-1, 1}, {0}, {1} or {-1}, and 1 is the positive; with one, any
    number of classes does.
    """
    if pos_label is not None:
        return f"{quote(target)} = {const(pos_label)}"
    found = [r[0] for r in rel.project(quote(target)).distinct().limit(4).fetchall()]
    if frozenset(found) not in _ACCEPTED:
        shown = ", ".join(repr(x) for x in found[:3]) + (
            ", ..." if len(found) > 3 else ""
        )
        msg = (
            f"{name} cannot be computed: the target {target!r} holds the labels "
            f"{shown} and pos_label is not given. Why: scikit-learn takes "
            "the labels {0, 1} or {-1, 1} alone, and calls 1 the positive. "
            "Fix: pass pos_label= with the label to treat as positive."
        )
        raise SqlearnError(msg)
    return f"{quote(target)} = 1"


def _steps(
    name: str,
    rel: duckdb.DuckDBPyRelation,
    target: str,
    score: str,
    pos_label: object,
) -> tuple[duckdb.DuckDBPyRelation, int, int]:
    """Return the steps of a curve, and its totals of positive and negative rows.

    The relation has one row per distinct score, descending: `threshold`
    (`DOUBLE`), and the running counts `tps` and `fps` (`HUGEINT`) of
    positive and negative rows scoring at least that. Only the two totals
    reach Python. The label and score checks are made first: the labels of
    precision's checks, and a score that is a number and neither NULL, NaN
    nor infinite.
    """
    types = _column_types(name, rel, [target, score])
    dtype = types[score]
    if dtype not in _NUMBERS and not dtype.startswith("DECIMAL"):
        msg = (
            f"{name} cannot be computed: column {score!r} has the type "
            f"{dtype}, which is not a number. Why: a score is ranked, and "
            "scikit-learn refuses text there too. Fix: pass a column of "
            "numbers, such as a model's probability."
        )
        raise SqlearnError(msg)
    check_labels(name, rel, target, target)
    positive = _positive(name, rel, target, pos_label)
    column = duckdb.ColumnExpression(score)
    counts = {
        "rows": duckdb.FunctionExpression("count_star"),
        "seen": duckdb.FunctionExpression("count", column),
        "positive": duckdb.FunctionExpression(
            "count", duckdb.CaseExpression(duckdb.SQLExpression(positive), const(1))
        ),
    }
    if dtype in _FLOATS:
        counts["nan"] = duckdb.FunctionExpression(
            "count",
            duckdb.CaseExpression(duckdb.FunctionExpression("isnan", column), const(1)),
        )
        counts["infinite"] = duckdb.FunctionExpression(
            "count",
            duckdb.CaseExpression(duckdb.FunctionExpression("isinf", column), const(1)),
        )
    try:
        row = rel.aggregate(list(counts.values())).fetchall()[0]
    except _COMPARISON_ERRORS as exc:
        msg = (
            f"{name} cannot be computed: pos_label={pos_label!r} cannot be "
            f"compared with column {target!r} ({types[target]}): "
            f"{_first_line(exc)} Fix: pass a pos_label of the kind the "
            "target holds."
        )
        raise SqlearnError(msg) from exc
    got = dict(zip(counts, row, strict=True))
    for key, what, why in (
        ("seen", "NULL", "A missing score cannot be ranked"),
        ("nan", "NaN", "A NaN score cannot be ranked"),
        ("infinite", "infinite", "scikit-learn refuses an infinite score too"),
    ):
        bad = got["rows"] - got[key] if key == "seen" else got.get(key, 0)
        if bad:
            msg = (
                f"{name} cannot be computed: column {score!r} has {bad} "
                f"{what} of {got['rows']} rows. {why}. Fix: drop or replace "
                "those rows first."
            )
            raise SqlearnError(msg)
    sql = (
        f"WITH g AS (SELECT {quote(score)} AS s, count(*) AS n, "
        f"count(CASE WHEN {positive} THEN 1 END) AS p FROM {_SOURCE} "
        f"GROUP BY {quote(score)}) "
        "SELECT CAST(s AS DOUBLE) AS threshold, "
        "CAST(sum(p) OVER w AS HUGEINT) AS tps, "
        "CAST(sum(n - p) OVER w AS HUGEINT) AS fps FROM g "
        "WINDOW w AS (ORDER BY s DESC)"
    )
    positives = int(got["positive"])
    return _query(rel, _SOURCE, sql), positives, int(got["rows"]) - positives


def _rate(count: str, total: int) -> str:
    """Return the SQL of a count over its total: one division, NaN for 0."""
    if total == 0:
        return "'NaN'::DOUBLE"
    return f"CAST({count} AS DOUBLE) / {total}.0"


def roc_curve(
    rel: duckdb.DuckDBPyRelation,
    target: str,
    score: str,
    *,
    pos_label: object = None,
    drop_intermediate: bool = True,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401  (the form `out` names)
    """Trace the true against the false positive rate over every threshold.

    As scikit-learn 1.9.1's ``roc_curve`` without ``sample_weight=``, as a
    relation: the first row is at threshold ``inf`` (nothing is called
    positive), then one row per distinct score, descending. Each rate is one
    division of two exact counts, which DuckDB sums in windows over the
    distinct scores (ADR 0049); no row reaches Python.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The rows, holding a target and a score column.
    target : str
        The column of true labels.
    score : str
        The column of scores: numbers, higher for the positive class.
    pos_label : object, default None
        The positive label. None takes 1, and needs the labels to be among
        {0, 1}, {-1, 1}, {0}, {1} or {-1}, as scikit-learn. With a label,
        any number of classes works: that class against the rest.
    drop_intermediate : bool, default True
        Drop the points scikit-learn drops: those whose false and true
        positive counts both step by the same amount before and after (equal
        steps, not every point on a straight line). The first and last
        points stay.
    out : {"pandas", "polars", "numpy", "arrow"} or Output or None
        What to hand back; None is a lazy relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        The curve, with columns `fpr`, `tpr` and `threshold` (`DOUBLE`), or
        it as `out` names.

    Raises
    ------
    SqlearnError
        If the labels fail precision's checks (no rows, NULL, NaN, infinity,
        continuous labels), the labels need a `pos_label` or it cannot be
        compared with them, or the score is not a number or holds NULL, NaN
        or infinity.

    Warns
    -----
    UndefinedMetricWarning
        If no row is negative (`fpr` is NaN) or none is positive (`tpr` is
        NaN).

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0.1), (1, 0.8), (0, 0.4), (1, 0.4)) t(y, s)"
    ... )
    >>> sq.metrics.roc_curve(rel, "y", "s", drop_intermediate=False).fetchall()
    [(0.0, 0.0, inf), (0.0, 0.5, 0.8), (0.5, 1.0, 0.4), (1.0, 1.0, 0.1)]
    """
    steps, positives, negatives = _steps("roc_curve", rel, target, score, pos_label)
    if negatives == 0:
        warnings.warn(
            "No negative samples in y_true, false positive value should be "
            "meaningless. Fix: check the data holds rows of the other classes.",
            UndefinedMetricWarning,
            stacklevel=2,
        )
    if positives == 0:
        warnings.warn(
            "No positive samples in y_true, true positive value should be "
            "meaningless. Fix: check pos_label names a label the target holds.",
            UndefinedMetricWarning,
            stacklevel=2,
        )
    keep = "TRUE"
    if drop_intermediate:
        # 1.9.1 drops a point whose second difference of both counts is 0.
        keep = (
            "m <= 2 OR i = 1 OR i = m "
            "OR lag(fps) OVER w - 2 * fps + lead(fps) OVER w <> 0 "
            "OR lag(tps) OVER w - 2 * tps + lead(tps) OVER w <> 0"
        )
    sql = (
        "WITH numbered AS (SELECT threshold, tps, fps, "
        "row_number() OVER w AS i, count(*) OVER () AS m, "
        f"{keep} AS kept FROM {_STEPS} WINDOW w AS (ORDER BY threshold DESC)) "
        f"SELECT {_rate('0', negatives)} AS fpr, {_rate('0', positives)} AS tpr, "
        "'inf'::DOUBLE AS threshold FROM (SELECT 1) "
        "UNION ALL "
        f"SELECT {_rate('fps', negatives)}, {_rate('tps', positives)}, threshold "
        "FROM numbered WHERE kept ORDER BY threshold DESC"
    )
    return to_output(_query(steps, _STEPS, sql), out)


def precision_recall_curve(
    rel: duckdb.DuckDBPyRelation,
    target: str,
    score: str,
    *,
    pos_label: object = None,
    drop_intermediate: bool = False,
    out: str | Output | None = None,
) -> Any:  # noqa: ANN401  (the form `out` names)
    """Trace precision against recall over every threshold.

    As scikit-learn 1.9.1's ``precision_recall_curve`` without
    ``sample_weight=``, as a relation: one row per distinct score, thresholds
    increasing, then a final row (precision 1, recall 0) whose threshold is
    NULL. Each value is one division of two exact counts, which DuckDB sums in
    windows over the distinct scores (ADR 0049); no row reaches Python.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The rows, holding a target and a score column.
    target : str
        The column of true labels.
    score : str
        The column of scores: numbers, higher for the positive class.
    pos_label : object, default None
        The positive label. None takes 1, and needs the labels to be among
        {0, 1}, {-1, 1}, {0}, {1} or {-1}, as scikit-learn. With a label,
        any number of classes works: that class against the rest.
    drop_intermediate : bool, default False
        Drop the points scikit-learn drops: those whose true positive count
        equals both its neighbours' (they lie on a vertical line of the
        plot). The first and last points stay.
    out : {"pandas", "polars", "numpy", "arrow"} or Output or None
        What to hand back; None is a lazy relation.

    Returns
    -------
    duckdb.DuckDBPyRelation or object
        The curve, with columns `precision`, `recall` and `threshold`
        (`DOUBLE`), or it as `out` names.

    Raises
    ------
    SqlearnError
        If the labels fail precision's checks (no rows, NULL, NaN, infinity,
        continuous labels), the labels need a `pos_label` or it cannot be
        compared with them, or the score is not a number or holds NULL, NaN
        or infinity.

    Warns
    -----
    UserWarning
        If no row is positive: recall is then 1 for every threshold, as
        scikit-learn. No negative row gives precision 1 and no warning.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (0, 0.1), (1, 0.8), (0, 0.4), (1, 0.4)) t(y, s)"
    ... )
    >>> sq.metrics.precision_recall_curve(rel, "y", "s").fetchall()
    [(0.5, 1.0, 0.1), (0.6666666666666666, 1.0, 0.4), (1.0, 0.5, 0.8), (1.0, 0.0, None)]
    """
    steps, positives, _ = _steps(
        "precision_recall_curve", rel, target, score, pos_label
    )
    if positives == 0:
        warnings.warn(
            "No positive class found in y_true, recall is set to one for all "
            "thresholds. Fix: check pos_label names a label the target holds.",
            stacklevel=2,
        )
    keep = "TRUE"
    if drop_intermediate:
        # 1.9.1 keeps a point whose true positives differ from a neighbour's.
        keep = (
            "m <= 2 OR i = 1 OR i = m "
            "OR tps <> lag(tps) OVER w OR tps <> lead(tps) OVER w"
        )
    recall = "1.0" if positives == 0 else f"CAST(tps AS DOUBLE) / {positives}.0"
    sql = (
        "WITH numbered AS (SELECT threshold, tps, fps, "
        "row_number() OVER w AS i, count(*) OVER () AS m, "
        f"{keep} AS kept FROM {_STEPS} WINDOW w AS (ORDER BY threshold DESC)) "
        "SELECT * FROM ("
        "SELECT CAST(tps AS DOUBLE) / CAST(tps + fps AS DOUBLE) AS precision, "
        f"{recall} AS recall, threshold FROM numbered WHERE kept "
        "UNION ALL "
        "SELECT 1.0, 0.0, NULL::DOUBLE) ORDER BY threshold ASC NULLS LAST"
    )
    return to_output(_query(steps, _STEPS, sql), out)

"""The feed: handing prepared data to a model and its predictions back.

A model the user brings (ADR 0017) is handed the prepared rows in the form
its `Model.feed` names; numpy is imported only inside the numpy hand-over,
so sqlearn itself never needs it. Every prediction is streamed: the rows go
to the model one batch at a time, and each batch's predictions are inserted
into a table in DuckDB beside the row numbers they belong to, so no step of
a prediction holds all the rows in memory.
"""

import contextlib
import itertools
import warnings
import weakref
from collections.abc import Generator, Sequence
from typing import Any

import duckdb

from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._expr import quote
from sqlearn._inputs import _drop_later, _release_later
from sqlearn._model import Model, _numpy, check_feed

__all__ = [
    "BATCH_ROWS",
    "PROBA",
    "WrongShapeError",
    "hand_over",
    "predict_streamed",
    "received",
    "stream_into",
    "take",
]

BATCH_ROWS = 65_536
"""How many rows streamed prediction hands the model at a time."""

PROBA = "__sqlearn_proba_"
"""The prefix of the columns ``predict_proba`` fills, one per class."""

_DATABASE = "__sqlearn_feed"
"""The in-memory database holding streamed predictions, private to sqlearn.

The rows are read on the connection while the predictions are written on a
cursor of it (a connection with an open result runs nothing else), and a
connection's temporary tables are its own: a database attached to the
instance is seen by both. DuckDB spills it to disk as it does temporary
tables.
"""

_prediction_ids = itertools.count()
_WARNED: set[str] = set()
"""The warnings already issued in this process, each issued once."""


class WrongShapeError(SqlearnError):
    """A model returned not one value (or one row of probabilities) per row.

    Raised by the stream itself, so a search passes it on as it is, while
    any other error of a fold gets the fold's setting and number.

    Examples
    --------
    >>> from sqlearn._feed import WrongShapeError
    >>> from sqlearn.errors import SqlearnError
    >>> issubclass(WrongShapeError, SqlearnError)
    True
    """


def take(
    rel: duckdb.DuckDBPyRelation,
    feed: str,
    columns: Sequence[str],
    aside: Sequence[str] = (),
) -> tuple[Any, dict[str, Any]]:
    """Run a relation once: the features in the feed's form, other columns aside.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The prepared data, with every column of `columns` and `aside`.
    feed : str
        The form of the features; ``"numpy"`` only.
    columns : sequence of str
        The features, in order.
    aside : sequence of str, default ()
        Columns fetched in the same query but not handed over as features
        (the target, the row number), as numpy arrays (masked where NULL).

    Returns
    -------
    features : numpy.ndarray
        A 2-D float64 array, one column per feature, NULL as NaN.
    aside : dict of str to numpy.ndarray
        The other columns by name.

    Raises
    ------
    SqlearnError
        If `feed` is not built, numpy is missing, or a feature is not a
        number.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import take
    >>> rel = connection().sql("SELECT 1.5 AS a, 'yes' AS y")
    >>> x, other = take(rel, "numpy", ["a"], ["y"])
    >>> x.tolist(), other["y"].tolist()
    ([[1.5]], ['yes'])
    """
    check_feed(feed)
    np = _numpy()
    picked = rel.project(*(duckdb.ColumnExpression(c) for c in [*columns, *aside]))
    arrays = picked.fetchnumpy()
    rows = len(next(iter(arrays.values()))) if arrays else 0
    x = np.empty((rows, len(columns)), dtype=np.float64)
    for j, c in enumerate(columns):
        values = arrays[c]
        if not (
            np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.bool_)
        ):
            kind = dict(zip(rel.columns, rel.types, strict=True))[c]
            msg = (
                f"column {c!r} reaches the model as {kind}, not as a number; a "
                "model is handed numbers only. Fix: encode it with a step "
                "(sq.encode.onehot or sq.encode.ordinal), or leave it out of the data."
            )
            raise SqlearnError(msg)
        x[:, j] = np.ma.filled(np.ma.asarray(values).astype(np.float64), np.nan)
    return x, {c: arrays[c] for c in aside}


def hand_over(rel: duckdb.DuckDBPyRelation, feed: str) -> object:
    """Run a relation and hand its rows over in the form a model takes.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The prepared data; every column is a feature.
    feed : str
        ``"numpy"``: a 2-D float64 array, columns in the relation's order,
        NULL as NaN. Other forms are issue #21.

    Returns
    -------
    numpy.ndarray
        The features.

    Raises
    ------
    SqlearnError
        If `feed` is not ``"numpy"`` (pointing to issue #21), numpy is not
        installed, or a column is not a number.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import hand_over
    >>> hand_over(connection().sql("SELECT 1 AS a, 2.5 AS b"), "numpy").tolist()
    [[1.0, 2.5]]
    """
    x, _ = take(rel, feed, rel.columns)
    return x


def received(
    con: duckdb.DuckDBPyConnection,
    rows: Any,  # noqa: ANN401  (numpy arrays)
    predicted: object,
) -> duckdb.DuckDBPyRelation:
    """Bring a model's predictions into DuckDB, sorted into the input's order.

    The predictions are registered on the connection as numpy arrays (no
    pandas or pyarrow) beside the row numbers they belong to, and the
    relation returned sorts by those numbers. The registration lasts as long
    as the relation does.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection.
    rows : numpy.ndarray
        Each prediction's row number in the input, counting from 1.
    predicted : array-like
        What the model's ``predict`` returned: one value per row.

    Returns
    -------
    duckdb.DuckDBPyRelation
        One column, ``prediction``, one row per input row, in input order.

    Raises
    ------
    SqlearnError
        If the model did not return one value per row.

    Examples
    --------
    >>> import numpy as np
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import received
    >>> rel = received(connection(), np.array([2, 1]), np.array(["b", "a"]))
    >>> rel.fetchall()
    [('a',), ('b',)]
    """
    np = _numpy()
    values = _checked(np.asarray(predicted), len(rows), "predict")
    name = f"_sqlearn_predictions_{next(_prediction_ids)}"
    con.register(name, {"row": np.ma.getdata(rows), "prediction": values})
    rel = (
        con.table(name)
        .order(duckdb.ColumnExpression("row"))
        .project(duckdb.ColumnExpression("prediction"))
    )
    # Release the registration (and the arrays) once the relation is gone.
    weakref.finalize(rel, _release_later, con, name)
    return rel


def _checked(values: Any, rows: int, method: str) -> Any:  # noqa: ANN401  (numpy arrays)
    """Refuse what a model returned unless it is one value (or row) per row."""
    wide = method == "predict_proba"
    if values.ndim != (2 if wide else 1) or len(values) != rows:
        shape = "one row of class probabilities" if wide else "one value"
        returns = "one column per class" if wide else "one column, prediction"
        msg = (
            f"the model's {method} returned an array of shape {values.shape}, "
            f"not {shape} for each of the {rows} rows; sqlearn returns "
            f"{returns}. Fix: use a model whose {method} returns {shape} per "
            "row."
        )
        raise WrongShapeError(msg)
    return values


def _batches(
    cur: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    feed: str,
    columns: Sequence[str],
    row: str,
) -> Generator[tuple[Any, Any]]:
    """Yield the features and the row numbers of `rel`, a batch at a time.

    With pyarrow, the relation is read as Arrow batches of `BATCH_ROWS`
    rows, each converted as `take` converts a whole relation (on `cur`, as
    the relation's own connection has the read open). Without it, the rows
    go in one batch. A relation of no rows gives one empty batch, so the
    model is asked once, as for any input.
    """
    picked = rel.project(*(duckdb.ColumnExpression(c) for c in [*columns, row]))
    try:
        import pyarrow  # noqa: F401  (only to know it is there)
    except ImportError:
        if "pyarrow" not in _WARNED:
            _WARNED.add("pyarrow")
            text = (
                "pyarrow is not installed, so prediction is not streamed: "
                "all the rows are fetched and handed to the model at once, "
                "which needs them in memory. Fix: install pyarrow (uv add "
                "pyarrow) to predict in batches."
            )
            warnings.warn(text, SqlearnWarning, stacklevel=5)
        x, aside = take(picked, feed, columns, [row])
        yield x, aside[row]
        return
    empty = True
    # Closed however the caller stops, so the connection's read is released.
    with contextlib.closing(picked.to_arrow_reader(batch_size=BATCH_ROWS)) as reader:
        for batch in reader:
            if batch.num_rows == 0:
                continue
            empty = False
            x, aside = take(cur.from_arrow(batch), feed, columns, [row])
            yield x, aside[row]
    if empty:
        x, aside = take(picked, feed, columns, [row])
        yield x, aside[row]


def stream_into(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    row: str,
    model: Model,
    *,
    method: str = "predict",
) -> tuple[str, list[str]]:
    """Predict a relation batch by batch into a table; the caller drops it.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection `rel` belongs to.
    rel : duckdb.DuckDBPyRelation
        The prepared rows, with every column of `columns` and `row`.
    columns : sequence of str
        The features, in order.
    row : str
        The column numbering the rows.
    model : Model
        The fitted model; `Model.feed` names the form of the hand-over.
    method : str, default "predict"
        The model's method to call: ``"predict"`` or ``"predict_proba"``.

    Returns
    -------
    table : str
        The table's qualified name, each part quoted, ready for SQL text:
        the column `row`, then the predictions.
    outputs : list of str
        The prediction columns: ``prediction``, or for ``predict_proba``
        ``__sqlearn_proba_0``, ``__sqlearn_proba_1``, ... one per class.

    Raises
    ------
    SqlearnError
        As for `take`.
    WrongShapeError
        If the model does not return one value (or one row of
        probabilities) per row.

    Warns
    -----
    SqlearnWarning
        Once per process, when pyarrow is missing and the rows go to the
        model in one batch.

    Examples
    --------
    >>> import numpy as np
    >>> from sklearn.dummy import DummyClassifier
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import stream_into
    >>> model = sq.Model(DummyClassifier().fit(np.zeros((2, 1)), [0, 0]))
    >>> con = connection()
    >>> rel = con.sql("SELECT 1.0 AS a, 1 AS r")
    >>> table, outputs = stream_into(con, rel, ["a"], "r", model)
    >>> outputs, con.sql(f"SELECT * FROM {table}").fetchall()
    (['prediction'], [(1, 0)])
    >>> con.execute(f"DROP TABLE {table}") is con
    True
    """
    np = _numpy()
    predict = getattr(model.estimator, method)
    con.execute(f"ATTACH IF NOT EXISTS ':memory:' AS {quote(_DATABASE)}")
    name = f"{quote(_DATABASE)}.{quote(f'predictions_{next(_prediction_ids)}')}"
    batch_name = f"_sqlearn_batch_{next(_prediction_ids)}"
    outputs: list[str] = []
    cur = con.cursor()
    batches = _batches(cur, rel, model.feed, columns, row)
    try:
        for x, rows in batches:
            values = _checked(np.asarray(predict(x)), len(rows), method)
            if values.dtype.kind == "U":
                # numpy text registers as an ENUM of the batch's own values,
                # which a later batch's could not join: text is VARCHAR.
                values = values.astype(object)
            if values.ndim == 1:
                arrays = {"prediction": values}
            else:
                arrays = {f"{PROBA}{j}": values[:, j] for j in range(values.shape[1])}
            cur.register(batch_name, {row: np.ma.getdata(rows), **arrays})
            try:
                if outputs:
                    cur.execute(f"INSERT INTO {name} BY NAME FROM {quote(batch_name)}")
                else:
                    cur.execute(f"CREATE TABLE {name} AS FROM {quote(batch_name)}")
                    outputs = list(arrays)
            finally:
                cur.unregister(batch_name)
    except BaseException:
        if outputs:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        raise
    finally:
        batches.close()  # ends the read even when the model failed mid-way
        cur.close()
    return name, outputs


def predict_streamed(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    row: str,
    model: Model,
    *,
    method: str = "predict",
) -> duckdb.DuckDBPyRelation:
    """Predict a relation one batch at a time, sorted back by row number.

    The rows are read in batches of `BATCH_ROWS` (one batch when pyarrow is
    not installed); each batch's features go to the model in its feed's
    form, and its predictions are inserted beside the batch's row numbers
    into a table, dropped once the relation returned is gone.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection `rel` belongs to.
    rel : duckdb.DuckDBPyRelation
        The prepared rows, with every column of `columns` and `row`.
    columns : sequence of str
        The features, in order.
    row : str
        The column numbering the rows; the result is sorted by it.
    model : Model
        The fitted model.
    method : str, default "predict"
        The model's method to call: ``"predict"`` or ``"predict_proba"``.

    Returns
    -------
    duckdb.DuckDBPyRelation
        One column, ``prediction`` (or, for ``predict_proba``, one column
        per class, ``__sqlearn_proba_0``, ``__sqlearn_proba_1``, ...), one
        row per row of `rel`, sorted by `row`.

    Raises
    ------
    SqlearnError
        As for `stream_into`.

    Examples
    --------
    >>> import numpy as np
    >>> from sklearn.dummy import DummyClassifier
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import predict_streamed
    >>> model = sq.Model(DummyClassifier().fit(np.zeros((2, 1)), ["no", "no"]))
    >>> con = connection()
    >>> rel = con.sql("SELECT i::DOUBLE AS a, 3 - i AS r FROM range(3) t(i)")
    >>> predict_streamed(con, rel, ["a"], "r", model).fetchall()
    [('no',), ('no',), ('no',)]
    """
    name, outputs = stream_into(con, rel, columns, row, model, method=method)
    out = (
        con.sql(f"FROM {name}")
        .order(duckdb.ColumnExpression(row))
        .project(*(duckdb.ColumnExpression(c) for c in outputs))
    )
    # Drop the table once the relation is gone.
    weakref.finalize(out, _drop_later, con, name)
    return out

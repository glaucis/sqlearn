"""The feed: handing prepared data to a model and its predictions back.

A model the user brings (ADR 0017) is handed the prepared rows in the form
its `Model.feed` names (ADR 0041): numpy, pandas, Polars or Arrow, each
library imported only inside the hand-over that needs it, so sqlearn itself
never needs them. Text columns reach pandas, Polars and Arrow as categories.
Every prediction is streamed: the rows go
to the model one batch at a time, and each batch's predictions are inserted
into a table in DuckDB beside the row numbers they belong to, so no step of
a prediction holds all the rows in memory.
"""

import contextlib
import importlib
import itertools
import warnings
import weakref
from collections.abc import Generator, Mapping, Sequence
from typing import Any

import duckdb

from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._expr import quote
from sqlearn._inputs import _drop_later, _release_later
from sqlearn._model import Model, _numpy, check_feed, missing_target, target_values

__all__ = [
    "BATCH_ROWS",
    "PROBA",
    "WrongShapeError",
    "fetch",
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

_AS_NUMPY = ("numpy", "stream")
"""The feeds whose rows are handed over as a numpy array."""

_NULL = "__sqlearn_target_null"
"""The column counting the target's SQL NULLs beside a pandas fetch."""

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
    """Run a relation once: the features as numpy, other columns aside.

    The numpy hand-over of `fetch`, for ``"numpy"`` and ``"stream"``.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The prepared data, with every column of `columns` and `aside`.
    feed : str
        The form of the features: ``"numpy"`` or ``"stream"``.
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
        If `feed` is not ``"numpy"`` or ``"stream"``, numpy is missing, or a
        feature is not a number.

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
    if feed not in _AS_NUMPY:
        msg = f"take hands over numpy only, not feed={feed!r}; fetch hands any form"
        raise SqlearnError(msg)
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


def _library(module: str, feed: str) -> Any:  # noqa: ANN401  (a module, imported here only)
    """Import a form's library, or say how to install it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        msg = (
            f"feed={feed!r} hands the data to the model through {module}, and "
            f"{module} is not installed. Fix: install it (uv add {module}), or "
            "pass another feed."
        )
        raise SqlearnError(msg) from exc


def fetch(
    rel: duckdb.DuckDBPyRelation,
    feed: str,
    columns: Sequence[str],
    target: str | None,
    *,
    named: str | None = None,
    categories: dict[str, list[str]] | None = None,
) -> tuple[Any, Any]:
    """Run a relation once: the features and the target in the feed's form.

    Each form comes from DuckDB's own method (``fetchnumpy``, ``df``,
    ``pl``, ``to_arrow_table``). With pandas, Polars and Arrow a text
    (``VARCHAR``) feature is cast to that library's categories after the
    fetch; a NULL stays missing, never a category. numpy and the stream
    refuse text, as `take` does.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The prepared data, with every column of `columns` and `target`.
    feed : {"numpy", "pandas", "polars", "arrow", "stream"}
        The form (``"stream"`` hands a batch over as numpy).
    columns : sequence of str
        The features, in order.
    target : str or None
        The target's column, fetched in the same query, or None for none.
    named : str, optional
        The target's name in the user's data, for the message when it is
        missing; `target` when not given.
    categories : dict of str to list of str, optional
        Each text feature's categories, shared by every fetch of one model
        so a value keeps its code. A column in it keeps its list as the
        prefix (values it lacks are appended, sorted); a column not in it
        learns its list here, the sorted values, and is recorded in it.
        Without it, each fetch has its own sorted list.

    Returns
    -------
    features : object
        A 2-D float64 array for numpy and the stream, NULL as NaN; a
        ``DataFrame`` for pandas and Polars; a ``pyarrow.Table`` for Arrow.
    target : object or None
        An array for numpy and the stream; a ``Series`` named `named` (or
        `target`) for pandas and Polars; a ``pyarrow.ChunkedArray`` for
        Arrow. None without a target.

    Raises
    ------
    SqlearnError
        If `feed` is not a form, its library is not installed, the target
        is missing (NULL) in a row, or (numpy, stream) a feature is not a
        number.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import fetch
    >>> rel = connection().sql("SELECT 1.5 AS a, 'Oslo' AS city, 0 AS y")
    >>> x, y = fetch(rel, "pandas", ["a", "city"], "y")
    >>> str(x["city"].dtype), y.tolist()
    ('category', [0])
    """
    check_feed(feed)
    name = named if named is not None else target
    aside = [] if target is None else [target]
    if feed in _AS_NUMPY:
        matrix, other = take(rel, feed, columns, aside)
        if target is None:
            return matrix, None
        return matrix, target_values(other[target], name or target)
    kinds = dict(zip(rel.columns, rel.types, strict=True))
    text = [c for c in columns if str(kinds[c]) == "VARCHAR"]
    known = {} if categories is None else categories
    picks = [duckdb.ColumnExpression(c) for c in [*columns, *aside]]
    if target is not None and feed == "pandas":
        # pandas reads NULL and NaN alike; the SQL NULLs are counted beside.
        picks.append(duckdb.ColumnExpression(target).isnull().alias(_NULL))
    picked = rel.project(*picks)
    x: Any
    y: Any = None
    if feed == "pandas":
        pd = _library("pandas", feed)
        x = picked.df()
        missing = 0
        if target is not None:
            missing = int(x.pop(_NULL).sum())
            y = x.pop(target).rename(name)
        for c in text:
            order = _order(known, c, x[c].dropna().unique().tolist())
            x[c] = pd.Categorical(x[c], categories=order)
    elif feed == "polars":
        pl = _library("polars", feed)
        x = picked.pl()
        if target is not None:
            y = x.get_column(target).alias(name or "")
            x = x.drop(target)
        for c in text:
            order = _order(known, c, x[c].drop_nulls().unique().to_list())
            # A Categories gives codes in the order values are first cast,
            # for as long as a cast series holds them: `seed` casts the
            # order first and is kept until the column holds them too.
            dtype = pl.Categorical(pl.Categories.random())
            seed = pl.Series(order, dtype=pl.String).cast(dtype)
            x = x.with_columns(x[c].cast(dtype))
            del seed
        missing = 0 if y is None else y.null_count()
    else:
        pa = _library("pyarrow", feed)
        pc = _library("pyarrow.compute", feed)
        table = picked.to_arrow_table()
        y = None if target is None else table.column(target)
        x = table.select(list(columns))
        for c in text:
            values = x.column(c).combine_chunks()
            order = _order(known, c, pc.unique(values.drop_null()).to_pylist())
            dictionary = pa.array(order, type=pa.string())
            indices = pc.index_in(values, value_set=dictionary)
            encoded = pa.DictionaryArray.from_arrays(indices, dictionary)
            x = x.set_column(x.column_names.index(c), c, encoded)
        missing = 0 if y is None else y.null_count
    if missing:
        raise missing_target(name or "", missing)
    return x, y


def _order(known: dict[str, list[str]], column: str, values: list[str]) -> list[str]:
    """Return a text column's categories: the known ones, then new values.

    A column not in `known` learns its list here, sorted, and records it;
    one in `known` keeps that list as the prefix, so its values keep their
    codes, and the values it lacks follow, sorted (never dropped to missing).
    """
    if column not in known:
        known[column] = sorted(values)
    seen = set(known[column])
    return [*known[column], *sorted(v for v in values if v not in seen)]


def hand_over(rel: duckdb.DuckDBPyRelation, feed: str) -> object:
    """Run a relation and hand its rows over in the form a model takes.

    Parameters
    ----------
    rel : duckdb.DuckDBPyRelation
        The prepared data; every column is a feature, in order.
    feed : {"numpy", "pandas", "polars", "arrow", "stream"}
        The form, as for `fetch`.

    Returns
    -------
    object
        The features, as `fetch` returns them.

    Raises
    ------
    SqlearnError
        As for `fetch`.

    Examples
    --------
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import hand_over
    >>> hand_over(connection().sql("SELECT 1 AS a, 2.5 AS b"), "numpy").tolist()
    [[1.0, 2.5]]
    """
    x, _ = fetch(rel, feed, rel.columns, None)
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


def _fetched(
    rel: duckdb.DuckDBPyRelation,
    feed: str,
    columns: Sequence[str],
    row: str,
    categories: dict[str, list[str]],
) -> tuple[Any, Any]:
    """Fetch the features in the feed's form and the row numbers as numpy."""
    x, rows = fetch(rel, feed, columns, row, categories=categories)
    return x, _numpy().asarray(rows)


def _batches(
    cur: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    feed: str,
    columns: Sequence[str],
    row: str,
    categories: Mapping[str, Sequence[str]] | None,
) -> Generator[tuple[Any, Any]]:
    """Yield the features and the row numbers of `rel`, a batch at a time.

    With pyarrow, the relation is read as Arrow batches of `BATCH_ROWS`
    rows, each converted as `fetch` converts a whole relation (on `cur`, as
    the relation's own connection has the read open), so a batch reaches
    the model in its feed's form, text as categories: those of
    `categories` first, shared by every batch (without it, the first
    batch's, sorted). Without pyarrow, the rows
    go in one batch. A relation of no rows gives one empty batch, so the
    model is asked once, as for any input.
    """
    picked = rel.project(*(duckdb.ColumnExpression(c) for c in [*columns, row]))
    # A copy: what a batch learns is not kept for the model.
    known = {c: list(v) for c, v in (categories or {}).items()}
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
        yield _fetched(picked, feed, columns, row, known)
        return
    empty = True
    # Closed however the caller stops, so the connection's read is released.
    with contextlib.closing(picked.to_arrow_reader(batch_size=BATCH_ROWS)) as reader:
        for batch in reader:
            if batch.num_rows == 0:
                continue
            empty = False
            yield _fetched(cur.from_arrow(batch), feed, columns, row, known)
    if empty:
        yield _fetched(picked, feed, columns, row, known)


def stream_into(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    row: str,
    model: Model,
    *,
    method: str = "predict",
    categories: Mapping[str, Sequence[str]] | None = None,
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
    categories : mapping of str to sequence of str, optional
        Each text feature's categories as the model was trained on them
        (see `fetch`): every batch keeps their codes.

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
    batches = _batches(cur, rel, model.feed, columns, row, categories)
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
    categories: Mapping[str, Sequence[str]] | None = None,
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
    categories : mapping of str to sequence of str, optional
        Each text feature's categories as the model was trained on them
        (see `fetch`): every batch keeps their codes.

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
    name, outputs = stream_into(
        con, rel, columns, row, model, method=method, categories=categories
    )
    out = (
        con.sql(f"FROM {name}")
        .order(duckdb.ColumnExpression(row))
        .project(*(duckdb.ColumnExpression(c) for c in outputs))
    )
    # Drop the table once the relation is gone.
    weakref.finalize(out, _drop_later, con, name)
    return out

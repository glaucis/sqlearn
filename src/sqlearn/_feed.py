"""The feed: handing prepared data to a model and its predictions back.

A model the user brings (ADR 0017) is handed the prepared rows in the form
its `Model.feed` names (ADR 0041): numpy, pandas, Polars or Arrow, each
library imported only inside the hand-over that needs it, so sqlearn itself
never needs them. Text columns reach pandas, Polars and Arrow as categories.
A model that learns in pieces (``feed="stream"``) is trained the same way,
one batch at a time through its ``partial_fit``. Every prediction is
streamed: the rows go
to the model one batch at a time, and each batch's predictions are inserted
into a table in DuckDB beside the row numbers they belong to, so no step of
a prediction holds all the rows in memory.
"""

import contextlib
import functools
import importlib
import inspect
import itertools
import warnings
import weakref
from collections.abc import Callable, Generator, Mapping, Sequence
from typing import Any

import duckdb
from duckdb.sqltypes import DuckDBPyType

from sqlearn._compose import number_rows
from sqlearn._config import connection
from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn._expr import quote
from sqlearn._inputs import _drop_later
from sqlearn._memory import check
from sqlearn._model import Model, _numpy, check_feed, missing_target, target_values
from sqlearn._selectors import is_text

__all__ = [
    "BATCH_ROWS",
    "MEGABYTES",
    "PROBA",
    "ROW",
    "WrongShapeError",
    "fetch",
    "hand_over",
    "predict_streamed",
    "stream_into",
    "stream_trainer",
    "take",
    "train_streamed",
]

BATCH_ROWS = 65_536
"""How many rows streamed prediction hands the model at a time."""

MEGABYTES = 100
"""About how large a streamed training batch is when its size is not given."""

ROW = "__sqlearn_row"
"""The column numbering the rows, which the stream shuffles and sorts by."""

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
"""The column counting the target's SQL NULLs beside a pandas fetch.

Lengthened with underscores while a feature or the target has the name.
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
    sized: bool = True,
) -> tuple[Any, Any]:
    """Run a relation once: the features and the target in the feed's form.

    Every form but ``"stream"`` (one batch at a time) first estimates the
    data's size and refuses it, before fetching, when it is over what the
    memory budget leaves the hand-over: swapping is never the fallback.

    Each form comes from DuckDB's own method (``fetchnumpy``, ``df``,
    ``pl``, ``to_arrow_table``). With pandas, Polars and Arrow a text
    (``VARCHAR`` or ``ENUM``) feature is cast to that library's categories after the
    fetch (pandas ``category``, Polars ``Enum``, Arrow dictionary); a NULL
    stays missing, never a category. numpy and the stream
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
        learns its list here, recorded in it: an ``ENUM``'s declared values
        in their order, otherwise the sorted values.
        Without it, each fetch has its own sorted list.
    sized : bool, default True
        Whether to check the size first; False for a batch, small by
        construction.

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
        If `feed` is not a form, the data would not fit in memory, its
        library is not installed, the target is missing (NULL) in a row, or
        (numpy, stream) a feature is not a number.

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
    if sized and feed != "stream":
        check(connection(), rel, [*columns, *aside], feed)
    if feed in _AS_NUMPY:
        matrix, other = take(rel, feed, columns, aside)
        if target is None:
            return matrix, None
        return matrix, target_values(other[target], name or target)
    kinds = dict(zip(rel.columns, rel.types, strict=True))
    text = [c for c in columns if is_text(kinds[c])]
    known = {} if categories is None else categories
    for c in text:
        declared = _declared(kinds[c])
        if declared is not None:
            known.setdefault(c, declared)
    picks = [duckdb.ColumnExpression(c) for c in [*columns, *aside]]
    null = _NULL
    while null in (*columns, *aside):
        null += "_"  # never a feature's or the target's name
    if target is not None and feed == "pandas":
        # pandas reads NULL and NaN alike; the SQL NULLs are counted beside.
        picks.append(duckdb.ColumnExpression(target).isnull().alias(null))
    picked = rel.project(*picks)
    x: Any
    y: Any = None
    if feed == "pandas":
        pd = _library("pandas", feed)
        x = picked.df()
        missing = 0
        if target is not None:
            missing = int(x.pop(null).sum())
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
            # An Enum's codes are its list's order, kept through to_arrow
            # and to_pandas; the order holds every value of this fetch.
            x = x.with_columns(x[c].cast(pl.Enum(order)))
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


def _declared(dtype: DuckDBPyType) -> list[str] | None:
    """Return an ENUM's declared values in order, or None for other text."""
    if dtype.id != "enum":
        return None
    values = dict(dtype.children)["values"]
    return [str(v) for v in values] if isinstance(values, list) else None


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
    *,
    sized: bool,
) -> tuple[Any, Any]:
    """Fetch the features in the feed's form and the row numbers as numpy."""
    x, rows = fetch(rel, feed, columns, row, categories=categories, sized=sized)
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
    # A batch is read back from Arrow, which keeps only the values it holds:
    # an ENUM's declared list comes from the relation's type.
    for c, kind in zip(picked.columns, picked.types, strict=True):
        declared = _declared(kind)
        if declared is not None:
            known.setdefault(c, declared)
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
        # One whole fetch: it must fit, as a training fetch must.
        yield _fetched(picked, feed, columns, row, known, sized=True)
        return
    empty = True
    # Closed however the caller stops, so the connection's read is released.
    with contextlib.closing(picked.to_arrow_reader(batch_size=BATCH_ROWS)) as reader:
        for batch in reader:
            if batch.num_rows == 0:
                continue
            empty = False
            yield _fetched(
                cur.from_arrow(batch), feed, columns, row, known, sized=False
            )
    if empty:
        yield _fetched(picked, feed, columns, row, known, sized=False)


# How DuckDB names the type of a column of NULLs only.
_NULL_TYPE = '"NULL"'


def _types(cur: duckdb.DuckDBPyConnection, source: str) -> dict[str, str]:
    """Return the names and types of `source`'s columns."""
    rel = cur.sql(f"FROM {source}")
    return {c: str(t) for c, t in zip(rel.columns, rel.types, strict=True)}


def _widen(
    cur: duckdb.DuckDBPyConnection,
    table: str,
    batch: str,
    columns: Mapping[str, Any],
    model: Model,
    method: str,
) -> None:
    """Widen the table's columns to the types DuckDB gives them with a batch's.

    A column whose batch has the table's type costs nothing. Text meeting a
    number has no common type but VARCHAR, which would turn the numbers into
    text: that is refused.
    """
    have = _types(cur, table)
    new = _types(cur, quote(batch))
    for column in columns:
        old, now = have[column], new[column]
        if old == now or now == _NULL_TYPE:
            continue  # nothing new, or only NULLs, which fit any type
        if old == _NULL_TYPE:
            common = now  # earlier rows were only NULLs, which fit any type
        else:
            ((common,),) = cur.execute(
                f"SELECT typeof(x) FROM (SELECT NULL::{old} AS x "
                f"UNION ALL SELECT NULL::{now}) LIMIT 1"
            ).fetchall()
            if common == "VARCHAR" and "VARCHAR" in (old, now):
                text = (
                    f"{type(model.estimator).__name__}.{method} returned {old} "
                    f"for earlier rows and {now} for later ones, which share "
                    "no type but text. Fix: make the model return one kind "
                    "of value."
                )
                raise SqlearnError(text)
        if common != old:
            cur.execute(
                f"ALTER TABLE {table} ALTER COLUMN {quote(column)} TYPE {common}"
            )


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
                    _widen(cur, name, batch_name, arrays, model, method)
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
    front: duckdb.DuckDBPyRelation | None = None,
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
    front : duckdb.DuckDBPyRelation, optional
        Columns to hand back before the predictions: a relation of `row`
        and those columns, joined to the predictions by `row` in DuckDB.

    Returns
    -------
    duckdb.DuckDBPyRelation
        One column, ``prediction`` (or, for ``predict_proba``, one column
        per class, ``__sqlearn_proba_0``, ``__sqlearn_proba_1``, ...), one
        row per row of `rel`, sorted by `row`; after the columns of `front`
        but `row`, when given.

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
    shown = [duckdb.ColumnExpression(c) for c in outputs]
    rows = con.sql(f"FROM {name}")
    if front is not None:
        shown = [duckdb.ColumnExpression(c) for c in front.columns if c != row] + shown
        rows = front.join(rows, row)
    out = rows.order(duckdb.ColumnExpression(row)).project(*shown)
    # Drop the table once the relation is gone.
    weakref.finalize(out, _drop_later, con, name)
    return out


def _batch_rows(model: Model, columns: Sequence[str]) -> int:
    """Return how many rows each streamed training batch holds.

    `Model.rows` when given; otherwise about `Model.megabytes` (or
    `MEGABYTES`) of float64 features: ``megabytes * 1_000_000 // (8 *
    features)`` rows, at least one.
    """
    if model.rows is not None:
        return model.rows
    megabytes = MEGABYTES if model.megabytes is None else model.megabytes
    return max(1, megabytes * 1_000_000 // (8 * max(1, len(columns))))


def _sized(reader: Any, size: int) -> Generator[Any]:  # noqa: ANN401  (a pyarrow reader)
    """Yield an Arrow reader's rows as tables of exactly `size` rows.

    DuckDB's batches may stop short of the size asked for (at a chunk's
    end), so they are joined and cut: every table but the last holds
    `size` rows, the last the rest; an empty one is never yielded. Memory
    holds about two batches.
    """
    pa = importlib.import_module("pyarrow")
    held: list[Any] = []
    count = 0
    for batch in reader:
        if batch.num_rows == 0:
            continue
        held.append(batch)
        count += batch.num_rows
        if count < size:
            continue
        table = pa.Table.from_batches(held)
        start = 0
        while count - start >= size:
            yield table.slice(start, size)
            start += size
        held = table.slice(start).to_batches() if start < count else []
        count -= start
    if count:
        yield pa.Table.from_batches(held)


def _takes_classes(partial_fit: Any) -> bool:  # noqa: ANN401  (any library's method)
    """Say whether a ``partial_fit`` has a ``classes`` parameter."""
    return "classes" in inspect.signature(partial_fit).parameters


def train_streamed(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    target: str,
    model: Model,
    *,
    named: str | None = None,
) -> None:
    """Train a model one batch at a time through its ``partial_fit``.

    Each epoch reads the rows from DuckDB as Arrow batches and hands each
    one to ``partial_fit(X, y)`` as numpy, so memory holds one batch, never
    all the rows. With ``shuffle=True`` epoch ``e`` streams the rows in the
    order of ``hash(row, seed, e)``, a new order each epoch and the same
    orders for the same seed; with ``shuffle=False`` in the input's order.
    The rows are numbered (`ROW`) in the order read unless `rel` already
    has the column, as a search's fold does. When ``partial_fit`` has a
    ``classes`` parameter, its first call is given the sorted distinct
    non-NULL target values, computed in SQL. A batch holds `Model.rows`
    rows, or about `Model.megabytes` (by default `MEGABYTES`) of float64
    features: ``max(1, megabytes * 1_000_000 // (8 * len(columns)))`` rows.
    Everything that can be refused is refused before the first call (see
    `stream_trainer`).

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection `rel` belongs to.
    rel : duckdb.DuckDBPyRelation
        The prepared rows, with every column of `columns` and `target`.
    columns : sequence of str
        The features, in order.
    target : str
        The target's column.
    model : Model
        The model; its stream settings (`Model.rows`, `Model.megabytes`,
        `Model.epochs`, `Model.shuffle`, `Model.seed`) size and order the
        batches.
    named : str, optional
        The target's name in the user's data, for the messages; `target`
        when not given.

    Raises
    ------
    SqlearnError
        As for `stream_trainer`.

    Examples
    --------
    >>> from sklearn.linear_model import SGDRegressor
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import train_streamed
    >>> con = connection()
    >>> rel = con.sql("SELECT i::DOUBLE AS a, 2 * i AS y FROM range(10) t(i)")
    >>> model = sq.Model(SGDRegressor(), feed="stream", rows=4)
    >>> train_streamed(con, rel, ["a"], "y", model)
    >>> int(model.estimator.t_)
    11
    """
    stream_trainer(con, rel, columns, target, model, named=named)()


def stream_trainer(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    target: str,
    model: Model,
    *,
    named: str | None = None,
) -> Callable[[], None]:
    """Check what the stream needs, then return the training to run.

    `train_streamed` in two parts, so that a caller can tell a refusal,
    which leaves the model as it was, from a ``partial_fit`` that failed
    and may have half changed it.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The connection `rel` belongs to.
    rel : duckdb.DuckDBPyRelation
        The prepared rows, with every column of `columns` and `target`.
    columns : sequence of str
        The features, in order.
    target : str
        The target's column.
    model : Model
        The model, with the stream's settings.
    named : str, optional
        The target's name in the user's data, for the messages; `target`
        when not given.

    Returns
    -------
    callable
        Takes nothing; streams every epoch through ``partial_fit``.

    Raises
    ------
    SqlearnError
        If the model has no ``partial_fit``, pyarrow is not installed (the
        rows cannot be streamed without it, and fetching them whole would
        defeat the stream), a feature is not a number, the target is
        missing (NULL) in a row, or there are no rows.

    Examples
    --------
    >>> from sklearn.linear_model import SGDRegressor
    >>> import sqlearn as sq
    >>> from sqlearn._config import connection
    >>> from sqlearn._feed import stream_trainer
    >>> con = connection()
    >>> rel = con.sql("SELECT i::DOUBLE AS a, 2 * i AS y FROM range(10) t(i)")
    >>> model = sq.Model(SGDRegressor(), feed="stream", epochs=2)
    >>> train = stream_trainer(con, rel, ["a"], "y", model)
    >>> hasattr(model.estimator, "t_")
    False
    >>> train()
    >>> int(model.estimator.t_)
    21
    """
    name = named if named is not None else target
    partial_fit = getattr(model.estimator, "partial_fit", None)
    if not callable(partial_fit):
        msg = (
            f"feed='stream' trains the model through partial_fit one batch at "
            f"a time, and a {type(model.estimator).__name__} has no "
            "partial_fit: it learns from all the rows at once. Fix: pass "
            "another feed, such as feed='numpy', or a model that learns in "
            "pieces, such as sklearn.linear_model.SGDClassifier()."
        )
        raise SqlearnError(msg)
    try:
        import pyarrow  # noqa: F401  (only to know it is there)
    except ImportError as exc:
        msg = (
            "feed='stream' reads the training rows from DuckDB in batches "
            "through pyarrow, and pyarrow is not installed; fetching all the "
            "rows at once would defeat the stream. Fix: install pyarrow (uv "
            "add pyarrow), or pass another feed, such as feed='numpy'."
        )
        raise SqlearnError(msg) from exc
    np = _numpy()
    take(rel.limit(0), "stream", columns)  # refuses text before any batch
    if ROW not in rel.columns:
        rel = con.sql(number_rows(rel.sql_query(), ROW))
    answer = duckdb.ColumnExpression(target)
    counted = rel.aggregate(
        [
            duckdb.FunctionExpression("count_star"),
            duckdb.FunctionExpression("count", answer),
        ]
    ).fetchall()[0]
    rows, known = int(counted[0]), int(counted[1])
    if rows == 0:
        msg = (
            "there are no rows to train on, so partial_fit would never be "
            "called and the model would learn nothing. Fix: pass data with "
            "rows."
        )
        raise SqlearnError(msg)
    if known < rows:
        raise missing_target(name, rows - known)
    first: dict[str, Any] = {}
    if _takes_classes(partial_fit):
        distinct = rel.project(answer).distinct().order(target)
        first["classes"] = np.ma.getdata(distinct.fetchnumpy()[target])
    return functools.partial(
        _stream_epochs, con, rel, columns, target, model,
        name=name, first=first,
    )  # fmt: skip


def _stream_epochs(
    con: duckdb.DuckDBPyConnection,
    rel: duckdb.DuckDBPyRelation,
    columns: Sequence[str],
    target: str,
    model: Model,
    *,
    name: str,
    first: dict[str, Any],
) -> None:
    """Stream every epoch's batches of `rel` (numbered) through ``partial_fit``.

    `first` holds the first call's extra arguments (``classes=``).
    """
    partial_fit = model.estimator.partial_fit
    size = _batch_rows(model, columns)
    row = duckdb.ColumnExpression(ROW)
    picks = [duckdb.ColumnExpression(c) for c in [*columns, target]]
    extra = first
    cur = con.cursor()
    try:
        for epoch in range(model.epochs):
            order = [row]
            if model.shuffle:
                shuffled = duckdb.FunctionExpression(
                    "hash",
                    row,
                    duckdb.ConstantExpression(model.seed),
                    duckdb.ConstantExpression(epoch),
                )
                order = [shuffled, row]
            picked = rel.sort(*order).project(*picks)
            reader = picked.to_arrow_reader(batch_size=size)
            with contextlib.closing(reader):
                for batch in _sized(reader, size):
                    x, y = fetch(
                        cur.from_arrow(batch), "stream", columns, target, named=name
                    )
                    partial_fit(x, y, **extra)
                    extra = {}  # classes= on the very first call only
    finally:
        cur.close()

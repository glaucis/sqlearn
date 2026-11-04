"""Models from other libraries: the wrapper, copying it, and the hand-over.

sqlearn prepares the data in DuckDB and hands it to a model the user brings
(ADR 0017): any object with scikit-learn's ``fit`` and ``predict``. numpy is
imported only inside the numpy hand-over, so sqlearn itself never needs it.
"""

import contextlib
import copy
import itertools
import weakref
from collections.abc import Sequence
from typing import Any

import duckdb

from sqlearn._errors import SqlearnError

__all__ = [
    "FEEDS",
    "Model",
    "as_model",
    "check_feed",
    "copy_model",
    "hand_over",
    "is_model",
    "received",
    "take",
    "target_values",
]

FEEDS = ("numpy",)
"""The forms data can be handed to a model in, in the core."""

_ISSUE_21 = "https://github.com/glaucis/sqlearn/issues/21"


def check_feed(feed: str) -> None:
    """Refuse a form of hand-over that is not built yet.

    Parameters
    ----------
    feed : str
        The form asked for.

    Raises
    ------
    SqlearnError
        If `feed` is not ``"numpy"``; Arrow and batches are planned in issue
        #21.

    Examples
    --------
    >>> from sqlearn._model import check_feed
    >>> check_feed("numpy")
    """
    if feed not in FEEDS:
        msg = (
            f"feed={feed!r} is not built yet: sqlearn hands models numpy only "
            f"for now. Arrow and batches are planned in issue #21 ({_ISSUE_21}). "
            "Fix: use feed='numpy'."
        )
        raise SqlearnError(msg)


def _missing(obj: object) -> list[str]:
    return [m for m in ("fit", "predict") if not callable(getattr(obj, m, None))]


def is_model(obj: object) -> bool:
    """Say whether an object is a model: a `Model`, or one with fit and predict.

    Parameters
    ----------
    obj : object
        The object.

    Returns
    -------
    bool
        True for a model.

    Examples
    --------
    >>> from sklearn.linear_model import LogisticRegression
    >>> from sqlearn._model import is_model
    >>> is_model(LogisticRegression()), is_model(object())
    (True, False)
    """
    return isinstance(obj, Model) or not _missing(obj)


class Model:
    """A model from another library, with sqlearn's settings for it.

    Any object with scikit-learn's ``fit`` and ``predict`` is a model. A
    pipeline wraps a plain one as ``Model(estimator)`` itself; wrap it to
    choose how data is handed to it.

    Parameters
    ----------
    estimator : object
        The model: an object with ``fit(X, y)`` and ``predict(X)``.
    feed : str, default "numpy"
        The form the prepared data is handed over in. Only ``"numpy"`` is
        built (a 2-D float64 array); other forms are issue #21.

    Attributes
    ----------
    estimator : object
        The model, as given; `Pipeline.train` fits it in place.
    feed : str
        The form of the hand-over.

    Raises
    ------
    SqlearnError
        If the estimator lacks ``fit`` or ``predict``, or `feed` is not built.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sklearn.linear_model import LogisticRegression
    >>> sq.Model(LogisticRegression(C=0.1))
    Model(LogisticRegression(C=0.1), feed='numpy')
    """

    def __init__(self, estimator: object, feed: str = "numpy") -> None:
        missing = _missing(estimator)
        if missing:
            msg = (
                f"a {type(estimator).__name__} is not a model: it has no "
                f"{' and no '.join(missing)}. A model needs fit(X, y) and "
                "predict(X), as scikit-learn's do. Fix: pass a model, such as "
                "sklearn.linear_model.LogisticRegression()."
            )
            raise SqlearnError(msg)
        check_feed(feed)
        self.estimator: Any = estimator
        self.feed = feed

    def __repr__(self) -> str:
        """Show the estimator's own repr and the feed, the same every time.

        Returns
        -------
        str
            ``Model(<estimator repr>, feed='numpy')``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> repr(sq.Model(LogisticRegression()))
        "Model(LogisticRegression(), feed='numpy')"
        """
        return f"Model({self.estimator!r}, feed={self.feed!r})"


def as_model(obj: object) -> Model:
    """Return a model wrapped in `Model`; a `Model` is returned as it is.

    Parameters
    ----------
    obj : object
        A `Model`, or an object with ``fit`` and ``predict``.

    Returns
    -------
    Model
        The model.

    Raises
    ------
    SqlearnError
        If `obj` has no ``fit`` or no ``predict``.

    Examples
    --------
    >>> from sklearn.linear_model import LogisticRegression
    >>> from sqlearn._model import as_model
    >>> as_model(LogisticRegression()).feed
    'numpy'
    """
    if isinstance(obj, Model):
        return obj
    return Model(obj)


def _clone(estimator: Any) -> Any:  # noqa: ANN401  (any library's model)
    """Copy a model unfitted, as scikit-learn's ``clone`` does."""
    get_params = getattr(estimator, "get_params", None)
    if isinstance(estimator, type) or not callable(get_params):
        # A class given as a setting is a setting, not a model: copied as is.
        return copy.deepcopy(estimator)
    try:
        params = get_params(deep=False)
    except TypeError:
        params = get_params()
    return type(estimator)(**{k: _clone(v) for k, v in params.items()})


def copy_model(m: Model) -> Model:
    """Copy a model with its settings, unfitted, keeping its feed.

    Follows scikit-learn's ``clone``: when the estimator has ``get_params``,
    a new one is built from its settings (``type(e)(**e.get_params())``);
    otherwise it is copied with `copy.deepcopy`.

    Parameters
    ----------
    m : Model
        The model to copy.

    Returns
    -------
    Model
        A new model with the same settings and feed.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sklearn.linear_model import LogisticRegression
    >>> from sqlearn._model import copy_model
    >>> copy_model(sq.Model(LogisticRegression(C=0.1)))
    Model(LogisticRegression(C=0.1), feed='numpy')
    """
    return Model(_clone(m.estimator), feed=m.feed)


def _numpy() -> Any:  # noqa: ANN401  (the numpy module, imported here only)
    try:
        import numpy as np
    except ImportError as exc:
        msg = (
            "feed='numpy' hands the data to the model as a numpy array, and "
            "numpy is not installed. Fix: install numpy (uv add numpy)."
        )
        raise SqlearnError(msg) from exc
    return np


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
    >>> from sqlearn._model import take
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
                "(sq.OneHot or sq.Ordinal), or leave it out of the data."
            )
            raise SqlearnError(msg)
        x[:, j] = np.ma.filled(np.ma.asarray(values).astype(np.float64), np.nan)
    return x, {c: arrays[c] for c in aside}


def target_values(values: Any, name: str) -> Any:  # noqa: ANN401  (numpy arrays)
    """Return the target as a plain numpy array, refusing missing values.

    Parameters
    ----------
    values : numpy.ndarray
        The target column as fetched (a masked array where it held NULL).
    name : str
        The target's name, for the message.

    Returns
    -------
    numpy.ndarray
        The values.

    Raises
    ------
    SqlearnError
        If a value is missing (NULL): a model learns only from known answers.

    Examples
    --------
    >>> import numpy as np
    >>> from sqlearn._model import target_values
    >>> target_values(np.array([0, 1]), "churned").tolist()
    [0, 1]
    """
    np = _numpy()
    missing = int(np.ma.count_masked(values))
    if missing:
        msg = (
            f"the target {name!r} is missing in {missing} row(s); a model "
            "learns only from rows whose answer is known. Fix: leave those "
            "rows out of the data passed to train."
        )
        raise SqlearnError(msg)
    return np.ma.getdata(values)


_prediction_ids = itertools.count()


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
    >>> from sqlearn._model import received
    >>> rel = received(connection(), np.array([2, 1]), np.array(["b", "a"]))
    >>> rel.fetchall()
    [('a',), ('b',)]
    """
    np = _numpy()
    values = np.asarray(predicted)
    if values.ndim != 1 or len(values) != len(rows):
        msg = (
            f"the model's predict returned an array of shape {values.shape}, "
            f"not one value for each of the {len(rows)} rows; sqlearn returns "
            "one column, prediction. Fix: use a model whose predict returns "
            "one value per row."
        )
        raise SqlearnError(msg)
    name = f"_sqlearn_predictions_{next(_prediction_ids)}"
    con.register(name, {"row": np.ma.getdata(rows), "prediction": values})
    rel = (
        con.table(name)
        .order(duckdb.ColumnExpression("row"))
        .project(duckdb.ColumnExpression("prediction"))
    )
    # Release the registration (and the arrays) once the relation is gone.
    weakref.finalize(rel, _unregister, con, name)
    return rel


def _unregister(con: duckdb.DuckDBPyConnection, name: str) -> None:
    with contextlib.suppress(duckdb.Error):
        con.unregister(name)


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
    >>> from sqlearn._model import hand_over
    >>> hand_over(connection().sql("SELECT 1 AS a, 2.5 AS b"), "numpy").tolist()
    [[1.0, 2.5]]
    """
    x, _ = take(rel, feed, rel.columns)
    return x

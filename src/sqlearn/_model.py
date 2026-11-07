"""Models from other libraries: the wrapper and copying it.

sqlearn prepares the data in DuckDB and hands it to a model the user brings
(ADR 0017): any object with scikit-learn's ``fit`` and ``predict``. The
hand-over itself is in `sqlearn._feed`; numpy, pandas, Polars and pyarrow
are imported only inside the functions that need them, so sqlearn itself
never needs them.
"""

import copy
from typing import Any

from sqlearn._errors import SqlearnError

__all__ = [
    "FEEDS",
    "Model",
    "as_model",
    "check_feed",
    "copy_model",
    "is_model",
    "missing_target",
    "refuse_stream",
    "target_values",
]

FEEDS = ("numpy", "pandas", "polars", "arrow", "stream")
"""The forms data can be handed to a model in (ADR 0041)."""

_STREAM_DEFAULTS: dict[str, object] = {
    "rows": None,
    "megabytes": None,
    "epochs": 1,
    "shuffle": True,
    "seed": 0,
}
"""The stream's settings and their defaults, in `Model`'s order."""


def check_feed(feed: str) -> None:
    """Refuse a form of hand-over sqlearn does not know.

    Parameters
    ----------
    feed : str
        The form asked for.

    Raises
    ------
    SqlearnError
        If `feed` is not one of `FEEDS`.

    Examples
    --------
    >>> from sqlearn._model import check_feed
    >>> check_feed("polars")
    """
    if feed not in FEEDS:
        msg = (
            f"feed={feed!r} is not a form sqlearn hands data to a model in; "
            f"the forms are {', '.join(FEEDS)}. Fix: pass feed= one of them, "
            "or leave it out for numpy."
        )
        raise SqlearnError(msg)


def refuse_stream(feed: str) -> None:
    """Refuse to train through the stream, which is not built yet.

    Parameters
    ----------
    feed : str
        The form a model is to be trained in.

    Raises
    ------
    SqlearnError
        If `feed` is ``"stream"``: training through ``partial_fit`` is
        planned in issue #21.

    Examples
    --------
    >>> from sqlearn._model import refuse_stream
    >>> refuse_stream("pandas")
    """
    if feed == "stream":
        msg = (
            "feed='stream' trains the model through partial_fit one batch at "
            "a time, which is not built yet "
            "(https://github.com/glaucis/sqlearn/issues/21). Fix: pass another "
            "feed for now, such as feed='numpy'."
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
    choose the form the data is handed to it in (ADR 0041). Each form's
    library is imported only when it is used, and none is a dependency of
    sqlearn: install the one your model reads.

    ============  ===========================  ===================
    ``feed=``     ``fit(X, y)`` gets           text columns
    ============  ===========================  ===================
    ``"numpy"``   a 2-D float64 array          refused
    ``"pandas"``  a ``DataFrame``              ``category`` dtype
    ``"polars"``  a ``DataFrame``              ``Enum``
    ``"arrow"``   a ``pyarrow.Table``          dictionary-encoded
    ``"stream"``  batches as numpy, through    refused
                  ``partial_fit``
    ============  ===========================  ===================

    The target goes over in the same form as the features: a numpy array, a
    pandas or Polars ``Series``, a ``pyarrow.ChunkedArray``. A NULL stays
    missing (NaN or null), never a category of its own. Predictions are
    asked for in the same form, one batch at a time; a text column's
    categories are those of the training rows, sorted, with values new at
    predict after them, so each value keeps its code.

    Parameters
    ----------
    estimator : object
        The model: an object with ``fit(X, y)`` and ``predict(X)``.
    feed : {"numpy", "pandas", "polars", "arrow", "stream"}, default "numpy"
        The form the prepared data is handed over in, as in the table above.
    rows : int, optional
        With ``feed="stream"`` only: the rows in each batch.
    megabytes : int, optional
        With ``feed="stream"`` only: about how large each batch is; about
        100 MB when neither this nor `rows` is given.
    epochs : int, default 1
        With ``feed="stream"`` only: how many times the rows are streamed.
    shuffle : bool, default True
        With ``feed="stream"`` only: whether each epoch streams the rows in
        a new order.
    seed : int, default 0
        With ``feed="stream"`` only: the seed of that order.

    Attributes
    ----------
    estimator : object
        The model, as given; `Pipeline.train` fits it in place.
    feed : str
        The form of the hand-over.
    rows, megabytes, epochs, shuffle, seed
        The stream's settings, as given.

    Raises
    ------
    SqlearnError
        If the estimator lacks ``fit`` or ``predict``, `feed` is not a form,
        or a setting of the stream is given with another feed.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sklearn.linear_model import LogisticRegression
    >>> sq.Model(LogisticRegression(C=0.1))
    Model(LogisticRegression(C=0.1))
    >>> sq.Model(LogisticRegression(), feed="pandas")
    Model(LogisticRegression(), feed='pandas')
    """

    def __init__(
        self,
        estimator: object,
        feed: str = "numpy",
        *,
        rows: int | None = None,
        megabytes: int | None = None,
        epochs: int = 1,
        shuffle: bool = True,
        seed: int = 0,
    ) -> None:
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
        stream = {
            "rows": rows,
            "megabytes": megabytes,
            "epochs": epochs,
            "shuffle": shuffle,
            "seed": seed,
        }
        if feed != "stream":
            for name, value in stream.items():
                if value != _STREAM_DEFAULTS[name]:
                    msg = (
                        f"{name}={value!r} is a setting of the stream, and "
                        f"feed={feed!r} hands the rows over at once, not in "
                        f"batches. Fix: pass feed='stream' with {name}=, or "
                        f"leave {name}= out."
                    )
                    raise SqlearnError(msg)
        self.estimator: Any = estimator
        self.feed = feed
        self.rows = rows
        self.megabytes = megabytes
        self.epochs = epochs
        self.shuffle = shuffle
        self.seed = seed

    def _settings(self) -> dict[str, Any]:
        """Return the feed and the stream's settings, to build a copy with."""
        return {"feed": self.feed, **{n: getattr(self, n) for n in _STREAM_DEFAULTS}}

    def __repr__(self) -> str:
        """Show the estimator's own repr and what differs from the defaults.

        Returns
        -------
        str
            ``Model(<estimator repr>)``, then each setting not at its
            default, in the signature's order.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> repr(sq.Model(LogisticRegression(), feed="stream", rows=500))
        "Model(LogisticRegression(), feed='stream', rows=500)"
        """
        defaults = {"feed": "numpy", **_STREAM_DEFAULTS}
        shown = [
            f"{name}={value!r}"
            for name, value in self._settings().items()
            if value != defaults[name]
        ]
        return f"Model({', '.join([repr(self.estimator), *shown])})"


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
    >>> copy_model(sq.Model(LogisticRegression(C=0.1), feed="polars"))
    Model(LogisticRegression(C=0.1), feed='polars')
    """
    return Model(_clone(m.estimator), **m._settings())


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
        raise missing_target(name, missing)
    return np.ma.getdata(values)


def missing_target(name: str, missing: int) -> SqlearnError:
    """Return the error for a target missing (NULL) in some rows.

    Parameters
    ----------
    name : str
        The target's name.
    missing : int
        How many rows lack it.

    Returns
    -------
    SqlearnError
        The error, to raise.

    Examples
    --------
    >>> from sqlearn._model import missing_target
    >>> str(missing_target("churned", 2)).split(";")[0]
    "the target 'churned' is missing in 2 row(s)"
    """
    msg = (
        f"the target {name!r} is missing in {missing} row(s); a model "
        "learns only from rows whose answer is known. Fix: leave those "
        "rows out of the data passed to train."
    )
    return SqlearnError(msg)

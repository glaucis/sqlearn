"""Methods of the search: how settings are picked, through ask and tell.

A method is started on a search space, asked for settings until it answers
None, and told each setting's score (ADR 0022). Grid knows every setting up
front; a method that picks one at a time from the scores so far (Optuna)
says so with ``knows_all = False``. `trial` applies one setting to a copy
of a pipeline, refusing a setting that names nothing.
"""

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlearn._errors import SqlearnError
from sqlearn._model import Model, _clone, as_model, copy_model, is_model
from sqlearn._pipeline import Pipeline
from sqlearn._step import Step

__all__ = ["Grid", "Method", "Range", "range", "trial"]

Params = dict[str, Any]
"""One setting: values keyed ``step__setting`` (or ``"model"``)."""


@dataclass(frozen=True)
class Range:
    """A span of numbers to search, for methods that draw from it.

    Attributes
    ----------
    low : float
        The lowest value.
    high : float
        The highest value.
    log : bool
        Whether values are drawn on a log scale.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.search.range(0.01, 10, log=True)
    Range(low=0.01, high=10, log=True)
    """

    low: float
    high: float
    log: bool = False


def range(low: float, high: float, log: bool = False) -> Range:
    """Return a span of numbers to search, from `low` to `high`.

    Grid cannot use one (it tries lists of values); methods that draw values
    (random, Optuna) can.

    Parameters
    ----------
    low : float
        The lowest value.
    high : float
        The highest value.
    log : bool, default False
        Draw on a log scale; `low` must then be above zero.

    Returns
    -------
    Range
        The span.

    Raises
    ------
    SqlearnError
        If `low` is above `high`, or `log` is True and `low` is not above 0.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.search.range(1, 5).high
    5
    """
    if low > high:
        msg = (
            f"sq.search.range got low={low!r} above high={high!r}; a range runs from "
            "low to high. Fix: swap them."
        )
        raise SqlearnError(msg)
    if log and low <= 0:
        msg = (
            f"sq.search.range got log=True with low={low!r}; a log scale starts above "
            "zero. Fix: pass a low above 0, or log=False."
        )
        raise SqlearnError(msg)
    return Range(low, high, log)


@runtime_checkable
class Method(Protocol):
    """How a search picks settings: start, ask, tell.

    Attributes
    ----------
    knows_all : bool
        True when every setting is known up front (grid, random), so the
        search can loop fold first; False when settings are picked one at a
        time from the scores so far.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sqlearn.model_selection.methods import Method
    >>> isinstance(sq.search.grid(), Method)
    True
    """

    knows_all: bool

    def start(self, space: list[Params]) -> None:
        """Begin a search over a space: one dict of settings per grid.

        Parameters
        ----------
        space : list of dict
            Settings keyed ``step__setting``, each to a list or a range.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().start([{"model__C": [0.1, 1]}])
        """

    def ask(self) -> Params | None:
        """Return the next setting to try, or None when done.

        Returns
        -------
        dict or None
            The setting.

        Examples
        --------
        >>> import sqlearn as sq
        >>> grid = sq.search.grid()
        >>> grid.start([{"model__C": [0.1]}])
        >>> grid.ask()
        {'model__C': 0.1}
        """

    def tell(self, params: Params, score: float) -> None:
        """Report a setting's score (its mean over the folds).

        Parameters
        ----------
        params : dict
            The setting, as `ask` returned it.
        score : float
            Its score.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().tell({"model__C": 0.1}, 0.8)
        """


def _values(name: str, values: object) -> Sequence[object]:
    """Return a grid setting's values, refusing what grid cannot try."""
    if isinstance(values, Range):
        msg = (
            f"Grid got {name!r}: {values!r}, made with sq.search.range; a grid tries "
            "a list of values and cannot draw from a range. Fix: list the "
            f"values ({name!r}: [0.1, 1, 10]), or use a method that draws "
            "from ranges."
        )
        raise SqlearnError(msg)
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        msg = (
            f"Grid got {name!r}: {values!r}, a single value; a grid tries a "
            f"list of values per setting. Fix: write {name!r}: [{values!r}]."
        )
        raise SqlearnError(msg)
    if not values:
        msg = (
            f"Grid got {name!r}: an empty list, so there is no value to try. "
            "Fix: list at least one value, or leave the setting out."
        )
        raise SqlearnError(msg)
    return values


class Grid:
    """Try every combination of the listed values, as scikit-learn's grid.

    Each dict of the space is expanded as scikit-learn's ``ParameterGrid``
    does: its settings sorted by name, the last varying fastest; the dicts
    one after another.

    Attributes
    ----------
    knows_all : bool
        True: the grid knows every setting up front.
    scores_ : list of (dict, float)
        Each setting told, with its score, in the order told.

    Examples
    --------
    >>> import sqlearn as sq
    >>> grid = sq.search.grid()
    >>> grid.start([{"model__C": [0.1, 1]}])
    >>> grid.ask(), grid.ask(), grid.ask()
    ({'model__C': 0.1}, {'model__C': 1}, None)
    """

    knows_all = True

    def __init__(self) -> None:
        self._settings: list[Params] = []
        self._next = 0
        self.scores_: list[tuple[Params, float]] = []

    def __repr__(self) -> str:
        """Show the method.

        Returns
        -------
        str
            ``Grid()``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.search.grid())
        'Grid()'
        """
        return "Grid()"

    def start(self, space: list[Params]) -> None:
        """Expand the space into its settings, refusing what grid cannot try.

        Parameters
        ----------
        space : list of dict
            One dict per grid, each setting to a list of values.

        Raises
        ------
        SqlearnError
            If a setting is a range (`sq.search.range`), a single value or an empty
            list.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().start([{"model__C": [1]}])
        """
        settings: list[Params] = []
        for grid in space:
            names = sorted(grid)
            values = [_values(n, grid[n]) for n in names]
            settings.extend(
                dict(zip(names, combo, strict=True))
                for combo in itertools.product(*values)
            )
        self._settings = settings
        self._next = 0
        self.scores_ = []

    def ask(self) -> Params | None:
        """Return the next setting in grid order, or None after the last.

        Returns
        -------
        dict or None
            The setting.

        Examples
        --------
        >>> import sqlearn as sq
        >>> grid = sq.search.grid()
        >>> grid.start([{}])
        >>> grid.ask()
        {}
        """
        if self._next >= len(self._settings):
            return None
        params = self._settings[self._next]
        self._next += 1
        return dict(params)

    def tell(self, params: Params, score: float) -> None:
        """Record a setting's score; grid does not use it to choose.

        Parameters
        ----------
        params : dict
            The setting.
        score : float
            Its score.

        Examples
        --------
        >>> import sqlearn as sq
        >>> grid = sq.search.grid()
        >>> grid.tell({"model__C": 1}, 0.5)
        >>> grid.scores_
        [({'model__C': 1}, 0.5)]
        """
        self.scores_.append((params, score))


_FIX = "Fix: write settings as step__setting, such as 'model__C'"


def _set_on_model(model: Model, key: str, name: str, value: object) -> None:
    """Set one setting on a copied model, refusing one it does not have.

    A model with ``get_params`` is checked against its keys and set with
    ``set_params`` (the value copied, as scikit-learn's search does); any
    other is checked and set as an attribute.
    """
    est = model.estimator
    setting = key.partition("__")[2]
    get_params = getattr(est, "get_params", None)
    have = list(get_params()) if callable(get_params) else None
    if (setting not in have) if have is not None else not hasattr(est, setting):
        listed = f"; its settings are {', '.join(have)}" if have else ""
        msg = (
            f"Search got the setting {key!r}, but {type(est).__name__} (the "
            f"model, {name!r}) has no setting {setting!r}{listed}. A model is "
            "searched over its own settings. Fix: correct the name, or put "
            "settings only one model has in that model's own grid."
        )
        raise SqlearnError(msg)
    if have is not None:
        est.set_params(**{setting: _clone(value)})
    else:
        setattr(est, setting, _clone(value))


def _parse(
    pipe: Pipeline, params: Params
) -> tuple[object, dict[str, Any], dict[str, dict[str, Any]]]:
    """Sort a setting's keys into the candidate model, its values, step values."""
    names = [n for n, _ in pipe.steps]
    model_name = names[-1]
    candidate: object = pipe.steps[-1][1]
    model_values: dict[str, Any] = {}
    step_values: dict[str, dict[str, Any]] = {n: {} for n in names}
    for key, value in params.items():
        name, sep, setting = key.partition("__")
        if name not in names:
            msg = (
                f"Search got the setting {key!r}, but the pipeline has no step "
                f"named {name!r}; its steps are {', '.join(names)}. {_FIX}."
            )
            raise SqlearnError(msg)
        if name == model_name and not sep:
            if not is_model(value):
                msg = (
                    f"Search got {key!r}: {value!r}, which is not a model (one "
                    "with fit and predict). Fix: list models, such as "
                    "[LogisticRegression(), DecisionTreeClassifier()]."
                )
                raise SqlearnError(msg)
            candidate = value
        elif not sep:
            msg = (
                f"Search got the setting {key!r}, which names a whole step; "
                f"only the model ({model_name!r}) can be replaced whole, and a "
                f"step is searched over its settings. {_FIX}."
            )
            raise SqlearnError(msg)
        elif name == model_name:
            model_values[key] = value
        else:
            step_values[name][setting] = value
    return candidate, model_values, step_values


def trial(pipe: Pipeline, params: Params) -> Pipeline:
    """Return a copy of the pipeline with one setting applied.

    Steps are rebuilt from their settings (``type(step)(**settings)``), the
    model is copied unfitted (`sqlearn._model.copy_model`); the user's
    pipeline is never changed.

    Parameters
    ----------
    pipe : Pipeline
        The user's pipeline, ending in a model.
    params : dict
        Values keyed ``step__setting``; the model's own name (``"model"``)
        alone replaces the model.

    Returns
    -------
    Pipeline
        The copy.

    Raises
    ------
    SqlearnError
        If a key names no step, a step or model lacks the setting, a step is
        replaced whole, or a candidate model is not a model.

    Examples
    --------
    >>> import sqlearn as sq
    >>> from sklearn.linear_model import LogisticRegression
    >>> from sqlearn.model_selection.methods import trial
    >>> pipe = sq.Pipeline(
    ...     [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    ... )
    >>> copy = trial(pipe, {"model__C": 0.1, "scale__keep": True})
    >>> copy["model"].C, copy["scale"].keep, pipe["scale"].keep
    (0.1, True, False)
    """
    candidate, model_values, step_values = _parse(pipe, params)
    steps: list[tuple[str, Step | object]] = []
    for position, (name, step) in enumerate(pipe.steps[:-1], start=1):
        if not isinstance(step, Step):  # pragma: no cover  (_modelled refused it)
            raise TypeError(name)
        settings = step.settings()
        for setting in step_values[name]:
            if setting not in settings:
                msg = (
                    f"Search got the setting {f'{name}__{setting}'!r}, but "
                    f"{type(step).__name__} (step {position}, {name!r}) has no "
                    f"setting {setting!r}; its settings are "
                    f"{', '.join(settings)}. Fix: correct the name."
                )
                raise SqlearnError(msg)
            if isinstance(settings[setting], Mapping):
                msg = (
                    f"Search got the setting {f'{name}__{setting}'!r}, but "
                    f"{name!r} (step {position}) gives each column its own "
                    f"{setting} with a dict ({settings[setting]!r}). Why: a "
                    "dict step is one step, so a search cannot change one "
                    f"column's {setting} apart from the others'. Fix: use one "
                    f"step per column, each with its own {setting}, and "
                    f"search each step's {setting}."
                )
                raise SqlearnError(msg)
        rebuilt: dict[str, Any] = {**settings, **step_values[name]}
        steps.append((name, type(step)(**rebuilt)))
    model_name = pipe.steps[-1][0]
    model = copy_model(as_model(candidate))
    for key, value in model_values.items():
        _set_on_model(model, key, model_name, value)
    # As given: a plain model stays plain, so pipe["model"].coef_ reads.
    steps.append(
        (model_name, model if isinstance(candidate, Model) else model.estimator)
    )
    return Pipeline(steps)

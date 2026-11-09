"""Methods of the search: how settings are picked, through ask and tell.

A method is started on a search space, asked for settings until it answers
None, and told each setting's score (ADR 0022). Grid knows every setting up
front; a method that picks one at a time from the scores so far (Optuna)
says so with ``knows_all = False``. `trial` applies one setting to a copy
of a pipeline, refusing a setting that names nothing.
"""

import builtins
import contextlib
import inspect
import itertools
import math
import numbers
import random as _random
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sqlearn._errors import SqlearnError
from sqlearn._model import Model, _clone, as_model, copy_model, is_model
from sqlearn._pipeline import Pipeline
from sqlearn._step import Step

__all__ = ["Grid", "Method", "Optuna", "Random", "Range", "range", "trial"]

if TYPE_CHECKING:
    import optuna
    from optuna.samplers import BaseSampler

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

    def start(self, space: list[Params], *, maximize: bool) -> None:
        """Begin a search over a space: one dict of settings per grid.

        Parameters
        ----------
        space : list of dict
            Settings keyed ``step__setting``, each to a list or a range.
        maximize : bool
            True when a higher score is better (the metric's
            ``greater_is_better``), so a method steering by the scores
            knows which way to go.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().start([{"model__C": [0.1, 1]}], maximize=True)
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
        >>> grid.start([{"model__C": [0.1]}], maximize=True)
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
            Its score. For a method that picks one setting at a time
            (``knows_all`` false), it is NaN when evaluating the setting
            raised; the error is re-raised right after and nothing more is
            asked. A method that knows every setting up front gets no NaN
            tell on a failure.

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
    >>> grid.start([{"model__C": [0.1, 1]}], maximize=True)
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

    def start(self, space: list[Params], *, maximize: bool) -> None:
        """Expand the space into its settings, refusing what grid cannot try.

        Parameters
        ----------
        space : list of dict
            One dict per grid, each setting to a list of values.
        maximize : bool
            Whether a higher score is better; the grid tries every setting
            either way.

        Raises
        ------
        SqlearnError
            If a setting is a range (`sq.search.range`), a single value or an empty
            list.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.grid().start([{"model__C": [1]}], maximize=True)
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
        >>> grid.start([{}], maximize=True)
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


class Random:
    """Try a fixed number of settings drawn at random.

    Each draw picks one grid of the space uniformly, then each setting of
    it: a list gives one of its values uniformly; a `sq.search.range` gives
    a number uniformly (log-uniformly with ``log=True``), an integer when
    both bounds are integers. The draws are fixed by `seed`.

    Parameters
    ----------
    trials : int, default 50
        The number of settings to draw, at least 1.
    seed : int, default 0
        Seeds the draws.

    Attributes
    ----------
    knows_all : bool
        True: the draws are made at `start`.
    scores_ : list of (dict, float)
        Each setting told, with its score, in the order told.

    Raises
    ------
    SqlearnError
        If `trials` is not a whole number (a bool among them) or is below 1.

    Examples
    --------
    >>> import sqlearn as sq
    >>> method = sq.search.random(trials=2, seed=0)
    >>> method.start([{"model__depth": sq.search.range(1, 9)}], maximize=True)
    >>> sorted(method.ask()), method.ask() is not None, method.ask()
    (['model__depth'], True, None)
    """

    knows_all = True

    def __init__(self, trials: int = 50, seed: int = 0) -> None:
        _check_trials("random", trials, "draws")
        self.trials = trials
        self.seed = seed
        self._settings: list[Params] = []
        self._next = 0
        self.scores_: list[tuple[Params, float]] = []

    def __repr__(self) -> str:
        """Show the method.

        Returns
        -------
        str
            ``Random(trials=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.search.random(trials=20, seed=3))
        'Random(trials=20, seed=3)'
        """
        return f"Random(trials={self.trials}, seed={self.seed})"

    def start(self, space: list[Params], *, maximize: bool) -> None:
        """Draw every setting of the search from the space.

        Parameters
        ----------
        space : list of dict
            One dict per grid, each setting a list of values or a range.
        maximize : bool
            Whether a higher score is better; random ignores it.

        Raises
        ------
        SqlearnError
            If a setting is a single value or an empty list.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.search.random(trials=3).start([{"model__C": [1, 2]}], maximize=True)
        """
        checked = [
            {n: v if isinstance(v, Range) else _values(n, v) for n, v in grid.items()}
            for grid in space
        ]
        rng = _random.Random(self.seed)
        settings: list[Params] = []
        for _ in itertools.repeat(None, self.trials):
            grid = rng.choice(checked)
            settings.append({n: _draw(rng, grid[n]) for n in sorted(grid)})
        self._settings = settings
        self._next = 0
        self.scores_ = []

    def ask(self) -> Params | None:
        """Return the next drawn setting, or None after the last.

        Returns
        -------
        dict or None
            The setting.

        Examples
        --------
        >>> import sqlearn as sq
        >>> method = sq.search.random(trials=1)
        >>> method.start([{}], maximize=True)
        >>> method.ask(), method.ask()
        ({}, None)
        """
        if self._next >= len(self._settings):
            return None
        params = self._settings[self._next]
        self._next += 1
        return dict(params)

    def tell(self, params: Params, score: float) -> None:
        """Record a setting's score; random does not use it to choose.

        Parameters
        ----------
        params : dict
            The setting.
        score : float
            Its score.

        Examples
        --------
        >>> import sqlearn as sq
        >>> method = sq.search.random()
        >>> method.tell({"model__C": 1}, 0.5)
        >>> method.scores_
        [({'model__C': 1}, 0.5)]
        """
        self.scores_.append((params, score))


def _check_trials(method: str, trials: object, verb: str) -> None:
    """Refuse a number of trials that is not a whole number of 1 or more."""
    if isinstance(trials, bool) or not isinstance(trials, numbers.Integral):
        msg = (
            f"sq.search.{method} got trials={trials!r}; it {verb} a whole "
            "number of settings, so trials must be a whole number (an int, "
            "not a bool). Fix: pass trials=1 or more, such as trials=50."
        )
        raise SqlearnError(msg)
    if trials < 1:
        msg = (
            f"sq.search.{method} got trials={trials!r}; it {verb} at least one "
            "setting. Fix: pass trials=1 or more."
        )
        raise SqlearnError(msg)


@contextlib.contextmanager
def _quiet_optuna(optuna: ModuleType) -> Generator[None]:
    """Hold Optuna's own logging at warnings while a search runs."""
    before = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        yield
    finally:
        optuna.logging.set_verbosity(before)


class Optuna:
    """Pick settings with Optuna, one at a time from the scores so far.

    Optuna's ask-and-tell interface chooses each setting from the scores of
    those before it (its default sampler is TPE). A list of values is a
    categorical choice, so any value, a model among them, can be chosen; a
    `sq.search.range` is a float (log-scaled with ``log=True``), or an
    integer when both bounds are integers. With several grids, Optuna first
    chooses a grid, then that grid's settings. Optuna is not a dependency of
    sqlearn: install it with ``uv add optuna``.

    Parameters
    ----------
    trials : int, default 100
        The number of settings to try, at least 1.
    sampler : Optuna sampler, optional
        Optuna's sampler; by default ``TPESampler(seed=seed)``.
    seed : int, default 0
        Seeds the default sampler (a given `sampler` has its own seed).

    Attributes
    ----------
    knows_all : bool
        False: each setting is picked after the scores of the last.
    study_ : optuna.Study
        The study of the running or last search; set by `start`.

    Raises
    ------
    SqlearnError
        If `trials` is not a whole number (a bool among them) or is below 1.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.search.optuna(trials=30, seed=1)
    Optuna(trials=30, seed=1)
    """

    knows_all = False

    def __init__(
        self, trials: int = 100, sampler: "BaseSampler | None" = None, seed: int = 0
    ) -> None:
        _check_trials("optuna", trials, "tries")
        self.trials = trials
        self.sampler = sampler
        self.seed = seed
        self._optuna = cast("ModuleType", None)
        self._space: list[Params] = []
        self._asked = 0
        self._open: list[tuple[Params, Any]] = []
        self.study_: Any = None

    def __repr__(self) -> str:
        """Show the method.

        Returns
        -------
        str
            ``Optuna(trials=..., seed=...)``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> repr(sq.search.optuna(trials=20, seed=3))
        'Optuna(trials=20, seed=3)'
        """
        return f"Optuna(trials={self.trials}, seed={self.seed})"

    def start(self, space: list[Params], *, maximize: bool) -> None:
        """Create the study over the space.

        Parameters
        ----------
        space : list of dict
            One dict per grid, each setting a list of values or a range.
        maximize : bool
            Whether a higher score is better: the study's direction.

        Raises
        ------
        SqlearnError
            If Optuna is not installed, or a setting is a single value or an
            empty list.

        Examples
        --------
        >>> import sqlearn as sq
        >>> method = sq.search.optuna(trials=3)
        >>> method.start([{"model__C": [1, 2]}], maximize=True)
        >>> method.study_.direction.name
        'MAXIMIZE'
        """
        try:
            import optuna
        except ImportError as exc:
            msg = (
                "sq.search.optuna needs Optuna, which is not installed. Fix: "
                "run `uv add optuna`, or use sq.search.grid() or "
                "sq.search.random()."
            )
            raise SqlearnError(msg) from exc
        self._space = [
            {n: v if isinstance(v, Range) else _values(n, v) for n, v in grid.items()}
            for grid in space
        ]
        sampler: BaseSampler | None = self.sampler
        if sampler is None:
            sampler = optuna.samplers.TPESampler(seed=self.seed)
        with _quiet_optuna(optuna):
            self.study_ = optuna.create_study(
                direction="maximize" if maximize else "minimize", sampler=sampler
            )
        self._optuna = optuna
        self._asked = 0
        self._open = []

    def ask(self) -> Params | None:
        """Return the next setting Optuna chooses, or None after the last.

        Returns
        -------
        dict or None
            The setting.

        Examples
        --------
        >>> import sqlearn as sq
        >>> method = sq.search.optuna(trials=1)
        >>> method.start([{"model__C": [0.5]}], maximize=True)
        >>> method.ask(), method.ask()
        ({'model__C': 0.5}, None)
        """
        if self._asked >= self.trials:
            return None
        self._asked += 1
        with _quiet_optuna(self._optuna):
            trial = self.study_.ask()
            if len(self._space) > 1:
                at = trial.suggest_categorical(
                    "__grid", list(builtins.range(len(self._space)))
                )
            else:
                at = 0
            grid = self._space[at]
            params: Params = {}
            for name in sorted(grid):
                params[name] = self._suggest(trial, f"{at}:{name}", grid[name])
        self._open.append((params, trial))
        return dict(params)

    @staticmethod
    def _suggest(
        trial: "optuna.trial.Trial", key: str, values: Range | Sequence[object]
    ) -> object:
        """Have the trial choose one value of a list or a range."""
        if not isinstance(values, Range):
            return values[
                trial.suggest_categorical(key, list(builtins.range(len(values))))
            ]
        low, high = values.low, values.high
        if isinstance(low, int) and isinstance(high, int):
            return trial.suggest_int(key, low, high, log=values.log)
        return trial.suggest_float(key, low, high, log=values.log)

    def tell(self, params: Params, score: float) -> None:
        """Report a setting's score to the study.

        Parameters
        ----------
        params : dict
            The setting, as `ask` returned it.
        score : float
            Its score.

        Examples
        --------
        >>> import sqlearn as sq
        >>> method = sq.search.optuna(trials=1)
        >>> method.start([{"model__C": [0.5]}], maximize=True)
        >>> method.tell(method.ask(), 0.9)
        >>> method.study_.best_value
        0.9
        """
        for i, (asked, trial) in enumerate(self._open):
            if asked == params:
                del self._open[i]
                with _quiet_optuna(self._optuna):
                    if math.isnan(score):
                        # Optuna fails a NaN value itself, with a warning;
                        # sqlearn says so plainly (spec §4 of the metrics).
                        state = self._optuna.trial.TrialState.FAIL
                        self.study_.tell(trial, state=state)
                    else:
                        self.study_.tell(trial, score)
                return
        msg = (
            f"the setting {params!r} was not asked of this method, or was "
            "already told, so there is no open trial to report its score to. "
            "Fix: tell only the settings `ask` returned, each once."
        )
        raise SqlearnError(msg)


def _draw(rng: _random.Random, values: Range | Sequence[object]) -> object:
    """Draw one value from a list or a range."""
    if not isinstance(values, Range):
        return rng.choice(values)
    low, high = values.low, values.high
    if isinstance(low, int) and isinstance(high, int):
        if values.log:
            return min(
                high,
                max(low, round(math.exp(rng.uniform(math.log(low), math.log(high))))),
            )
        return rng.randint(low, high)
    if values.log:
        return math.exp(rng.uniform(math.log(low), math.log(high)))
    return rng.uniform(low, high)


_FIX = "Fix: write settings as step__setting, such as 'model__C'"


def _constructor_settings(cls: type) -> list[str]:
    """Return the named arguments of a class's constructor, or none if unreadable."""
    try:
        parameters = inspect.signature(cls).parameters.values()
    except (TypeError, ValueError):  # pragma: no cover  (a builtin's constructor)
        return []
    named = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    return [p.name for p in parameters if p.kind in named]


def _set_on_model(model: Model, key: str, name: str, value: object) -> None:
    """Set one setting on a copied model, refusing one it does not have.

    A model with ``get_params`` is checked against its keys, and the named
    arguments of its constructor (CatBoost's ``get_params`` lists only the
    settings it was given), and set with ``set_params`` (the value copied,
    as scikit-learn's search does); any other is checked and set as an
    attribute.
    """
    est = model.estimator
    setting = key.partition("__")[2]
    get_params = getattr(est, "get_params", None)
    have = None
    if callable(get_params):
        have = list(get_params())
        have += [p for p in _constructor_settings(type(est)) if p not in have]
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

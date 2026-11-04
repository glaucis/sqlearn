"""The search: try settings of a pipeline over folds and keep the best.

One class, `Search`, whose method picks the settings (ADR 0022). Every trial
runs on copies of the user's pipeline. A method that knows its settings up
front loops fold first (ADR 0024): each fold's data is prepared once per
distinct preparation and handed to every model setting.
"""

import itertools
import json
import warnings
import weakref
from collections.abc import Sequence
from typing import Any

import duckdb

from sqlearn._config import connection
from sqlearn._errors import DefaultsUsedWarning, SqlearnError
from sqlearn._inputs import Source, _release_later, read
from sqlearn._model import Model, _numpy, _unregister, target_values
from sqlearn._output import Output
from sqlearn._pipeline import Pipeline, _source_sql
from sqlearn.metrics import Metric, accuracy
from sqlearn.model_selection.defaults import default_space, hint
from sqlearn.model_selection.folds import KFold
from sqlearn.model_selection.methods import Grid, Method, Params, trial

__all__ = ["FOLD", "Search"]

FOLD = "__sqlearn_fold"
"""The column holding each row's fold number in a fold's feeding query."""

_ids = itertools.count()


def _preparation(params: Params, model_name: str) -> str:
    """Return a key naming a setting's preparation: its non-model settings."""
    steps = {k: v for k, v in params.items() if k.partition("__")[0] != model_name}
    return json.dumps(steps, sort_keys=True, default=repr)


def _check_folds(source: Source, folds: KFold) -> None:
    """Refuse a fold that holds out no row, counting every fold in one query."""
    fold = duckdb.ColumnExpression(FOLD)
    counted = folds.numbered(source.relation, FOLD).aggregate(
        [fold, duckdb.FunctionExpression("count_star")], fold
    )
    sizes = dict.fromkeys(range(folds.n), 0)
    sizes.update({int(k): int(n) for k, n in counted.fetchall()})
    empty = [k for k, n in sizes.items() if n == 0]
    if empty:
        rows = sum(sizes.values())
        listed = ", ".join(str(n) for n in sizes.values())
        msg = (
            f"fold {empty[0]} of {folds!r} holds out no row: the {rows} rows "
            f"were dealt into folds of {listed} rows, and a fold with nothing "
            "held out cannot be scored. Fix: use fewer folds, or pass more "
            "data."
        )
        raise SqlearnError(msg)


def _fold_error(
    exc: Exception, action: str, params: Params, k: int, folds: KFold
) -> SqlearnError:
    """Explain a model failing on one fold, naming the setting and the fold."""
    setting = json.dumps(params, default=repr)
    msg = (
        f"the model failed to {action} with the setting {setting} on fold {k} "
        f"of {folds!r}: {exc}\nFix: check that setting; with few or repeated "
        "rows, pass more data or use fewer folds, so that each fold's "
        "training rows hold every class."
    )
    return SqlearnError(msg)


def _score(
    con: duckdb.DuckDBPyConnection,
    metric: Metric,
    y: Any,  # noqa: ANN401  (numpy arrays)
    predicted: object,
) -> float:
    """Compute the metric in SQL over the held-out targets and predictions."""
    np = _numpy()
    values = np.asarray(predicted)
    if values.ndim != 1 or len(values) != len(y):
        msg = (
            f"the model's predict returned an array of shape {values.shape}, "
            f"not one value for each of the {len(y)} held-out rows. Fix: use "
            "a model whose predict returns one value per row."
        )
        raise SqlearnError(msg)
    name = f"_sqlearn_scored_{next(_ids)}"
    con.register(name, {"target": y, "prediction": values})
    try:
        return metric.compute(con.table(name), "target", "prediction")
    finally:
        _unregister(con, name)


class Search:
    """Try settings of a pipeline over folds; keep the best, trained on all.

    Parameters
    ----------
    pipe : Pipeline
        A pipeline ending in a model. It is never changed: every trial runs
        on a copy.
    params : dict or list of dict, optional
        Settings to try, keyed ``step__setting`` as in scikit-learn, each to
        a list of values; ``"model"`` (the model's name) to a list of
        models. A list of dicts holds one grid per model. By default, the
        model's default space (`sqlearn.model_selection.defaults`), or one
        trial of its own settings, with a `DefaultsUsedWarning`.
    metric : Metric, default sq.accuracy
        The score, computed in SQL on each fold's held-out rows.
    method : Method, optional
        How settings are picked; by default ``sq.Grid()``.
    folds : KFold, optional
        The folds; by default ``sq.KFold(5, seed=0)``.

    Attributes
    ----------
    best_params_ : dict
        The best setting; on a tie, the first in the method's order.
    best_score_ : float
        Its score, the mean over the folds.
    results_ : duckdb.DuckDBPyRelation
        One row per setting and fold: ``setting`` (JSON text, models by
        their repr), ``fold``, ``score``.
    used_ : dict of str to str
        For ``params``, ``method`` and ``folds``: ``"given"``, or the
        default used.
    best_pipeline_ : Pipeline
        A copy of the pipeline with the best setting, trained on all data.
    transforms_ : int
        How many times a fold's data was prepared.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> from sklearn.linear_model import LogisticRegression
    >>> data = pd.DataFrame({"x": range(20), "y": [0, 1] * 5 + [1, 0] * 5})
    >>> pipe = sq.Pipeline([("scale", sq.Scale()), ("model", LogisticRegression())])
    >>> search = sq.Search(pipe, params={"model__C": [1.0]}, folds=sq.KFold(2))
    >>> search.train(data, target="y").best_params_
    {'model__C': 1.0}
    """

    def __init__(
        self,
        pipe: Pipeline,
        params: Params | list[Params] | None = None,
        metric: Metric = accuracy,
        method: Method | None = None,
        folds: KFold | None = None,
    ) -> None:
        self.pipe = pipe
        self.params = params
        self.metric = metric
        self.method = method
        self.folds = folds
        self.transforms_ = 0

    def _space(self, model_name: str, model: Model) -> tuple[list[Params], str]:
        """Return the space to search and what `used_` says of it; warn on a default."""
        if self.params is not None:
            given = [self.params] if isinstance(self.params, dict) else self.params
            return list(given), "given"
        cls = type(model.estimator).__name__
        space = default_space(model.estimator)
        if space is None:
            text = (
                f"Hint: no params given, and sqlearn has no default space for "
                f"{cls}.\nIt evaluated {cls} with its own settings over the "
                "folds (one trial).\nPass params=... to choose what to search."
            )
            warnings.warn(text, DefaultsUsedWarning, stacklevel=3)
            return [{}], f"default: one trial of {cls} with its own settings"
        described = hint(cls, space)
        text = (
            "Hint: no params given. sqlearn searched its default space for\n"
            f"{described}.\nPass params=... to choose what to search."
        )
        warnings.warn(text, DefaultsUsedWarning, stacklevel=3)
        return [{f"{model_name}__{k}": v for k, v in space.items()}], (
            f"default: {described}"
        )

    def train(self, data: object, target: str) -> "Search":
        """Score every setting over the folds, then train the best on all data.

        The data is read once. With a method that knows every setting up
        front, each fold's data is prepared once per distinct preparation
        (the settings of the steps) and every model setting is trained on
        it; the steps' learned values come from the store when unchanged.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
        target : str
            The column the model learns to predict.

        Returns
        -------
        Search
            This search, with its results and best pipeline.

        Raises
        ------
        SqlearnError
            If the pipeline has no model, a setting names a step or setting
            that does not exist, the method refuses the params, the target
            is not a column, the data has a column named ``__sqlearn_fold``,
            a fold holds out no row, or the model fails to fit or predict on
            a fold (naming the setting and the fold).
        StepError
            As for `Pipeline.train`.

        Notes
        -----
        A change to a DuckDB table or relation in place that keeps its row
        count and columns (an ``UPDATE``, or rows deleted and as many
        inserted) is not noticed: the values learned before are reused. Pass
        the changed data under a new name, or as a file or a pandas frame, to
        have it learned again.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> data = pd.DataFrame({"x": range(20), "y": [0, 1] * 5 + [1, 0] * 5})
        >>> pipe = sq.Pipeline([("model", LogisticRegression())])
        >>> search = sq.Search(pipe, params={"model__C": [0.1, 1.0]}, folds=sq.KFold(2))
        >>> search.train(data, target="y").results_.count("*").fetchall()
        [(4,)]
        """
        _, model = self.pipe._modelled()
        model_name = self.pipe.steps[-1][0]
        space, used_params = self._space(model_name, model)
        method = Grid() if self.method is None else self.method
        folds = KFold() if self.folds is None else self.folds
        method.start(space)
        asked: list[Params] = []
        if method.knows_all:
            while (params := method.ask()) is not None:
                trial(self.pipe, params)  # refuses a bad setting before any work
                asked.append(params)
        source = read(data)
        con = connection()
        _source_sql(con, source)
        self.pipe._features(source, target)  # refuses a target not in the data
        if any(c.lower() == FOLD for c, _ in source.schema):
            msg = (
                f"the data has a column named {FOLD!r}, a name sqlearn keeps "
                "for each row's fold during a search. Fix: rename that column."
            )
            raise SqlearnError(msg)
        _check_folds(source, folds)
        self.transforms_ = 0
        scored: list[tuple[Params, list[float]]] = []
        if method.knows_all:
            scored = list(
                zip(asked, self._evaluate(source, target, folds, asked), strict=True)
            )
            for params, scores in scored:
                method.tell(params, sum(scores) / len(scores))
        else:
            while (params := method.ask()) is not None:
                [scores] = self._evaluate(source, target, folds, [params])
                scored.append((params, scores))
                method.tell(params, sum(scores) / len(scores))
        if not scored:
            msg = (
                f"the method {method!r} gave no setting to try, so there is "
                "nothing to score. Fix: give params with at least one value "
                "per setting."
            )
            raise SqlearnError(msg)
        means = [sum(s) / len(s) for _, s in scored]
        pick = max if self.metric.greater_is_better else min
        best = pick(range(len(means)), key=means.__getitem__)
        self.best_params_ = scored[best][0]
        self.best_score_ = means[best]
        self.results_ = self._results(con, scored)
        self.used_ = {
            "params": used_params,
            "method": "given" if self.method is not None else f"default: {method!r}",
            "folds": "given" if self.folds is not None else f"default: {folds!r}",
        }
        best_pipe = trial(self.pipe, self.best_params_)
        _, best_model = best_pipe._modelled()
        self.best_pipeline_ = best_pipe._train(source, target, best_model.feed)
        return self

    def _evaluate(
        self, source: Source, target: str, folds: KFold, settings: list[Params]
    ) -> list[list[float]]:
        """Score each setting on each fold, fold first; return scores per setting."""
        np = _numpy()
        con = connection()
        model_name = self.pipe.steps[-1][0]
        groups: dict[str, list[int]] = {}
        for i, params in enumerate(settings):
            groups.setdefault(_preparation(params, model_name), []).append(i)
        numbered = folds.numbered(source.relation, FOLD)
        scores = [[0.0] * folds.n for _ in settings]
        for k in range(folds.n):
            rows = folds.rows(source.relation, k, held=False)
            learn_from = self.pipe._features(
                Source(rows, source.key, source.schema), target
            )
            for members in groups.values():
                prepared = trial(self.pipe, settings[members[0]])
                _, first = prepared._modelled()
                x, aside = prepared._prepare_fold(
                    learn_from, (folds.n, folds.seed, k), numbered,
                    [target, FOLD], first.feed,
                )  # fmt: skip
                self.transforms_ += 1
                y = target_values(aside[target], target)
                fit = np.ma.getdata(aside[FOLD]) != k
                for i in members:
                    _, model = trial(self.pipe, settings[i])._modelled()
                    action = "fit"
                    try:
                        model.estimator.fit(x[fit], y[fit])
                        action = "predict"
                        predicted = model.estimator.predict(x[~fit])
                    except Exception as exc:
                        err = _fold_error(exc, action, settings[i], k, folds)
                        raise err from exc
                    scores[i][k] = _score(con, self.metric, y[~fit], predicted)
        return scores

    @staticmethod
    def _results(
        con: duckdb.DuckDBPyConnection, scored: Sequence[tuple[Params, list[float]]]
    ) -> duckdb.DuckDBPyRelation:
        """Return the scores as a relation: setting, fold, score."""
        np = _numpy()
        texts = [json.dumps(p, default=repr) for p, s in scored for _ in s]
        name = f"_sqlearn_results_{next(_ids)}"
        con.register(
            name,
            {
                "setting": np.array(texts, dtype=object),
                "fold": np.array([k for _, s in scored for k in range(len(s))]),
                "score": np.array([v for _, s in scored for v in s], dtype=float),
            },
        )
        rel = con.table(name)
        weakref.finalize(rel, _release_later, con, name)
        return rel

    def predict(self, data: object, out: str | Output | None = None) -> Any:  # noqa: ANN401  (the form `out` names)
        """Predict with the best pipeline, trained on all the data.

        Parameters
        ----------
        data : str, pathlib.Path, duckdb.DuckDBPyRelation or pandas.DataFrame
            A file path or glob, a table name, a relation or a pandas frame.
        out : {"pandas", "polars", "numpy", "arrow"} or Output, optional
            What to hand back, as for `Pipeline.predict`.

        Returns
        -------
        object
            The predictions, as `Pipeline.predict` returns them.

        Raises
        ------
        SqlearnError
            If the search has not been trained, or as for `Pipeline.predict`.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> from sklearn.linear_model import LogisticRegression
        >>> data = pd.DataFrame({"x": range(20), "y": [0] * 10 + [1] * 10})
        >>> pipe = sq.Pipeline([("model", LogisticRegression())])
        >>> search = sq.Search(pipe, params={"model__C": [1.0]}, folds=sq.KFold(2))
        >>> search.train(data, target="y").predict(data, out="numpy")[
        ...     "prediction"
        ... ].tolist()[:3]
        [0, 0, 0]
        """
        best: Pipeline | None = getattr(self, "best_pipeline_", None)
        if best is None:
            msg = (
                "this search has not been trained yet, so it has no best "
                "pipeline to predict with. Fix: call train(data, target=...) "
                "first."
            )
            raise SqlearnError(msg)
        return best.predict(data, out)

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

from sqlearn._compose import POSITION, TARGET
from sqlearn._config import connection
from sqlearn._errors import DefaultsUsedWarning, SqlearnError
from sqlearn._expr import quote
from sqlearn._feed import stream_into, take
from sqlearn._inputs import Source, _release_later, read
from sqlearn._model import Model, _numpy, missing_target, target_values
from sqlearn._output import Output
from sqlearn._pipeline import _ROW, Pipeline, _FoldTable, _positioned, _source_sql
from sqlearn._store import FoldKey
from sqlearn.metrics import Metric, accuracy
from sqlearn.model_selection.defaults import default_space, hint
from sqlearn.model_selection.folds import Folds, KFold
from sqlearn.model_selection.methods import Grid, Method, Params, trial

__all__ = ["FOLD", "Search"]

FOLD = "__sqlearn_fold"
"""The column holding each row's fold number in a fold's feeding query."""

_ids = itertools.count()


def _preparation(params: Params, model_name: str) -> str:
    """Return a key naming a setting's preparation: its non-model settings."""
    steps = {k: v for k, v in params.items() if k.partition("__")[0] != model_name}
    return json.dumps(steps, sort_keys=True, default=repr)


def _flag(predicate: duckdb.Expression) -> duckdb.Expression:
    """Return 1 where the predicate is true, else 0 (NULL counts as false)."""
    one, zero = duckdb.ConstantExpression(1), duckdb.ConstantExpression(0)
    return duckdb.CaseExpression(predicate, one).otherwise(zero)


def _check_folds(source: Source, folds: Folds, target: str) -> None:
    """Refuse a fold that holds out or learns from no row, in one query."""
    numbered = folds.numbered(source.relation, FOLD, target)
    counts = [
        duckdb.FunctionExpression("sum", _flag(folds.held(FOLD, k)))
        for k in range(folds.splits)
    ]
    trained = [
        duckdb.FunctionExpression("sum", _flag(folds.training(FOLD, k)))
        for k in range(folds.splits)
    ]
    row = numbered.aggregate(
        [*counts, *trained, duckdb.FunctionExpression("count_star")]
    ).fetchall()[0]
    sizes = [int(n) for n in row[: folds.splits]]
    learns = [int(n or 0) for n in row[folds.splits : -1]]
    empty = [k for k, n in enumerate(sizes) if n == 0]
    if empty:
        listed = ", ".join(str(n) for n in sizes)
        msg = (
            f"fold {empty[0]} of {folds!r} holds out no row: the {row[-1]} "
            f"rows were dealt into folds of {listed} rows, and a fold with "
            "nothing held out cannot be scored. Fix: use fewer folds, or "
            "pass more data."
        )
        raise SqlearnError(msg)
    bare = [k for k, n in enumerate(learns) if n == 0]
    if bare:
        msg = (
            f"fold {bare[0]} of {folds!r} learns from no row: its training "
            f"rows number {', '.join(str(n) for n in learns)} per fold, and "
            "nothing can be learned from none. Fix: use fewer folds, a "
            "smaller gap, or pass more data."
        )
        raise SqlearnError(msg)


def _fetch(
    table: duckdb.DuckDBPyRelation,
    rows: duckdb.Expression,
    feed: str,
    features: Sequence[str],
) -> tuple[Any, Any]:
    """Fetch the rows of a fold's table a predicate picks, in the query's order."""
    picked = table.filter(rows).sort(duckdb.ColumnExpression(_ROW))
    x, aside = take(picked, feed, features, [TARGET])
    return x, aside[TARGET]


def _check_held_targets(
    table: duckdb.DuckDBPyRelation, held: duckdb.Expression, target: str
) -> None:
    """Refuse held-out rows whose target is missing: they cannot be scored."""
    unknown = held & duckdb.ColumnExpression(TARGET).isnull()
    missing = table.filter(unknown).count("*").fetchall()[0][0]
    if missing:
        raise missing_target(target, missing)


def _fold_error(
    exc: Exception, action: str, params: Params, k: int, folds: Folds
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
    fold_table: str,
    held: duckdb.Expression,
    predictions: str,
) -> float:
    """Compute the metric in SQL: each held-out row's target beside its prediction.

    `predictions` (a table `stream_into` filled) is joined to the fold's
    table by row number; both are tables sqlearn owns (Ruling R1).
    """
    row = quote(_ROW)
    scored = (
        con.table(fold_table)
        .filter(held)
        .set_alias("held")
        .join(
            con.sql(f"FROM {predictions}").set_alias("predicted"),
            f"held.{row} = predicted.{row}",
        )
        .project(
            duckdb.ColumnExpression("held", TARGET).alias("target"),
            duckdb.ColumnExpression("predicted", "prediction"),
        )
    )
    return metric.compute(scored, "target", "prediction")


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
    metric : Metric, default sq.metrics.accuracy
        The score, computed in SQL on each fold's held-out rows.
    method : Method, optional
        How settings are picked; by default ``sq.search.grid()``.
    folds : Folds, optional
        The fold scheme, any object with the `Folds` members; by default
        ``sq.folds.kfold(5, seed=0)``.

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
    >>> pipe = sq.Pipeline(
    ...     [("scale", sq.scale.standard()), ("model", LogisticRegression())]
    ... )
    >>> search = sq.search(pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2))
    >>> search.train(data, target="y").best_params_
    {'model__C': 1.0}
    """

    def __init__(
        self,
        pipe: Pipeline,
        params: Params | list[Params] | None = None,
        metric: Metric = accuracy,
        method: Method | None = None,
        folds: Folds | None = None,
    ) -> None:
        self.pipe = pipe
        self.params = params
        self.metric = metric
        self.method = method
        self.folds = folds
        self.transforms_ = 0
        self._fold_tables: dict[tuple[str, FoldKey], _FoldTable] = {}

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

        The data is read once. Each fold's data is prepared once per
        distinct preparation (the settings of the steps) into a temporary
        DuckDB table, which every model setting sharing it reads, so a
        setting asked again is not prepared again; the tables are dropped
        when this returns or raises. The steps' learned values come from the
        store when unchanged.

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
            is not a column, the data has a column whose name starts with
            ``__sqlearn_fold`` or a column (or a step creates one) named
            ``__sqlearn_row``, a fold holds out no row, a target is missing,
            or the model fails to fit or predict on a fold (naming the
            setting and the fold).
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
        >>> search = sq.search(
        ...     pipe, params={"model__C": [0.1, 1.0]}, folds=sq.folds.kfold(2)
        ... )
        >>> search.train(data, target="y").results_.count("*").fetchall()
        [(4,)]
        """
        _, model = self.pipe._modelled()
        model_name = self.pipe.steps[-1][0]
        space, used_params = self._space(model_name, model)
        method = Grid() if self.method is None else self.method
        folds: Folds = KFold() if self.folds is None else self.folds
        method.start(space, maximize=self.metric.greater_is_better)
        asked: list[Params] = []
        if method.knows_all:
            while (params := method.ask()) is not None:
                trial(self.pipe, params)  # refuses a bad setting before any work
                asked.append(params)
        source = read(data)
        con = connection()
        _source_sql(con, source)
        self.pipe._features(source, target)  # refuses a target not in the data
        if any(c.lower().startswith(FOLD) for c, _ in source.schema):
            msg = (
                f"the data has a column whose name starts with {FOLD!r}, a prefix "
                "sqlearn keeps for each row's fold during a search. Fix: rename "
                "that column."
            )
            raise SqlearnError(msg)
        if any(c.lower() == _ROW for c, _ in source.schema):
            msg = (
                f"the data has a column named {_ROW!r}, a name sqlearn keeps "
                "for numbering each fold's rows during a search, so "
                "predictions line up with their targets. Fix: rename that "
                "column."
            )
            raise SqlearnError(msg)
        _check_folds(source, folds, target)
        self.transforms_ = 0
        scored: list[tuple[Params, list[float]]] = []
        # Each (preparation, fold) is prepared once into a table, read by
        # every setting that shares it; the tables live for this call only.
        self._fold_tables = {}
        try:
            if method.knows_all:
                scores_of = self._evaluate(source, target, folds, asked)
                scored = list(zip(asked, scores_of, strict=True))
                for params, scores in scored:
                    method.tell(params, sum(scores) / len(scores))
            else:
                while (params := method.ask()) is not None:
                    [scores] = self._evaluate(source, target, folds, [params])
                    scored.append((params, scores))
                    method.tell(params, sum(scores) / len(scores))
        finally:
            tables, self._fold_tables = self._fold_tables, {}
            for table in tables.values():
                con.execute(f"DROP TABLE IF EXISTS {quote(table.name)}")
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
            "folds": f"given: {folds!r}"
            if self.folds is not None
            else f"default: {folds!r}",
        }
        best_pipe = trial(self.pipe, self.best_params_)
        _, best_model = best_pipe._modelled()
        self.best_pipeline_ = best_pipe._train(source, target, best_model.feed)
        return self

    def _evaluate(
        self, source: Source, target: str, folds: Folds, settings: list[Params]
    ) -> list[list[float]]:
        """Score each setting on each fold, fold first; return scores per setting.

        A (preparation, fold) already in `_fold_tables` is read from its
        table; any other is prepared into a new one and counted in
        `transforms_`. The training rows are fetched from the table by the
        scheme's own predicate; the held-out rows, picked by its other, are
        streamed to each model in batches and scored in SQL against their
        targets.
        """
        con = connection()
        model_name = self.pipe.steps[-1][0]
        groups: dict[str, list[int]] = {}
        for i, params in enumerate(settings):
            groups.setdefault(_preparation(params, model_name), []).append(i)
        numbered = folds.numbered(source.relation, FOLD, target)
        if any(s.uses_target for _, s in self.pipe._split()[0]):
            # Every row numbered once, before the folds split them, so a
            # fold's training rows keep the positions their inner folds
            # are dealt by in the fold's query too.
            numbered = _positioned(numbered)
        columns = [duckdb.ColumnExpression(c) for c, _ in source.schema]
        if POSITION in numbered.columns:
            columns.append(duckdb.ColumnExpression(POSITION))
        scores = [[0.0] * folds.splits for _ in settings]
        helpers = [c for c in numbered.columns if c.lower().startswith(FOLD)]
        for k in range(folds.splits):
            fold: FoldKey = (folds.key, k)
            rows = numbered.filter(folds.training(FOLD, k)).project(*columns)
            for preparation, members in groups.items():
                prepared = trial(self.pipe, settings[members[0]])
                _, first = prepared._modelled()
                prepared_fold = self._fold_tables.get((preparation, fold))
                if prepared_fold is None:
                    # The setting's own steps: their inner folds travel beside.
                    learn_from = prepared._features(
                        Source(rows, source.key, source.schema), target
                    )
                    prepared_fold = prepared._prepare_fold(
                        learn_from, fold, numbered, target,
                        keep=helpers, held=folds.held(FOLD, k),
                    )  # fmt: skip
                    self._fold_tables[preparation, fold] = prepared_fold
                    self.transforms_ += 1
                table = con.table(prepared_fold.name)
                features = prepared_fold.features
                x_fit, y_fit = _fetch(
                    table, folds.training(FOLD, k), first.feed, features
                )
                y_fit = target_values(y_fit, target)
                _check_held_targets(table, folds.held(FOLD, k), target)
                # The held-out rows are streamed to each model in batches.
                held = table.filter(folds.held(FOLD, k))
                for i in members:
                    _, model = trial(self.pipe, settings[i])._modelled()
                    action = "fit"
                    try:
                        model.estimator.fit(x_fit, y_fit)
                        action = "predict"
                        predictions, _ = stream_into(con, held, features, _ROW, model)
                    except SqlearnError:
                        raise
                    except Exception as exc:
                        err = _fold_error(exc, action, settings[i], k, folds)
                        raise err from exc
                    try:
                        scores[i][k] = _score(
                            con, self.metric, prepared_fold.name,
                            folds.held(FOLD, k), predictions,
                        )  # fmt: skip
                    finally:
                        con.execute(f"DROP TABLE IF EXISTS {predictions}")
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
        >>> search = sq.search(
        ...     pipe, params={"model__C": [1.0]}, folds=sq.folds.kfold(2)
        ... )
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

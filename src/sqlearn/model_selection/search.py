"""The search: try settings of a pipeline over folds and keep the best.

One class, `Search`, whose method picks the settings (ADR 0022). Every trial
runs on copies of the user's pipeline. A method that knows its settings up
front loops fold first (ADR 0024): each fold's data is prepared once per
distinct preparation and handed to every model setting.
"""

import contextlib
import functools
import itertools
import json
import math
import os
import sys
import warnings
import weakref
from collections.abc import Sequence
from typing import Any

import duckdb

from sqlearn._compose import POSITION, TARGET
from sqlearn._config import connection
from sqlearn._errors import DefaultsUsedWarning, SqlearnError
from sqlearn._expr import quote
from sqlearn._feed import WrongShapeError, fetch, stream_into, stream_trainer
from sqlearn._inputs import Source, _release_later, read
from sqlearn._model import Model, _numpy, missing_target
from sqlearn._output import Output
from sqlearn._pipeline import _ROW, Pipeline, _FoldTable, _positioned, _source_sql
from sqlearn._store import FoldKey
from sqlearn.metrics import Metric, MissingClassError, accuracy
from sqlearn.model_selection.defaults import default_space, hint
from sqlearn.model_selection.folds import Folds, KFold
from sqlearn.model_selection.kept import KeptFolds, steps_identity, table_name
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
            f"fold {empty[0]} of {folds!r} holds out no row: of the {row[-1]} "
            f"rows, the folds hold out {listed} rows in turn, and a fold with "
            "nothing held out cannot be scored. Fix: use fewer folds (or, for "
            "a holdout, a larger test share), or pass more data."
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
    target: str,
    categories: dict[str, list[str]],
) -> tuple[Any, Any]:
    """Fetch the rows of a fold's table a predicate picks, in the query's order.

    The features and the target come in the form `feed` names, the target
    refused where it is missing (named `target`, as in the user's data);
    each text feature's categories are recorded in `categories`.
    """
    picked = table.filter(rows).sort(duckdb.ColumnExpression(_ROW))
    return fetch(picked, feed, features, TARGET, named=target, categories=categories)


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


def _unstable() -> SqlearnError:
    """Explain that data with no stable identity cannot be kept prepared."""
    msg = (
        "keep_prepared keeps each fold's prepared rows for later searches, "
        "even in another session, so it needs data known the same way in "
        "every process: a file, a pandas frame, or a table in a DuckDB "
        "database file. A relation, or a table of an in-memory database, is "
        "known only to this process. Fix: pass a file, a pandas frame or a "
        "table of a database file, or search without keep_prepared."
    )
    return SqlearnError(msg)


TIE_TOLERANCE = 16 * sys.float_info.epsilon
"""Mean scores this close (relative) tie: a few ULPs, measured at 1 (ADR 0043)."""


def _score(
    con: duckdb.DuckDBPyConnection,
    metric: Metric,
    fold_table: str,
    held: duckdb.Expression,
    predicted: tuple[str, list[str], Sequence[object] | None],
) -> float:
    """Compute the metric in SQL: each held-out row's target beside its prediction.

    `predicted` holds a table `stream_into` filled, its prediction columns
    (``prediction``, or one probability column per class) and the model's
    classes, which a ``"predict_proba"`` metric reads. The table is joined
    to the fold's table by row number; both are tables sqlearn owns
    (Ruling R1).
    """
    predictions, outputs, classes = predicted
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
            *(duckdb.ColumnExpression("predicted", c) for c in outputs),
        )
    )
    return metric.compute(scored, "target", "prediction", classes=classes)


def _check_method(metric: Metric, model: Model) -> None:
    """Refuse a model without the method the metric reads, before any work."""
    if not hasattr(model.estimator, metric.needs):
        msg = (
            f"the metric {metric.name} reads the model's {metric.needs}, and "
            f"the model {type(model.estimator).__name__} has none. Fix: pick "
            f"a metric that reads predict (sq.metrics.accuracy, say), or a "
            f"model with {metric.needs}."
        )
        raise SqlearnError(msg)


def _no_classes(metric: Metric, model: Model) -> SqlearnError:
    """Explain a fitted model whose probabilities have no classes to name them."""
    msg = (
        f"the metric {metric.name} reads one probability column per class, "
        f"and the fitted model {type(model.estimator).__name__} has no "
        "classes_ naming them, so no column can be matched to a label. Fix: "
        "use a classifier that sets classes_ when fitted, as scikit-learn's "
        "do."
    )
    return SqlearnError(msg)


def _one_class(
    exc: MissingClassError, metric: Metric, k: int, folds: Folds
) -> SqlearnError:
    """Explain a held-out fold that holds one class only, naming the fold.

    The fix depends on the scheme: time folds keep their order, so the fix
    is fewer folds or a later cut-off, not stratified folds.
    """
    scheme = getattr(folds, "key", ("",))[0]
    if scheme == "time":
        fix = (
            "use fewer folds, or a later cut-off (data whose later periods "
            "hold every class)"
        )
    elif scheme == "stratified":
        fix = "use fewer folds, or pass more rows of each class"
    else:
        fix = (
            "use fewer folds, or sq.folds.stratified, which holds out every "
            "class in every fold"
        )
    msg = (
        f"fold {k} of {folds!r} cannot be scored by {metric.name}: among its "
        f"held-out rows, {exc.reason}. Fix: {fix}."
    )
    return SqlearnError(msg)


def _unscored(
    exc: SqlearnError, metric: Metric, params: Params, k: int, folds: Folds
) -> SqlearnError:
    """Give a metric's refusal on one fold the fold and the setting."""
    setting = json.dumps(params, default=repr)
    msg = (
        f"fold {k} of {folds!r} cannot be scored by {metric.name} with the "
        f"setting {setting}, on its held-out rows: {exc}"
    )
    return SqlearnError(msg)


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
    keep_prepared : str or os.PathLike, optional
        A DuckDB file to keep each fold's prepared rows in, so a later
        search on the same data, steps and folds (in this session or
        another) prepares nothing. Off by default: the rows are kept in
        temporary tables for one ``train`` only. See Notes.

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

    Notes
    -----
    With ``keep_prepared``, a kept table is found by a key of its data (a
    file by its path, size and modification time; a pandas frame by its
    content; a table of a database file by the file, its name, row count
    and storage blocks), the target, each step's name, class and settings,
    the fold scheme, and the versions of sqlearn and DuckDB. Data with no
    such key (a relation, a table of an in-memory database) is refused, and
    so is a step setting that cannot be keyed by its content. A table
    edited in place gets new storage blocks and so is prepared again, with
    a `SqlearnWarning` when this process learned from it before: warned once
    per change of the table, by whichever learns from it first. An edit
    still in the write-ahead log may not be seen yet: run ``CHECKPOINT``
    after editing. Not seen: a change to the code of a step of your own, with the
    same class name and settings; and a change to sqlearn's code in an
    editable or git install, whose version does not change with its code.
    After any of these, or an edit not checkpointed, clear the file with
    ``sq.store.clear(prepared=path)``. ``sq.store.prepared(path)`` lists
    what is kept.

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
        keep_prepared: str | os.PathLike[str] | None = None,
    ) -> None:
        if not isinstance(metric, Metric):
            msg = (
                f"metric= was given {metric!r}, which is not a metric. Why: a "
                "search needs a score to rank the settings by, and "
                "confusion_matrix, classification_report, roc_curve and "
                "precision_recall_curve give tables, not a score; a plain "
                "function has no SQL to run. Fix: pass one of sq.metrics' "
                "scores, as metric=sq.metrics.f1."
            )
            raise SqlearnError(msg)
        self.pipe = pipe
        self.params = params
        self.metric = metric
        self.method = method
        self.folds = folds
        self.keep_prepared = keep_prepared
        self.transforms_ = 0
        self._fold_tables: dict[tuple[str, FoldKey], _FoldTable] = {}
        self._kept: tuple[KeptFolds, tuple[object, ...]] | None = None

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
        setting asked again is not prepared again. A method asking one
        setting at a time (``knows_all`` False) keeps only the current
        preparation's tables, dropping the others when it asks a different
        one, so they hold one preparation's folds at most. The tables are
        dropped when this returns or raises. With ``keep_prepared``, the tables are
        written to that file instead and kept, and a table already there is
        read rather than prepared again; the file is attached only while
        this runs. The steps' learned values come from the store when
        unchanged.

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
            the model fails to fit or predict on a fold (naming the setting
            and the fold), or ``keep_prepared`` is given with data that has
            no stable identity (a relation, a table of an in-memory
            database), a step setting that cannot be keyed by its content
            (a lambda, a ``functools.partial``, ...), or a file that cannot
            be opened (locked by another process, or not a DuckDB
            database).
        StepError
            As for `Pipeline.train`.

        Notes
        -----
        A table of a database file edited in place is noticed by its
        storage blocks once the edit is checkpointed (run ``CHECKPOINT``
        after editing): it is learned and prepared again, with a
        `SqlearnWarning` when this process learned from it before. A
        relation, or a table of an in-memory database, changed in place
        with the same row count and columns (an ``UPDATE``, or rows deleted
        and as many inserted) is not noticed: the values learned before are
        reused. Pass the changed data under a new name, or as a file or a
        pandas frame, to have it learned again.

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
        if self.keep_prepared is not None and isinstance(data, duckdb.DuckDBPyRelation):
            raise _unstable()  # before any work: a relation has no stable key
        _, model = self.pipe._modelled()
        model_name = self.pipe.steps[-1][0]
        space, used_params = self._space(model_name, model)
        method = Grid() if self.method is None else self.method
        folds: Folds = KFold() if self.folds is None else self.folds
        self.metric._ready()  # before any work
        method.start(space, maximize=self.metric.greater_is_better)
        asked: list[Params] = []
        if method.knows_all:
            while (params := method.ask()) is not None:
                # Refuses a bad setting, or a model the metric cannot read,
                # before any work.
                _check_method(self.metric, trial(self.pipe, params)._modelled()[1])
                asked.append(params)
        source = read(data, learning=True)
        stable = None
        if self.keep_prepared is not None:
            stable = source.stable_key()
            if stable is None:
                raise _unstable()
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
        # every setting that shares it; the tables live for this call only,
        # and one setting at a time keeps only the current preparation's.
        self._fold_tables = {}
        try:
            if self.keep_prepared is not None:
                # The target belongs to the key: it is set aside before the
                # steps, so another target prepares other rows.
                self._kept = (KeptFolds(self.keep_prepared), (stable, target))
            if method.knows_all:
                scores_of = self._evaluate(source, target, folds, asked)
                scored = list(zip(asked, scores_of, strict=True))
                for params, scores in scored:
                    method.tell(params, sum(scores) / len(scores))
            else:
                while (params := method.ask()) is not None:
                    try:
                        _check_method(
                            self.metric, trial(self.pipe, params)._modelled()[1]
                        )
                        self._keep_only(con, _preparation(params, model_name))
                        [scores] = self._evaluate(source, target, folds, [params])
                    except BaseException:
                        # The asked setting gets no score: tell the method
                        # so (Optuna fails the trial instead of leaving it
                        # running), then the error goes on unchanged.
                        with contextlib.suppress(Exception):
                            method.tell(params, math.nan)
                        raise
                    scored.append((params, scores))
                    method.tell(params, sum(scores) / len(scores))
        finally:
            tables, self._fold_tables = self._fold_tables, {}
            kept, self._kept = self._kept, None
            if kept is None:
                for table in tables.values():
                    con.execute(f"DROP TABLE IF EXISTS {quote(table.name)}")
            else:
                kept[0].close()  # the kept tables stay in the file
        if not scored:
            msg = (
                f"the method {method!r} gave no setting to try, so there is "
                "nothing to score. Fix: give params with at least one value "
                "per setting."
            )
            raise SqlearnError(msg)
        means = [sum(s) / len(s) for _, s in scored]
        # A NaN mean (a fold scored NaN under zero_division=nan) ranks last,
        # as GridSearchCV ranks it; with every mean NaN there is no best.
        scorable = [i for i, m in enumerate(means) if not math.isnan(m)]
        if not scorable:
            msg = (
                f"every setting scored NaN with {self.metric!r}, so none is "
                "the best. Why: a fold of each setting divided by zero, and "
                "zero_division=nan makes that score NaN. Fix: give the "
                'metric zero_division=0.0 (or "warn"), or use folds where '
                "every class is predicted."
            )
            raise SqlearnError(msg)
        pick = max if self.metric.greater_is_better else min
        top = means[pick(scorable, key=means.__getitem__)]
        # Scores within rounding of the best tie, and the first tried wins:
        # DuckDB's parallel sums can move a score by an ULP between runs, so
        # that wobble must never change the best (ADR 0043).
        best = next(
            i for i in scorable if math.isclose(means[i], top, rel_tol=TIE_TOLERANCE)
        )
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

    def _keep_only(self, con: duckdb.DuckDBPyConnection, preparation: str) -> None:
        """Drop the temporary fold tables of every preparation but this one.

        A method asking one setting at a time (``knows_all`` False) may ask
        any number of preparations, so only the current one's tables are
        kept: a setting asked again with the same preparation reads them,
        and memory holds one preparation's folds at most. Tables in the
        ``keep_prepared`` file are kept there by design.
        """
        if self._kept is not None:
            return
        for key in [key for key in self._fold_tables if key[0] != preparation]:
            table = self._fold_tables.pop(key)
            con.execute(f"DROP TABLE IF EXISTS {quote(table.name)}")

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
                prepared_fold = self._fold_tables.get((preparation, fold))
                if prepared_fold is None:
                    prepared_fold = self._prepared_fold(
                        prepared, Source(rows, source.key, source.schema),
                        (fold, numbered, target, helpers, folds),
                    )  # fmt: skip
                    self._fold_tables[preparation, fold] = prepared_fold
                table = con.table(prepared_fold.name)
                features = prepared_fold.features
                models = {
                    i: trial(self.pipe, settings[i])._modelled()[1] for i in members
                }
                # Each model trains in its own form, the rows fetched once per
                # distinct form and fitted to every model taking it.
                feeds: dict[str, list[int]] = {}
                for i, model in models.items():
                    feeds.setdefault(model.feed, []).append(i)
                for n, (feed, takers) in enumerate(feeds.items()):
                    categories: dict[str, list[str]] = {}
                    training = folds.training(FOLD, k)
                    fitted: tuple[object, object] | duckdb.DuckDBPyRelation
                    if feed == "stream":
                        # Each model streams the training rows itself, with
                        # its own batches, epochs and order.
                        fitted = table.filter(training)
                    else:
                        fitted = _fetch(
                            table, training, feed, features, target, categories
                        )
                    if n == 0:
                        _check_held_targets(table, folds.held(FOLD, k), target)
                    self._fit_and_score(
                        con, prepared_fold, folds, k, (fitted, target, categories),
                        [(i, settings[i]) for i in takers], models, scores,
                    )  # fmt: skip
                    del fitted  # one form's rows in memory at a time
        return scores

    def _prepared_fold(
        self,
        prepared: Pipeline,
        rows: Source,
        where: tuple[FoldKey, duckdb.DuckDBPyRelation, str, list[str], Folds],
    ) -> _FoldTable:
        """Return a fold's prepared table: kept already, or prepared now.

        `rows` are the fold's training rows; `where` holds the fold, every
        row numbered into folds, the target, the fold's helper columns and
        the scheme. A table kept in the ``keep_prepared`` file under this
        key is read as it is; any other is prepared (counted in
        `transforms_`), into the file when one is given, else into a
        temporary table.
        """
        fold, numbered, target, helpers, folds = where
        k = fold[1]
        steps, _ = prepared._modelled()
        if self._kept is None:
            # The setting's own steps: their inner folds travel beside.
            table = prepared._prepare_fold(
                prepared._features(rows, target), fold, numbered, target,
                keep=helpers, held=folds.held(FOLD, k),
            )  # fmt: skip
            self.transforms_ += 1
            return table
        kept, stable = self._kept
        name = table_name(stable, steps, folds.key, k)
        found = kept.get(name)
        if found is not None:
            columns = connection().table(found).columns
            return _FoldTable(found, tuple(columns[: columns.index(TARGET)]))
        sql, features = prepared._fold_query(
            prepared._features(rows, target), fold, numbered, target,
            keep=helpers, held=folds.held(FOLD, k),
        )  # fmt: skip
        row = (repr(stable), repr(steps_identity(steps)), repr(folds.key), k)
        table = _FoldTable(kept.put(name, sql, row), features)
        self.transforms_ += 1
        return table

    def _fit_and_score(
        self,
        con: duckdb.DuckDBPyConnection,
        prepared_fold: _FoldTable,
        folds: Folds,
        k: int,
        fitted: tuple[
            tuple[object, object] | duckdb.DuckDBPyRelation, str, dict[str, list[str]]
        ],
        takers: Sequence[tuple[int, Params]],
        models: dict[int, Model],
        scores: list[list[float]],
    ) -> None:
        """Fit each model to one fold's training rows, then score it in SQL.

        `fitted` holds the training rows, the target's name in the user's
        data and the text categories. The rows are the features and the
        target fetched in the takers' form, or for ``feed="stream"`` the
        fold table's training rows, which each model streams through
        ``partial_fit`` (what the stream refuses is refused as it is, not as
        a fold's failure). The held-out rows are streamed to each model in
        batches, in its own form with those categories, and the score is
        written to ``scores[i][k]``. Each model is taken out of `models` as
        it is fitted, so it is dropped once scored rather than kept alive
        beside the next.
        """
        rows, target, categories = fitted
        features = prepared_fold.features
        held = con.table(prepared_fold.name).filter(folds.held(FOLD, k))
        for i, params in takers:
            model = models.pop(i)
            if isinstance(rows, duckdb.DuckDBPyRelation):
                fit = stream_trainer(con, rows, features, TARGET, model, named=target)
            else:
                x_fit, y_fit = rows
                fit = functools.partial(model.estimator.fit, x_fit, y_fit)
            action = "fit"
            try:
                fit()
                action = "predict"
                predictions, outputs = stream_into(
                    con, held, features, _ROW, model,
                    method=self.metric.needs, categories=categories,
                )  # fmt: skip
            except WrongShapeError:
                raise  # the stream's own message says what to fix
            except Exception as exc:
                raise _fold_error(exc, action, params, k, folds) from exc
            try:
                classes = getattr(model.estimator, "classes_", None)
                if self.metric.needs == "predict_proba" and classes is None:
                    raise _no_classes(self.metric, model)
                try:
                    scores[i][k] = _score(
                        con, self.metric, prepared_fold.name,
                        folds.held(FOLD, k), (predictions, outputs, classes),
                    )  # fmt: skip
                except MissingClassError as exc:
                    raise _one_class(exc, self.metric, k, folds) from exc
                except SqlearnError as exc:
                    raise _unscored(exc, self.metric, params, k, folds) from exc
            finally:
                con.execute(f"DROP TABLE IF EXISTS {predictions}")

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

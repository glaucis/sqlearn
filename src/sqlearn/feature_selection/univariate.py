"""SelectKBest: keep the numeric columns that score best against the target."""

import math
import sys
import warnings
from collections.abc import Mapping
from typing import ClassVar, cast

from duckdb import Expression

from sqlearn._errors import PACKAGE_FILES, SqlearnError, SqlearnWarning, StepError
from sqlearn._group import call_repr
from sqlearn._selectors import Schema, Selector, _numeric
from sqlearn._step import Learned, Step
from sqlearn.feature_selection._scores import (
    LEARNED,
    SCORES,
    Stats,
    finish_score,
    learn_score,
)
from sqlearn.preprocessing.scale import _numeric_inputs
from sqlearn.preprocessing.target import _NUMBERS

__all__ = ["SelectKBest"]


def _score(call: str, value: object) -> str:
    """Return `value` when it names a score, else refuse it."""
    if not isinstance(value, str) or value not in SCORES:
        msg = (
            f"{call} got score={value!r}. Why: the score is named, so a saved "
            f"pipeline stays plain data, and it is one of {', '.join(SCORES)}. "
            'Fix: give one of them, such as score="f_classif" for classes or '
            'score="f_regression" for a number.'
        )
        raise SqlearnError(msg)
    return value


def _k(value: object) -> int | str:
    """Return `value` when it is a whole number from 0 up or ``"all"``."""
    whole = isinstance(value, int) and not isinstance(value, bool)
    if value == "all" or (whole and cast("int", value) >= 0):
        return cast("int | str", value)
    msg = (
        f"sq.select.best got k={value!r}. Why: k is how many columns to keep, "
        'a whole number from 0 up or "all", as scikit-learn\'s SelectKBest '
        'checks. Fix: give such a number, such as k=10, or k="all".'
    )
    raise SqlearnError(msg)


def _ranked(score: float) -> float:
    """Return `score` for ranking: NaN as the lowest double, as scikit-learn's."""
    return -sys.float_info.max if math.isnan(score) else score


class _Univariate(Step):
    """A feature selector keeping the columns that score best against the target.

    What `SelectKBest` and `SelectPercentile` share: each column is scored
    against the target (`score`, learned in SQL by
    `sqlearn.feature_selection._scores`), and a subclass keeps some of them
    by their scores (`_kept`). It learns once on the rows given, without
    cross-fitting (ADR 0055).
    """

    uses_target = True
    cross_fits = False
    dynamic = True
    rowwise = True
    keeps_inputs = True
    _call: ClassVar[str] = "sq.select"

    def __init__(
        self,
        score: str,
        cols: Selector | str | tuple[str, ...] | list[str] | None,
    ) -> None:
        super().__init__(cols=cols)
        self.score = _score(self._call, score)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to score, refusing any that is not numeric.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns (by default the numeric ones), in schema order.

        Raises
        ------
        StepError
            If a chosen column is not numeric.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import DOUBLE, VARCHAR
        >>> sq.select.best().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "score", f"the {self.score} score is of numbers"
        )

    def learn(
        self, x: Expression, y: Expression | None = None
    ) -> Mapping[str, Expression]:
        """Learn what the column's score against the target needs.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        y : duckdb.Expression
            The target, which the pipeline gives a step with `uses_target`
            (optional only so the signature extends `Step.learn`'s).

        Returns
        -------
        mapping of str to duckdb.Expression
            Learned name to aggregate (see
            `sqlearn.feature_selection._scores.learn_score`).

        Raises
        ------
        StepError
            If no target is given.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> x, y = duckdb.ColumnExpression("a"), duckdb.ColumnExpression("y")
        >>> list(sq.select.best(score="f_regression").learn(x, y))[-3:]
        ['covariance', 'variance', 'target_variance']
        """
        if y is None:
            msg = (
                "scores each column against the target, but was given none. "
                "Fix: learn the pipeline with learn(data, target=...) or train."
            )
            raise StepError(msg, step="", position=0)
        return learn_score(self.score, x, y)

    @property
    def scores_(self) -> dict[str, float]:
        """Each column's score against the target, as scikit-learn's ``scores_``.

        Returns
        -------
        dict of str to float
            Column to its score; NaN where scikit-learn's is NaN (such as
            ``f_classif`` of a constant column).

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 5.0, 6.0], "y": [0, 0, 1, 1]})
        >>> pipe = sq.Pipeline([sq.select.best(k=1)]).learn(data, target="y")
        >>> pipe["best"].scores_
        {'a': 32.0}
        """
        learned = cast(
            "dict[str, dict[str, object]] | None", self.__dict__.get("_learned")
        )
        if learned is None:
            return cast("dict[str, float]", self.count_)  # raises: not learned
        return {c: finish_score(self.score, values) for c, values in learned.items()}

    def learned(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Warn of constant columns (``f_classif``) and of what is kept.

        As scikit-learn's ``f_classif`` warns that columns are constant, once
        and naming them; then the warnings of the subclass's setting.

        Parameters
        ----------
        values : mapping of str to mapping of str to object
            Column, then learned name, to the value learned.

        Examples
        --------
        >>> import sqlearn as sq
        >>> stats = [(0, 0, 1, 1.0, 1.0), (0, 1, 1, 0.0, 0.0)]
        >>> sq.select.best(k=1).learned({"a": {"stats": stats}}) is None
        True
        """
        if self.score == "f_classif":
            constant = [
                c
                for c, v in values.items()
                if all(s == 0 for _, _, _, s, _ in cast("Stats", v["stats"]))
            ]
            if constant:
                names = ", ".join(map(repr, constant))
                text = (
                    f"{self._call}: columns {names} are constant, so their "
                    "f_classif score is NaN and they rank lowest, as "
                    "scikit-learn's f_classif warns. Fix: drop them first "
                    "with sq.select.variance(), or leave them out with cols=."
                )
                warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)
        self._warn(len(values))

    def _warn(self, count: int) -> None:
        """Warn of the subclass's setting, given how many columns are scored."""

    def _kept(self, scores: Mapping[str, float]) -> set[str]:
        """Return the columns kept for their scores (the subclass's rule)."""
        raise NotImplementedError

    def _scores(self, learned: Mapping[str, Learned]) -> dict[str, float]:
        """Return each column's score, refusing what scikit-learn refuses."""
        scores: dict[str, float] = {}
        for c, values in learned.items():
            got = {k: values.raw(k) for k in LEARNED[self.score]}
            self._refuse(c, got)
            scores[c] = finish_score(self.score, got)
        return scores

    def _refuse(self, column: str, values: Mapping[str, object]) -> None:
        """Refuse a missing or infinite value, a negative one for chi2, a bad target."""
        fill = "Fix: fill them first with sq.impute, or leave those rows out."
        if cast("int", values["target_missing"]):
            msg = (
                "scores each column against the target, which is missing "
                "(NULL or NaN) or infinite in some rows. Why: scikit-learn "
                "refuses such a target. Fix: leave those rows out, or fill "
                "the target first."
            )
            raise StepError(msg, step="", position=0)
        if cast("int", values["missing"]):
            msg = (
                f"cannot score column {column!r}, which has missing values "
                "(NULL or NaN). Why: the scores take every row's value, and "
                f"scikit-learn refuses a missing one. {fill}"
            )
            raise StepError(msg, step="", position=0)
        if cast("int", values["infinite"]):
            msg = (
                f"cannot score column {column!r}, which has infinite "
                "values. Why: the scores take every row's value, and "
                "scikit-learn refuses an infinite one. Fix: clip or replace "
                "them first, or leave those rows out."
            )
            raise StepError(msg, step="", position=0)
        if self.score == "chi2" and cast("float", values["low"]) < 0:
            msg = (
                f"cannot score column {column!r} by chi2: it has negative "
                f"values (the least is {values['low']!r}). Why: chi2 compares "
                "sums such as counts or frequencies, and scikit-learn's chi2 "
                "refuses a negative value. Fix: scale it to 0 up first with "
                'sq.scale.minmax(), or score it with score="f_classif".'
            )
            raise StepError(msg, step="", position=0)
        if self.score == "f_regression":
            kind = str(values["kind"])
            if kind not in _NUMBERS and not kind.startswith("DECIMAL"):
                msg = (
                    f"scores by f_regression against the target, which is "
                    f"{kind}. Why: f_regression correlates each column with "
                    "a number. Fix: for classes, score with "
                    'score="f_classif" or score="chi2".'
                )
                raise StepError(msg, step="", position=0)

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
        values: Mapping[str, Expression],
    ) -> Mapping[str, Expression]:
        """Keep the columns that score best, each unchanged.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The chosen columns, by name.
        learned : mapping of str to Learned
            The values learned for each column.
        values : mapping of str to duckdb.Expression
            Unused: the step computes nothing per row.

        Returns
        -------
        mapping of str to duckdb.Expression
            The columns kept, each as it came, under its own name, in order.

        Raises
        ------
        StepError
            If a column has a missing or infinite value, a negative one for
            ``chi2``, or the target is missing somewhere (or not a number,
            for ``f_regression``), as scikit-learn refuses them.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> xs = {c: duckdb.ColumnExpression(c) for c in "ab"}
        >>> def known(stats):
        ...     return Learned.values(
        ...         {
        ...             "count": 4,
        ...             "missing": 0,
        ...             "infinite": 0,
        ...             "target_missing": 0,
        ...             "stats": stats,
        ...             "low": 0.0,
        ...         }
        ...     )
        >>> learned = {
        ...     "a": known([(0, 0, 2, 1.0, 1.0), (0, 1, 2, 1.0, 1.0)]),
        ...     "b": known([(0, 0, 2, 0.0, 0.0), (0, 1, 2, 4.0, 8.0)]),
        ... }
        >>> list(sq.select.best(k=1).apply_row(xs, learned, {}))
        ['b']
        """
        kept = self._kept(self._scores({c: learned[c] for c in xs}))
        return {c: x for c, x in xs.items() if c in kept}


class SelectKBest(_Univariate):
    """Keep the `k` numeric columns that score best against the target.

    Build it with `sq.select.best <SelectGroup>`. As scikit-learn's
    ``SelectKBest``: it scores each column against the target by `score`
    and keeps the `k` highest; the others are gone. A column kept passes
    through unchanged: its name, type and values. A NaN score ranks lowest,
    and among equal scores the later column is kept, as scikit-learn's
    stable sort. It learns once on the rows given, without cross-fitting
    (ADR 0055): in a search, on each fold's training rows.

    The scores, as scikit-learn's of the same name:

    - ``"f_classif"``: the ANOVA F of the column across the target's classes
      (of any type). A constant column scores NaN, and is warned about.
    - ``"f_regression"``: the F of the column's correlation with a numeric
      target, ``force_finite``: a constant column or target scores 0, a
      perfect correlation the largest double.
    - ``"chi2"``: chi² of the column's sum per class against its expected
      sum, for counts or frequencies; a negative value is refused.

    A missing (NULL, NaN) or infinite value in a scored column, or a
    missing target, is refused, as scikit-learn refuses them. There is no
    ``pvalues_``: the p-values select nothing here, and come with the
    p-value feature selectors (``SelectFpr``, ``SelectFdr``, ``SelectFwe``)
    when those are built.

    Parameters
    ----------
    k : int or "all", default 10
        How many columns to keep; from 0 up, or ``"all"``. Above the number
        of columns it keeps them all and warns; 0 keeps none and warns. It
        chooses only which columns are output, so a search over it learns
        each fold once (``output_settings``).
    score : str, default "f_classif"
        The score: ``"f_classif"``, ``"f_regression"`` or ``"chi2"``.
    cols : Selector or str or sequence of str, optional
        The columns to choose among; by default the numeric ones. Columns
        not chosen pass through.

    Attributes
    ----------
    scores_ : dict of str to float
        After learning, each column's score.

    Raises
    ------
    SqlearnError
        If `k` is not a whole number from 0 up or ``"all"`` (True is
        refused), or `score` is not one of the three.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame(
    ...     {"a": [1.0, 2.0, 5.0, 6.0], "b": [3.0, 1.0, 2.0, 2.0], "y": [0, 0, 1, 1]}
    ... )
    >>> pipe = sq.Pipeline([sq.select.best(k=1)]).learn(data, target="y")
    >>> pipe.columns_out_
    ['a']
    >>> pipe["best"].scores_
    {'a': 32.0, 'b': 0.0}
    """

    output_settings: ClassVar[frozenset[str]] = frozenset({"k"})
    _call: ClassVar[str] = "sq.select.best"

    def __init__(
        self,
        k: int | str = 10,
        score: str = "f_classif",
        cols: Selector | str | tuple[str, ...] | list[str] | None = _numeric(),  # noqa: B008
    ) -> None:
        super().__init__(score=score, cols=cols)
        self.k = _k(k)

    def default_name(self) -> str:
        """Return ``best``.

        Returns
        -------
        str
            ``best``, whatever the settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.select.best(k=3).default_name()
        'best'
        """
        return "best"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.k != 10:
            kwargs["k"] = self.k
        if self.score != "f_classif":
            kwargs["score"] = self.score
        if self.cols != _numeric():
            kwargs["cols"] = self.cols
        return call_repr(self._call, **kwargs)

    def _warn(self, count: int) -> None:
        """Warn when `k` is above the number of columns, or 0."""
        if self.k == "all":
            return
        if cast("int", self.k) > count:
            text = (
                f"sq.select.best: k={self.k} is greater than the {count} "
                "columns scored, so all are kept, as scikit-learn's "
                "SelectKBest warns. Fix: give k up to the number of columns, "
                'or k="all".'
            )
            warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)
        elif self.k == 0:
            text = (
                "sq.select.best: k=0 keeps none of the columns scored, as "
                "scikit-learn's SelectKBest warns that no column was "
                "selected. Fix: give k=1 or more to keep the best ones."
            )
            warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)

    def _kept(self, scores: Mapping[str, float]) -> set[str]:
        """Return the `k` best columns, as ``argsort(kind="mergesort")[-k:]``."""
        if self.k == "all":
            return set(scores)
        k = cast("int", self.k)
        if k == 0:
            return set()
        # A stable sort: among equal scores the later column sorts later.
        order = sorted(scores, key=lambda c: _ranked(scores[c]))
        return set(order[-k:])

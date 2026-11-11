"""TargetEncoder: replace each category by the target's mean in it, smoothed."""

import math
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Any, cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE

from sqlearn._compose import inner_name
from sqlearn._errors import SqlearnError, StepError
from sqlearn._expr import const, target_stats
from sqlearn._group import call_repr
from sqlearn._selectors import Schema, Selector, _string
from sqlearn._step import Learned, Step
from sqlearn.preprocessing._lookup import check_lookup, check_text, position

__all__ = ["TargetEncoder"]

_TYPES = ("auto", "binary", "continuous")
"""The target types: found from the target, or given."""

_NUMBERS = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
    "FLOAT",
    "DOUBLE",
    "BOOLEAN",
)
"""The types of target taken, beside DECIMAL: numbers, and booleans as 0 and 1."""

_NAN = math.nan
"""The one NaN object every NaN category is keyed by, so a dict finds it."""

Stats = Sequence[tuple[int, object, int, float, float]]
"""Per inner fold and category: fold, category, count, sum(y), sum(y * y)."""


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _number(value: object) -> float:
    """Return a fetched number as a float."""
    return float(cast("float", value))


def _key(category: object) -> object:
    """Key a category: NaN as the one `_NAN`, any other value as itself."""
    if isinstance(category, float) and math.isnan(category):
        return _NAN
    return category


def _sorted(categories: Iterable[object]) -> list[object]:
    """Sort categories by value, NULL last; in the order given if they do not sort."""
    given = list(categories)
    present: list[Any] = [c for c in given if c is not None]
    try:
        ordered: list[object] = sorted(present)
    except TypeError:
        ordered = list(present)
    return [*ordered, *([None] * (len(given) - len(present)))]


def _totals(rows: Stats) -> tuple[int, Fraction, Fraction]:
    """Return the count and the exact sums of a set of statistics' rows."""
    n = sum(r[2] for r in rows)
    total = sum((Fraction(r[3]) for r in rows), Fraction(0))
    return n, total, sum((Fraction(r[4]) for r in rows), Fraction(0))


def _moments(n: int, total: Fraction, squares: Fraction) -> tuple[Fraction, Fraction]:
    """Return the exact mean and population variance (never below 0)."""
    mean = total / n
    return mean, max(squares / n - mean * mean, Fraction(0))


class TargetEncoder(Step):
    """Replace each category by the target's mean in it, shrunk towards the mean.

    Build it with `sq.encode.target <EncodeGroup>`. It learns from the
    target, so it is learned with ``learn(data, target=...)`` or ``train``.

    As scikit-learn's ``TargetEncoder``. With ``smooth="auto"``, a category
    of ``n`` rows whose target has mean ``μ`` and variance ``s²`` is encoded
    ``λ·μ + (1 - λ)·m``, where ``λ = n·v / (n·v + s²)``, and ``m`` and ``v``
    are the target's mean and variance over every row (both variances are
    the population's); with a number for `smooth`, ``(n·μ + smooth·m) / (n +
    smooth)``. A category not seen when learning gets ``m``; NULL is a
    category when it was seen, else it gets ``m`` too. The output is DOUBLE
    and replaces the column.

    A binary target (two values, or one) is first label-encoded, its smaller
    value 0 and its larger 1; a continuous one is used as it is. With
    ``target_type="auto"`` the target is continuous when it holds a value
    that is not whole, else binary; three or more whole values are a
    multiclass target, which is refused (it comes later). A text target is
    refused too: map it to numbers first.

    In ``train`` the rows the model trains on are cross-fitted, as
    scikit-learn's ``fit_transform``: each row is encoded with what was
    learned on the rows outside its own inner fold, and later steps learn
    from those values. The inner folds are sqlearn's: ``sq.folds.kfold(cv, seed)``
    dealt by each row's position in the data as read (rows alike get folds
    of their own, as scikit-learn's ``KFold`` deals them). ``apply`` after
    ``learn(data, target=...)``, and ``predict``, use what was learned on all
    rows (scikit-learn's ``fit`` then ``transform``).

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to encode; defaults to the text columns.
    keep : bool, default False
        Keep the input column and add the encoding beside it.
    smooth : "auto" or float, default "auto"
        How far a category's mean is shrunk towards the overall mean: found
        from the variances, or a number of rows' weight (at least 0).
    cv : int, default 5
        The number of inner folds of the cross-fitting, at least 2.
    seed : int, default 0
        The seed of the inner folds.
    target_type : {"auto", "binary", "continuous"}, default "auto"
        The kind of target; found from it by default.
    lookup : {"list", "hash"}, optional
        How a value is found among the learned categories; both give the
        same encodings. Left out, ``"list"``: ``list_position``, which
        compares the value with the categories one by one, honouring a
        column's collation. ``"hash"``: an MD5 perfect hash, whose cost per
        row barely grows with the count but whose SQL holds about 3.5
        constants per category, a fixed cost per query. On 1,000,000 rows
        from Parquet the target encoder applied slower with the hash at
        every count measured, up to 30,000 categories (20.3 s against
        12.6 s; ``docs/benchmarks/category-lookup.md``); it pays only on
        more rows than that, or more categories. The hash takes text columns
        alone (VARCHAR, ENUM) and compares the bytes exactly, ignoring a
        collation, which DuckDB does not report to a step. Unlike the
        ordinal encoder, the target encoder never warns about the lookup,
        however many categories it learns: the hash was slower for it in the
        benchmark.

    Attributes
    ----------
    categories_ : dict of str to list
        After learning, each column's categories, NULL left out.
    encodings_ : dict of str to list of float
        Each category's encoding, in the order of `categories_`.
    null_ : dict of str to float or None
        The encoding of NULL, or None when NULL was not seen.
    target_mean_ : dict of str to float
        The target's mean (label-encoded when binary): what an unseen
        category gets.
    target_type_ : dict of str to str
        ``"binary"`` or ``"continuous"``.

    Raises
    ------
    SqlearnError
        If `smooth`, `cv`, `seed`, `target_type` or `lookup` is not a setting
        it takes.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame(
    ...     {
    ...         "plan": ["a", "b"] * 5,
    ...         "day": range(10),
    ...         "y": [1, 0, 1, 1, 1, 0, 1, 0, 0, 1],
    ...     }
    ... )
    >>> pipe = sq.Pipeline([sq.encode.target("plan", smooth=0.0)])
    >>> pipe.learn(data, target="y").apply(data, out="pandas")["plan"].tolist()[:2]
    [0.8, 0.4]
    >>> pipe["target"].categories_, pipe["target"].target_mean_
    ({'plan': ['a', 'b']}, {'plan': 0.6})
    """

    static = True
    uses_target = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _string(),  # noqa: B008
        keep: bool = False,
        smooth: str | float = "auto",
        cv: int = 5,
        seed: int = 0,
        target_type: str = "auto",
        lookup: str | None = None,
    ) -> None:
        check_lookup("sq.encode.target", lookup)
        super().__init__(cols=cols, keep=keep)
        if smooth != "auto" and (
            isinstance(smooth, bool)
            or not isinstance(smooth, (int, float))
            or not smooth >= 0
        ):
            msg = (
                f"sq.encode.target got smooth={smooth!r}. Why: smooth is "
                '"auto" or the weight of the overall mean, a number at least 0. '
                'Fix: pass smooth="auto" or a number such as 10.0.'
            )
            raise SqlearnError(msg)
        if isinstance(cv, bool) or not isinstance(cv, int) or cv < 2:
            msg = (
                f"sq.encode.target got cv={cv!r}. Why: cross-fitting needs at "
                "least 2 inner folds, as a whole number. Fix: pass cv=5, say."
            )
            raise SqlearnError(msg)
        if isinstance(seed, bool) or not isinstance(seed, int):
            msg = (
                f"sq.encode.target got seed={seed!r}. Why: the seed is mixed "
                "into the inner folds' hash and must be a whole number. Fix: "
                "pass seed=0, say."
            )
            raise SqlearnError(msg)
        if target_type not in _TYPES:
            listed = ", ".join(repr(t) for t in _TYPES)
            msg = (
                f"sq.encode.target got target_type={target_type!r}. Why: the "
                f"types are {listed}; a multiclass target comes later. Fix: "
                "use one of them."
            )
            raise SqlearnError(msg)
        self.smooth = smooth
        self.cv = cv
        self.seed = seed
        self.target_type = target_type
        self.lookup = lookup

    def default_name(self) -> str:
        """Return ``target``.

        Returns
        -------
        str
            The name of the method.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.encode.target().default_name()
        'target'
        """
        return "target"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        defaults = TargetEncoder()
        kwargs: dict[str, object] = {}
        if self.cols != _string():
            kwargs["cols"] = self.cols
        for name in ("keep", "smooth", "cv", "seed", "target_type", "lookup"):
            if getattr(self, name) != getattr(defaults, name):
                kwargs[name] = getattr(self, name)
        return call_repr("sq.encode.target", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to encode, refusing ``lookup="hash"`` on non-text.

        Parameters
        ----------
        schema : list of (str, DuckDBPyType)
            The columns reaching the step.

        Returns
        -------
        list of str
            The chosen columns, in schema order.

        Raises
        ------
        StepError
            If the lookup is ``"hash"`` and a chosen column is not text.

        Examples
        --------
        >>> import sqlearn as sq
        >>> from duckdb.sqltypes import INTEGER, VARCHAR
        >>> sq.encode.target().inputs([("a", INTEGER), ("c", VARCHAR)])
        ['c']
        """
        chosen = super().inputs(schema)
        check_text("sq.encode.target", self.lookup, chosen, dict(schema))
        return chosen

    def learn(
        self, x: Expression, y: Expression | None = None
    ) -> Mapping[str, Expression]:
        """Learn the target's statistics per inner fold and category.

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
            ``stats``: count, sum and sum of squares of the target per inner
            fold and category; and, of the target, its type (``kind``), its
            extremes (``low``, ``high``), whether a value is not whole
            (``fractional``) and whether one is missing (``missing``).

        Raises
        ------
        StepError
            If no target is given.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> x, y = duckdb.ColumnExpression("a"), duckdb.ColumnExpression("y")
        >>> list(sq.encode.target().learn(x, y))
        ['stats', 'kind', 'low', 'high', 'fractional', 'missing']
        """
        if y is None:
            msg = (
                "learns from the target, but was given none. Fix: learn the "
                "pipeline with learn(data, target=...) or train."
            )
            raise StepError(msg, step="", position=0)
        number = y.try_cast(DOUBLE)
        fold = duckdb.ColumnExpression(inner_name(self.cv, self.seed))
        return {
            "stats": target_stats(x, number, fold),
            "kind": _fn("any_value", _fn("typeof", y)),
            "low": _fn("min", number),
            "high": _fn("max", number),
            "fractional": _fn("bool_or", number != _fn("floor", number)),
            "missing": _fn("bool_or", y.isnull() | _fn("isnan", number)),
        }

    def encodings(self, stats: Stats, k: int) -> dict[str, dict[object, float]]:
        """Encode every category on all rows and on each fold's complement.

        Parameters
        ----------
        stats : sequence of (int, object, int, float, float)
            Per inner fold and category: the fold, the category, the count,
            the sum of the target and the sum of its squares; the target
            already label-encoded when binary. Sums of the target less a
            constant (`target_stats` gives ``y - min(y)``) give encodings
            less that constant.
        k : int
            The number of inner folds.

        Returns
        -------
        dict of str to dict of object to float
            ``"all"``, then ``"0"`` to ``str(k - 1)`` (the rows outside that
            fold), each to every category seen in `stats` and its encoding. A
            category with no row in the rows used gets their mean, as does
            one whose encoding is undefined (no spread in the target nor in
            the category), as scikit-learn's.

        Examples
        --------
        >>> import sqlearn as sq
        >>> stats = [
        ...     (0, "a", 2, 2.0, 2.0),
        ...     (1, "a", 1, 0.0, 0.0),
        ...     (1, "b", 1, 0.0, 0.0),
        ... ]
        >>> sq.encode.target(smooth=0.0).encodings(stats, 2)["all"]
        {'a': 0.6666666666666666, 'b': 0.0}
        """
        return self._encodings(stats, k, 0.0)

    def _encodings(
        self, stats: Stats, k: int, offset: float
    ) -> dict[str, dict[object, float]]:
        """Encode as `encodings`, `offset` added before the one rounding.

        The formulae are computed exactly (`Fraction`) from the fetched
        sums, so each encoding is the double nearest their answer.
        """
        rows = [(f, _key(c), n, s, ss) for f, c, n, s, ss in stats]
        categories = _sorted(dict.fromkeys(r[1] for r in rows))
        shift = Fraction(offset)
        out: dict[str, dict[object, float]] = {}
        for key in ["all", *(str(i) for i in range(k))]:
            used = rows if key == "all" else [r for r in rows if r[0] != int(key)]
            if not used:
                out[key] = dict.fromkeys(categories, math.nan)
                continue
            mean, variance = _moments(*_totals(used))
            per: dict[object, list[tuple[int, float, float]]] = {}
            for _, c, n, s, ss in used:
                per.setdefault(c, []).append((n, s, ss))
            out[key] = {
                c: float(self._encode(per.get(c, []), mean, variance) + shift)
                for c in categories
            }
        return out

    def _encode(
        self, rows: list[tuple[int, float, float]], mean: Fraction, variance: Fraction
    ) -> Fraction:
        """Encode one category from its rows' statistics, as scikit-learn."""
        n = sum(r[0] for r in rows)
        total = sum((Fraction(r[1]) for r in rows), Fraction(0))
        if self.smooth != "auto":
            smooth = Fraction(self.smooth)
            return mean if n + smooth == 0 else (total + smooth * mean) / (n + smooth)
        if n == 0:
            return mean
        squares = sum((Fraction(r[2]) for r in rows), Fraction(0))
        mu, spread = _moments(n, total, squares)
        weight = n * variance + spread
        if weight == 0:
            return mean
        lam = n * variance / weight
        return lam * mu + (1 - lam) * mean

    def derive(
        self, values: Mapping[str, object], k: int
    ) -> dict[str, dict[str, object]]:
        """Find the target's type, label-encode it, and encode the categories.

        Parameters
        ----------
        values : mapping of str to object
            What `learn` fetched for one column.
        k : int
            The number of inner folds.

        Returns
        -------
        dict of str to dict of str to object
            ``"all"`` and ``"0"`` ... ``str(k - 1)``, each to ``categories``,
            ``encodings``, ``null``, ``target_mean`` and ``target_type``.

        Raises
        ------
        StepError
            If the target is text, missing in a row, multiclass, or a
            non-empty inner fold leaves no row to learn from.

        Examples
        --------
        >>> import sqlearn as sq
        >>> fetched = {
        ...     "stats": [(0, "a", 1, 1.0, 1.0), (1, "a", 1, 0.0, 0.0)],
        ...     "kind": "INTEGER",
        ...     "low": 0.0,
        ...     "high": 1.0,
        ...     "fractional": False,
        ...     "missing": False,
        ... }
        >>> sq.encode.target(smooth=0.0).derive(fetched, 2)["0"]["encodings"]
        [0.0]
        """
        kind = str(values["kind"])
        if kind not in _NUMBERS and not kind.startswith("DECIMAL"):
            msg = (
                f"learns from the target, which is {kind}: a text target "
                "(such as 'yes' and 'no') comes later. Fix: map it to numbers "
                "first, such as 1 for 'yes' and 0 for 'no'."
            )
            raise StepError(msg, step="", position=0)
        if values["missing"]:
            msg = (
                "learns from the target, which is missing (NULL or NaN) in "
                "some rows; a category's mean needs every row's answer. Fix: "
                "leave those rows out, or fill the target first."
            )
            raise StepError(msg, step="", position=0)
        stats = [
            (int(f), c, int(n), float(s), float(ss))
            for f, c, n, s, ss in cast("Stats", values["stats"])
        ]
        target_type = self._target_type(stats, values)
        # The statistics are of y - low (see `target_stats`): a binary target
        # is label-encoded by dividing by the width; a continuous one gets
        # low back on its encodings and mean.
        low, high = _number(values["low"]), _number(values["high"])
        offset = 0.0
        if target_type == "binary":
            width = high - low
            stats = [
                (f, c, n, enc, enc)
                for f, c, n, s, _ in stats
                for enc in [s / width if width else 0.0]
            ]
        else:
            offset = low
        self._check_folds(stats, k)
        encoded = self._encodings(stats, k, offset)
        out: dict[str, dict[str, object]] = {}
        for key, table in encoded.items():
            used = stats if key == "all" else [r for r in stats if r[0] != int(key)]
            known = [c for c in table if c is not None]
            mean = (
                float(_moments(*_totals(used))[0] + Fraction(offset))
                if used
                else math.nan
            )
            out[key] = {
                "categories": known,
                "encodings": [table[c] for c in known],
                "null": table.get(None),
                "target_mean": mean,
                "target_type": target_type,
            }
        return out

    def _target_type(self, stats: Stats, values: Mapping[str, object]) -> str:
        """Find the target's type as scikit-learn's ``type_of_target`` does.

        A value that is not whole makes it continuous. Otherwise it is
        binary when it holds at most two values: every value is then one of
        the extremes, so ``Σ (y - low)(y - high)``, from the sums of ``y -
        low`` as ``Σ (y - low)² - width · Σ (y - low)``, is 0, while a value
        between them makes a term below 0. Whole values give whole sums,
        exact in a double below 2**53, so the sum is then at most -1; values
        that are not whole (``target_type="binary"`` given) are judged within
        rounding.
        """
        fractional = bool(values["fractional"])
        if self.target_type == "continuous":
            return "continuous"
        if self.target_type == "auto" and fractional:
            return "continuous"
        width = _number(values["high"]) - _number(values["low"])
        n, total, squares = _totals(stats)
        between = squares - width * total
        limit = 1e-9 * width * width * n if fractional else 0.5
        if between < -limit:
            what = "values" if fractional else "whole values"
            msg = (
                f"learns from the target, which holds more than two {what}: "
                "a multiclass target, which comes later. Fix: pass "
                'target_type="continuous" to treat it as a number, or give a '
                "binary target."
            )
            raise StepError(msg, step="", position=0)
        return "binary"

    @staticmethod
    def _check_folds(stats: Stats, k: int) -> None:
        """Refuse an inner fold holding every row: its rows learn from none."""
        folds = {r[0] for r in stats}
        if len(folds) == 1 and k > 1:
            (only,) = folds
            msg = (
                f"deals every row into inner fold {only} of {k}, so those rows "
                "have no other rows to be encoded from. Fix: pass more data, "
                "or fewer folds with cv=."
            )
            raise StepError(msg, step="", position=0)

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Look each value up among the learned categories.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            The category's encoding, a DOUBLE; the target's mean for a value
            not seen, and for NULL unless NULL was seen.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> learned = Learned.values(
        ...     {
        ...         "categories": ["a"],
        ...         "encodings": [0.75],
        ...         "null": None,
        ...         "target_mean": 0.5,
        ...     }
        ... )
        >>> rel = duckdb.sql("SELECT * FROM (VALUES ('a'), ('b'), (NULL)) t(c)")
        >>> out = sq.encode.target().apply(duckdb.ColumnExpression("c"), learned)
        >>> rel.select(out).fetchall()
        [(0.75,), (0.5,), (0.5,)]
        """
        categories = learned.categories
        encodings = learned.encodings
        mean = learned.raw("target_mean")
        null = learned.raw("null")
        fallback = const(_number(mean)).cast(DOUBLE)
        found: Expression = fallback
        if isinstance(categories, list) and categories:
            at = position(x, categories, self.lookup or "list")
            found = duckdb.CoalesceOperator(
                _fn("list_extract", const(encodings), at), fallback
            )
        when_null = fallback if null is None else const(_number(null))
        return (
            duckdb.CaseExpression(x.isnull(), when_null.cast(DOUBLE))
            .otherwise(found)
            .cast(DOUBLE)
        )

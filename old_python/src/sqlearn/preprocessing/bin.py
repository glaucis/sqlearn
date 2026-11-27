"""Bin: put numbers into bins, ``sq.bin`` and its shortcuts.

``sq.bin.uniform`` and ``sq.bin.quantile`` learn the edges of the bins
(`Bin`); ``sq.bin.binarize`` compares with a threshold and learns nothing
(`Binarize`).
"""

import itertools
import math
import warnings
from collections.abc import Mapping, Sequence
from typing import TypedDict, Unpack, cast

import duckdb
from duckdb import Expression
from duckdb.sqltypes import DOUBLE, INTEGER

from sqlearn._errors import PACKAGE_FILES, SqlearnError, SqlearnWarning
from sqlearn._expr import const, is_missing
from sqlearn._group import Group, call_repr, columns_arg
from sqlearn._selectors import Schema, Selector
from sqlearn._step import Learned, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing._missing import (
    infinite,
    refuse_all_missing,
    refuse_infinite,
)
from sqlearn.preprocessing.scale import _numeric_inputs

__all__ = ["Bin", "BinGroup", "Binarize", "bin"]

METHODS = ("uniform", "quantile")
"""The ways `Bin` places its edges, as ``KBinsDiscretizer``'s strategies."""

N_BINS = 5
"""The number of bins asked for by default, as scikit-learn's."""

WIDTH = 1e-8
"""The width at or below which scikit-learn merges a quantile bin away."""

_QUANTILE_METHOD = "averaged_inverted_cdf"
"""The quantile method of scikit-learn 1.9's ``KBinsDiscretizer``."""

_WHY_NUMBERS = "binning compares each value with numbers"


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _n(n: object) -> int:
    """Return `n` when it is a whole number of bins, at least 2, else refuse it."""
    if isinstance(n, int) and not isinstance(n, bool) and n >= 2:
        return n
    msg = (
        f"sq.bin got n={n!r}, which is not a number of bins. Why: n is how "
        "many bins to make, a whole number at least 2, as scikit-learn's "
        "n_bins. Fix: give one, such as n=5."
    )
    raise SqlearnError(msg)


def _threshold(threshold: object) -> float:
    """Return `threshold` when it is a finite number, else refuse it."""
    if (
        isinstance(threshold, int | float)
        and not isinstance(threshold, bool)
        and math.isfinite(threshold)
    ):
        return threshold
    msg = (
        f"sq.bin.binarize got threshold={threshold!r}, which is not a "
        "threshold. Why: each value is compared with it, so it is a finite "
        "number. Fix: give one, such as threshold=0.0."
    )
    raise SqlearnError(msg)


def _percent_level(i: int, n: int) -> float:
    """Return the share of the `i`-th of `n` quantile edges, as scikit-learn's.

    scikit-learn asks numpy for the percentiles ``np.linspace(0, 100, n +
    1)``, each divided by 100. That is ``i * (100 / n) / 100`` in doubles,
    which is not always ``i / n`` (for ``n = 3``, ``0.33333333333333337``),
    and the quantile method is exact about whole ranks, so the difference
    can choose another value.
    """
    return i * (100 / n) / 100


class Bin(Step):
    """Put each value into one of `n` bins, written as its index from 0.

    Build it with `sq.bin.uniform <BinGroup>` or `sq.bin.quantile
    <BinGroup>`. As scikit-learn's ``KBinsDiscretizer(encode="ordinal")``,
    it learns the edges between the bins over the column's present values
    (neither NULL nor NaN):

    ========  ==========================================  =================
    method    the inner edges, for ``i = 1 ... n - 1``     scikit-learn
    ========  ==========================================  =================
    uniform   ``min + i * ((max - min) / n)``             ``"uniform"``
    quantile  the exact quantile at ``i / n``             ``"quantile"``
    ========  ==========================================  =================

    The quantiles are numpy's ``averaged_inverted_cdf``, the default of
    scikit-learn 1.9 (which sorts all the rows: it is given
    ``subsample=None``), at the shares scikit-learn computes. As
    scikit-learn does, a quantile edge within ``1e-8`` of the edge before it
    (the minimum first) is merged away, so there are fewer bins, and a
    constant column has one bin; either is said with a `SqlearnWarning`.

    A value's bin is the number of inner edges at or below it (numpy's
    ``searchsorted(side="right")``, as scikit-learn), so a value below the
    minimum is in bin 0 and one above the maximum in the last. The output
    is INTEGER and replaces the column; NULL and NaN stay NULL. A column
    holding infinity is refused, as is one with no present value.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to bin; by default the numeric ones.
    method : {"uniform", "quantile"}, default "quantile"
        How the edges are placed.
    n : int, default 5
        The number of bins, at least 2.
    keep : bool, default False
        Keep the input column and add the bin beside it.
    suffix : str, optional
        Suffix of the bin's column when `keep` is True; defaults to the
        step's name.

    Attributes
    ----------
    edges_ : dict of str to list of float
        After learning, each column's inner edges, merged ones left out.

    Raises
    ------
    SqlearnError
        If `method` is not a method or `n` not a number of bins.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0]})
    >>> pipe = sq.Pipeline([sq.bin.uniform(n=4)]).learn(data)
    >>> pipe["uniform"].edges_
    {'x': [1.0, 2.0, 3.0]}
    >>> pipe.apply(data, out="pandas")["x"].tolist()
    [0, 1, 2, 3, 3]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        method: str = "quantile",
        n: int = N_BINS,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        if method == "binarize":
            msg = (
                "Bin got method='binarize'. Why: binarize compares with a "
                "threshold and learns no edges, a step of its own (Binarize). "
                "Fix: build it with sq.bin.binarize(), or search over whole "
                "steps."
            )
            raise SqlearnError(msg)
        if method not in METHODS:
            names = ", ".join(repr(m) for m in (*METHODS, "binarize"))
            msg = (
                f"sq.bin got method={method!r}, which is not a method. Why: the "
                f"methods are {names}. Fix: use one of them, or a shortcut "
                "such as sq.bin.quantile()."
            )
            raise SqlearnError(msg)
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.method = method
        self.n = _n(n)

    def default_name(self) -> str:
        """Return the method.

        Returns
        -------
        str
            ``uniform`` or ``quantile``.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin(method="uniform", n=3).default_name()
        'uniform'
        """
        return self.method

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.n != N_BINS:
            kwargs["n"] = self.n
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr(f"sq.bin.{self.method}", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to bin, refusing any that is not numeric.

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
        >>> sq.bin().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(self.cols, schema, "bin", _WHY_NUMBERS)

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the inner edges and whether the column holds infinity.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``edges``: the inner edges, a list of DOUBLE (empty for a
            constant column, NULL for one with no present value), quantile
            edges within ``1e-8`` of the one before merged away; and
            ``infinite`` (infinity where the column holds any, else 0).

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.bin.quantile().learn(duckdb.ColumnExpression("a")))
        ['edges', 'infinite']
        """
        low, high = agg.min(x).cast(DOUBLE), agg.max(x).cast(DOUBLE)
        n = self.n
        if self.method == "uniform":
            # As numpy's linspace: the step first, then i steps from the minimum.
            step = (high - low) / const(float(n))
            edges = _fn(
                "list_value", *(const(float(i)) * step + low for i in range(1, n))
            )
        else:
            quantiles = [
                agg.quantile(x, q=_percent_level(i, n), method=_QUANTILE_METHOD)
                for i in range(1, n)
            ]
            full = [low, *quantiles, high]
            # scikit-learn keeps an edge more than 1e-8 above the one before
            # it (the minimum always), then drops the first and last kept.
            wide = [const(True)] + [
                b - a > const(WIDTH) for a, b in itertools.pairwise(full)
            ]
            kept = _fn("list_where", _fn("list_value", *full), _fn("list_value", *wide))
            edges = _fn("list_slice", kept, const(2), const(-2))
        none = const(None).cast("DOUBLE[]")
        empty = const([]).cast("DOUBLE[]")
        learned = (
            duckdb.CaseExpression(low.isnull(), none)
            .when(low == high, empty)
            .otherwise(edges)
        )
        return {"edges": learned, "infinite": infinite(x)}

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Write the bin: the number of inner edges at or below the value.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            The values learned for the column.

        Returns
        -------
        duckdb.Expression
            The bin as INTEGER, from 0; NULL where the value is missing.

        Raises
        ------
        StepError
            If every value of the column was missing, or any is infinite.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> x = duckdb.ColumnExpression("a")
        >>> learned = Learned.values({"edges": [1.5, 2.5], "infinite": 0.0})
        >>> "2.5" in str(sq.bin.uniform(n=3).apply(x, learned))
        True
        """
        refuse_all_missing(x, learned, "edges")
        refuse_infinite(x, learned, "infinite")
        edges = learned.edges
        if isinstance(edges, list):
            bounds = [const(float(e)) for e in edges]
        else:
            # Placeholders: the edges are a list in the learn stage, at most
            # n - 1 long; an edge past its end is NULL and counts nothing.
            listed = cast("Expression", edges)
            bounds = [_fn("list_extract", listed, const(k)) for k in range(1, self.n)]
        v = x.cast(DOUBLE)
        at_or_below = [
            duckdb.CaseExpression(v >= b, const(1)).otherwise(const(0)) for b in bounds
        ]
        index = (
            _fn("list_sum", _fn("list_value", *at_or_below))
            if at_or_below
            else const(0)
        )
        keep_null = duckdb.CaseExpression(is_missing(x), const(None))
        return keep_null.otherwise(index).cast(INTEGER)

    def learned(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Warn of each column with fewer bins than asked for, as scikit-learn.

        Called once per ``learn`` or ``train``, as scikit-learn's ``fit``
        warns: edges were merged away, or the column is constant.

        Parameters
        ----------
        values : mapping of str to mapping of str to object
            Column, then learned name, to the value learned.

        Warns
        -----
        SqlearnWarning
            For each column with fewer than `n` bins, naming it.

        Examples
        --------
        >>> import warnings
        >>> import sqlearn as sq
        >>> with warnings.catch_warnings(record=True) as caught:
        ...     warnings.simplefilter("always")
        ...     sq.bin.uniform(n=3).learned({"x": {"edges": []}})
        >>> str(caught[0].message).startswith("sq.bin: column 'x' has 1 bin, not 3")
        True
        """
        for column, learned in values.items():
            edges = learned.get("edges")
            if not isinstance(edges, list) or len(edges) + 1 >= self.n:
                continue
            bins = len(edges) + 1
            noun = "bin" if bins == 1 else "bins"
            text = (
                f"sq.bin: column {column!r} has {bins} {noun}, not {self.n}. "
                f"Why: {self.method} bins of width 1e-8 or less are merged "
                "away, as scikit-learn merges them, and a constant column has "
                "one bin. Fix: ask for fewer bins, or bin the column uniformly."
            )
            warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)


class Binarize(Step):
    """Write 1 where a value is above a threshold, else 0.

    Build it with `sq.bin.binarize <BinGroup>`. As scikit-learn's
    ``Binarizer``: a value equal to the threshold is 0. It learns nothing.
    The output is INTEGER and replaces the column; NULL and NaN stay NULL.

    Parameters
    ----------
    cols : Selector or str or sequence of str, optional
        The columns to compare; by default the numeric ones.
    threshold : float, default 0.0
        Values above it become 1, the rest 0.
    keep : bool, default False
        Keep the input column and add the result beside it.
    suffix : str, optional
        Suffix of the result's column when `keep` is True; defaults to the
        step's name.

    Raises
    ------
    SqlearnError
        If `threshold` is not a finite number.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"x": [-1.0, 0.0, 2.5]})
    >>> pipe = sq.Pipeline([sq.bin.binarize()]).learn(data)
    >>> pipe.apply(data, out="pandas")["x"].tolist()
    [0, 0, 1]
    """

    static = True

    def __init__(
        self,
        cols: Selector | str | tuple[str, ...] | list[str] | None = None,
        threshold: float = 0.0,
        keep: bool = False,
        suffix: str | None = None,
    ) -> None:
        super().__init__(cols=cols, keep=keep, suffix=suffix)
        self.threshold = _threshold(threshold)

    def default_name(self) -> str:
        """Return ``binarize``.

        Returns
        -------
        str
            ``binarize``, whatever the threshold.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin.binarize(threshold=2.0).default_name()
        'binarize'
        """
        return "binarize"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.cols is not None:
            kwargs["cols"] = self.cols
        if self.threshold != 0:
            kwargs["threshold"] = self.threshold
        if self.keep:
            kwargs["keep"] = True
        if self.suffix is not None:
            kwargs["suffix"] = self.suffix
        return call_repr("sq.bin.binarize", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to compare, refusing any that is not numeric.

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
        >>> sq.bin.binarize().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(self.cols, schema, "binarize", _WHY_NUMBERS)

    def apply(self, x: Expression, learned: Learned) -> Expression:
        """Write 1 where the value is above the threshold, else 0.

        Parameters
        ----------
        x : duckdb.Expression
            The column.
        learned : Learned
            Unused: the step learns nothing.

        Returns
        -------
        duckdb.Expression
            1 or 0 as INTEGER; NULL where the value is missing.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> x = duckdb.ColumnExpression("a")
        >>> "0.5" in str(sq.bin.binarize(threshold=0.5).apply(x, Learned.values({})))
        True
        """
        above = x.cast(DOUBLE) > const(float(self.threshold))
        return (
            duckdb.CaseExpression(is_missing(x), const(None))
            .when(above, const(1))
            .otherwise(const(0))
            .cast(INTEGER)
        )


class _Settings(TypedDict, total=False):
    """The settings every shortcut passes on."""

    cols: Selector | str | Sequence[str] | None
    keep: bool
    suffix: str | None


class BinGroup(Group):
    """Bin numeric columns: ``sq.bin(cols, method=...)`` and its shortcuts.

    Called, it is the general form: `method` picks how. Each shortcut is a
    method, and builds exactly the step the general form builds with it.
    A bin is written as its index from 0; to one-hot encode the bins, put
    `sq.encode.onehot <EncodeGroup>` after the step.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.bin.quantile("age", n=4)
    sq.bin.quantile(cols='age', n=4)
    >>> sq.bin("age", method="uniform")
    sq.bin.uniform(cols='age')
    >>> sq.bin(method="binarize", threshold=1.5)
    sq.bin.binarize(threshold=1.5)
    """

    def __call__(
        self,
        *names: object,
        method: str = "quantile",
        n: int = N_BINS,
        threshold: float = 0.0,
        cols: Selector | str | Sequence[str] | None = None,
        keep: bool = False,
        suffix: str | None = None,
    ) -> Bin | Binarize:
        """Build the step that bins columns by `method`.

        Parameters
        ----------
        *names : str or list of str
            The columns: names or one list; by default the numeric ones.
        method : {"uniform", "quantile", "binarize"}, default "quantile"
            How: bins of equal width, bins of equal count, or a threshold
            (a `Binarize`).
        n : int, default 5
            The number of bins of ``uniform`` and ``quantile``.
        threshold : float, default 0.0
            The threshold of ``binarize``.
        cols : Selector or str or sequence of str, optional
            The columns, as a selector; not given with `names`.
        keep : bool, default False
            Keep the input column beside the result.
        suffix : str, optional
            Suffix of the result's column when `keep` is True.

        Returns
        -------
        Bin or Binarize
            The step: a `Binarize` for ``method="binarize"``.

        Raises
        ------
        SqlearnError
            If names and `cols` are both given, a dict is given, `method` is
            not a method, or ``binarize`` is given an `n` or another method
            a `threshold`.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin(cols=sq.cols("a", "b"), method="quantile", n=10)
        sq.bin.quantile(cols=cols('a', 'b'), n=10)
        """
        chosen = columns_arg(names, cols, allow_dict=False)
        columns = cast("str | list[str] | Selector | None", chosen)
        if method == "binarize":
            if n != N_BINS:
                msg = (
                    f"sq.bin got method='binarize' and n={n!r}. Why: binarize "
                    "compares with a threshold, so it has no number of bins. "
                    "Fix: leave n= out, or use method='uniform' or 'quantile'."
                )
                raise SqlearnError(msg)
            return Binarize(cols=columns, threshold=threshold, keep=keep, suffix=suffix)
        if threshold != 0:
            msg = (
                f"sq.bin got method={method!r} and threshold={threshold!r}. "
                "Why: only binarize compares with a threshold. Fix: leave "
                "threshold= out, or use method='binarize'."
            )
            raise SqlearnError(msg)
        return Bin(cols=columns, method=method, n=n, keep=keep, suffix=suffix)

    def uniform(self, *names: object, n: int = N_BINS, **kw: Unpack[_Settings]) -> Bin:
        """Make `n` bins of equal width between the minimum and the maximum.

        As scikit-learn's ``KBinsDiscretizer(strategy="uniform",
        encode="ordinal")`` (``method="uniform"``): it learns the minimum and
        the maximum.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        n : int, default 5
            The number of bins.
        **kw : object
            The general form's other settings (``cols``, ``keep``,
            ``suffix``).

        Returns
        -------
        Bin
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin.uniform("age", n=10)
        sq.bin.uniform(cols='age', n=10)
        """
        return cast("Bin", self(*names, method="uniform", n=n, **kw))

    def quantile(self, *names: object, n: int = N_BINS, **kw: Unpack[_Settings]) -> Bin:
        """Make `n` bins holding about as many values each.

        As scikit-learn's ``KBinsDiscretizer(strategy="quantile",
        encode="ordinal")`` (``method="quantile"``): it learns the ``n - 1``
        inner quantiles, exactly, by sorting; edges within ``1e-8`` merge.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        n : int, default 5
            The number of bins.
        **kw : object
            The general form's other settings (``cols``, ``keep``,
            ``suffix``).

        Returns
        -------
        Bin
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin.quantile(n=4)
        sq.bin.quantile(n=4)
        """
        return cast("Bin", self(*names, method="quantile", n=n, **kw))

    def binarize(
        self, *names: object, threshold: float = 0.0, **kw: Unpack[_Settings]
    ) -> Binarize:
        """Write 1 above `threshold`, else 0 (``method="binarize"``).

        As scikit-learn's ``Binarizer``: a value equal to the threshold is
        0, and nothing is learned.

        Parameters
        ----------
        *names : str or list of str
            The columns; by default the numeric ones.
        threshold : float, default 0.0
            Values above it become 1.
        **kw : object
            The general form's other settings (``cols``, ``keep``,
            ``suffix``).

        Returns
        -------
        Binarize
            The step.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.bin.binarize("score", threshold=0.5)
        sq.bin.binarize(cols='score', threshold=0.5)
        """
        return cast(
            "Binarize", self(*names, method="binarize", threshold=threshold, **kw)
        )


bin = BinGroup("bin")
"""The binning steps: ``sq.bin(...)``, ``sq.bin.quantile(...)`` and so on."""

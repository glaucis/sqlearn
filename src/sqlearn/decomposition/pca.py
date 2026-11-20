"""PCA: the principal components of the numeric columns, learned from XᵀX."""

import math
import numbers
import warnings
from collections.abc import Mapping, Sequence
from typing import ClassVar, cast

import duckdb
import numpy as np
from duckdb import Expression
from duckdb.sqltypes import DOUBLE

from sqlearn._errors import PACKAGE_FILES, SqlearnError, SqlearnWarning, StepError
from sqlearn._expr import const, is_missing
from sqlearn._group import call_repr
from sqlearn._selectors import Schema, Selector, _numeric
from sqlearn._step import Learned, Step
from sqlearn.agg import aggregates as agg
from sqlearn.preprocessing.scale import EPS, _numeric_inputs

__all__ = ["PCA"]


def _n_components(value: object) -> int | float | None:
    """Return `n_components` when it is a setting, else refuse it (spec §4.1).

    None, a whole number from 0 up (a numpy one too) or a fraction strictly
    between 0 and 1, as scikit-learn's checks take; a bool, ``1.0``, any
    other number and any text (``"mle"`` too) are refused.
    """
    if value is None:
        return None
    number = isinstance(value, numbers.Real) and not isinstance(value, bool)
    whole = isinstance(value, numbers.Integral)
    if number and whole and int(cast("int", value)) >= 0:
        return int(cast("int", value))
    if number and not whole and 0 < float(cast("float", value)) < 1:
        return float(cast("float", value))
    msg = (
        f"sq.decompose.pca got n_components={value!r}. Why: it is None (as "
        "many components as the smaller of the rows and the columns), a "
        "whole number from 0 up, or a fraction strictly between 0 and 1 (the "
        "share of the variance to explain), as scikit-learn's PCA takes; "
        "'mle' is not supported. Fix: give such a value, such as "
        "n_components=2 or n_components=0.95."
    )
    raise SqlearnError(msg)


def _whiten(value: object) -> bool:
    """Return `value` when it is a bool, else refuse it."""
    if isinstance(value, bool):
        return value
    msg = (
        f"sq.decompose.pca got whiten={value!r}. Why: whiten is on or off. "
        "Fix: give whiten=True or whiten=False."
    )
    raise SqlearnError(msg)


def _refuse_too_many(n_components: object, rows: int, columns: int) -> None:
    """Refuse a whole number of components above the smaller of rows and columns."""
    most = min(rows, columns)
    if type(n_components) is int and n_components > most:
        msg = (
            f"cannot keep n_components={n_components} components of "
            f"{columns} columns and {rows} rows. Why: there are at most as "
            "many components as the smaller of the rows and the columns "
            f"({most}), as scikit-learn's PCA checks. Fix: give "
            f"n_components={most} or fewer, or None for all."
        )
        raise StepError(msg, step="", position=0)


def _kept_components(
    n_components: float | None, rows: int, variances: Sequence[float]
) -> int:
    """Return how many components to keep: scikit-learn's ``n_components_``.

    Parameters
    ----------
    n_components : int or float or None
        The setting: None for the smaller of `rows` and the column count, a
        whole number for itself, a fraction for the fewest components whose
        cumulative explained variance ratio is above it (scikit-learn's
        ``searchsorted(..., side="right") + 1``).
    rows : int
        The rows learned from.
    variances : sequence of float
        Every component's explained variance, largest first: one per column.

    Returns
    -------
    int
        The number of components kept.

    Raises
    ------
    StepError
        If a whole number is above the smaller of `rows` and the column
        count, as scikit-learn refuses it at fit.

    Examples
    --------
    >>> from sqlearn.decomposition.pca import _kept_components
    >>> _kept_components(None, 10, [3.0, 1.0, 0.0])
    3
    >>> _kept_components(0.7, 10, [3.0, 1.0, 0.0])
    1
    >>> _kept_components(0.75, 10, [3.0, 1.0, 0.0])
    2
    """
    columns = len(variances)
    if n_components is None:
        return min(rows, columns)
    if isinstance(n_components, int):
        _refuse_too_many(n_components, rows, columns)
        return n_components
    ratios = np.cumsum(_ratios(variances))
    return int(np.searchsorted(ratios, n_components, side="right")) + 1


def _ratios(variances: Sequence[float]) -> np.ndarray:
    """Return each variance over their sum: all NaN when the sum is 0."""
    values = np.asarray(variances, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return values / values.sum()


def _refusal(name: str, found: str, fix: str) -> Expression:
    """Return ``error(...)``: a refusal DuckDB raises when the row is fetched."""
    msg = (
        f"sq.decompose.pca found {found} in column {name!r}. Why: each "
        "output is a sum over every value of the row, and scikit-learn's PCA "
        f"refuses it too. Fix: {fix}"
    )
    return duckdb.FunctionExpression("error", const(msg))


_MISSING = (
    "a missing value (NULL or NaN)",
    "impute the column first, such as with sq.impute() before this step.",
)
_INFINITE = (
    "an infinite value",
    "replace or drop the infinite values before this step.",
)


class PCA(Step):
    """Project the numeric columns on their principal components.

    Build it with `sq.decompose.pca <DecomposeGroup>`. As scikit-learn's
    ``PCA(svd_solver="covariance_eigh")``: it learns each input column's
    mean in SQL, then the covariance of the centred rows from their Gram
    matrix XᵀX, which numpy builds from batches DuckDB streams (ADR 0058),
    and its eigenvectors, largest eigenvalue first, each with the sign that
    makes its largest entry in absolute value positive. It keeps the whole
    decomposition, whatever `n_components`, so a change of `n_components`
    or `whiten` never learns again. A missing value (NULL or NaN), an
    infinite value and fewer than two rows are refused at learn, before any
    batch.

    Applying is one SQL expression per output, ``pca0`` to ``pca{k-1}``,
    replacing the input columns and placed after the last of them, as every
    whole-row step places the columns it creates: the centred values times
    the weights, as constants. A missing or infinite value at apply is
    refused when its row is fetched.

    Parameters
    ----------
    n_components : int or float, optional
        How many components to keep: None for the smaller of the rows and
        the columns; a whole number from 0 up to that; a fraction strictly
        between 0 and 1 for the fewest components explaining more than that
        share of the variance.
    whiten : bool, default False
        Whether to divide each output by the square root of its explained
        variance, as scikit-learn does.
    cols : Selector or str or sequence of str, optional
        The columns to decompose; by default the numeric ones.

    Attributes
    ----------
    components_ : list of list of float
        After learning, the kept components, largest first: each a list of
        one weight per input column.
    explained_variance_, explained_variance_ratio_, singular_values_ : list of float
        After learning, each kept component's variance, its share of the
        total variance, and its singular value.
    mean_ : list of float
        After learning, each input column's mean.
    n_components_, n_samples_ : int
        After learning, the components kept and the rows learned from.
    noise_variance_ : float
        After learning, the mean variance of the components not kept, as
        scikit-learn's probabilistic PCA estimates it (0 when none is left
        out of the smaller of the rows and the columns).

    Raises
    ------
    SqlearnError
        If `n_components` or `whiten` is not a setting.

    Examples
    --------
    >>> import pandas as pd
    >>> import sqlearn as sq
    >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 4.0, 6.5]})
    >>> pca = sq.Pipeline([sq.decompose.pca(n_components=1)]).learn(data)["pca"]
    >>> [round(w, 4) for w in pca.components_[0]]
    [0.405, 0.9143]
    """

    gram = True
    dynamic = True
    rowwise = True
    names_are_labels: ClassVar[bool] = False
    output_settings: ClassVar[frozenset[str]] = frozenset({"n_components", "whiten"})

    def __init__(
        self,
        n_components: float | None = None,
        whiten: bool = False,
        cols: Selector | str | tuple[str, ...] | list[str] | None = _numeric(),  # noqa: B008
    ) -> None:
        super().__init__(cols=cols)
        self.n_components = _n_components(n_components)
        self.whiten = _whiten(whiten)

    def default_name(self) -> str:
        """Return ``pca``.

        Returns
        -------
        str
            ``pca``, whatever the settings.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.decompose.pca(n_components=2).default_name()
        'pca'
        """
        return "pca"

    def __repr__(self) -> str:
        """Return the shortest call that rebuilds the step."""
        kwargs: dict[str, object] = {}
        if self.n_components is not None:
            kwargs["n_components"] = self.n_components
        if self.whiten:
            kwargs["whiten"] = True
        if self.cols != _numeric():
            kwargs["cols"] = self.cols
        return call_repr("sq.decompose.pca", **kwargs)

    def inputs(self, schema: Schema) -> list[str]:
        """Return the columns to decompose, refusing any that is not numeric.

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
        >>> sq.decompose.pca().inputs([("a", DOUBLE), ("c", VARCHAR)])
        ['a']
        """
        return _numeric_inputs(
            self.cols, schema, "decompose", "PCA takes the covariance of numbers"
        )

    def learn(self, x: Expression) -> Mapping[str, Expression]:
        """Learn the column's mean, its count, and its missing and infinite values.

        Parameters
        ----------
        x : duckdb.Expression
            The column.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``mean`` (`sqlearn.agg.mean`, DOUBLE) and ``count`` (the present
            values), which centre the rows; ``missing`` (NULL or NaN) and
            ``infinite``, the rows `before_gram` refuses.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> list(sq.decompose.pca().learn(duckdb.ColumnExpression("a")))
        ['mean', 'count', 'missing', 'infinite']
        """
        infinite = duckdb.FunctionExpression("isinf", x.cast(DOUBLE))
        return {
            "mean": agg.mean(x),
            "count": agg.count(x),
            "missing": duckdb.FunctionExpression("count_if", is_missing(x)),
            "infinite": duckdb.FunctionExpression("count_if", infinite),
        }

    def before_gram(self, learned: Mapping[str, Mapping[str, object]]) -> None:
        """Refuse a missing or infinite value, one row, or too many components.

        Parameters
        ----------
        learned : mapping of str to mapping of str to object
            What `learn` returned: learned name, then column, to value.

        Raises
        ------
        StepError
            If a column has a missing (NULL or NaN) or an infinite value,
            there are fewer than two rows, or `n_components` is a whole
            number above the smaller of the rows and the columns.

        Examples
        --------
        >>> import sqlearn as sq
        >>> values = {"count": {"a": 3}, "missing": {"a": 0}, "infinite": {"a": 0}}
        >>> sq.decompose.pca().before_gram(values) is None
        True
        """
        for column, missing in learned["missing"].items():
            if cast("int", missing):
                msg = (
                    f"cannot decompose column {column!r}, which has "
                    f"{missing} missing values (NULL or NaN). Why: PCA "
                    "takes every row's value, and scikit-learn's PCA "
                    "refuses a missing one. Fix: fill them first with "
                    "sq.impute, or leave those rows out."
                )
                raise StepError(msg, step="", position=0)
        for column, infinite in learned["infinite"].items():
            if cast("int", infinite):
                msg = (
                    f"cannot decompose column {column!r}, which has "
                    f"{infinite} infinite values. Why: PCA takes every row's "
                    "value, and scikit-learn's PCA refuses an infinite one. "
                    "Fix: clip or replace them first, or leave those rows out."
                )
                raise StepError(msg, step="", position=0)
        counts = learned["count"]
        rows = cast("int", next(iter(counts.values()), 0))
        if rows < 2:
            msg = (
                f"cannot decompose {rows} row{'' if rows == 1 else 's'}. Why: "
                "PCA divides the covariance by the rows less one, so it needs "
                "two rows at least. Fix: learn on more rows."
            )
            raise StepError(msg, step="", position=0)
        _refuse_too_many(self.n_components, rows, len(counts))

    def learned_from_gram(
        self, gram: np.ndarray, learned: Mapping[str, Mapping[str, object]]
    ) -> Mapping[str, Mapping[str, object]]:
        """Learn every component and its variance from XᵀX of the centred rows.

        Parameters
        ----------
        gram : numpy.ndarray
            The p-by-p sum of ``xᵀx`` over the centred rows, in input order.
        learned : mapping of str to mapping of str to object
            What `learn` returned: learned name, then column, to value.

        Returns
        -------
        mapping of str to mapping of str to object
            For the input column at position j: ``weights``, the j-th entry
            of every component (p floats, largest component first), and
            ``variance``, the j-th largest eigenvalue of the covariance
            (negative ones set to 0). The whole decomposition, never cut.

        Examples
        --------
        >>> import numpy as np
        >>> import sqlearn as sq
        >>> gram = np.array([[2.0, 0.0], [0.0, 8.0]])
        >>> got = sq.decompose.pca().learned_from_gram(
        ...     gram, {"count": {"a": 3, "b": 3}}
        ... )
        >>> got["variance"], got["weights"]
        ({'a': 4.0, 'b': 1.0}, {'a': [0.0, 1.0], 'b': [1.0, 0.0]})
        """
        columns = list(learned["count"])
        rows = cast("int", learned["count"][columns[0]])
        values, vectors = np.linalg.eigh(gram / (rows - 1))
        values, vectors = values[::-1].clip(min=0.0), vectors[:, ::-1]
        components = vectors.T.copy()  # rows are components
        p = len(columns)
        largest = np.abs(components).argmax(axis=1)
        signs = np.sign(components[np.arange(p), largest])
        components *= signs[:, None]
        return {
            "weights": {
                c: [float(w) for w in components[:, j]] for j, c in enumerate(columns)
            },
            "variance": {c: float(values[j]) for j, c in enumerate(columns)},
        }

    def learned(self, values: Mapping[str, Mapping[str, object]]) -> None:
        """Warn when every input column is constant: the ratios are NaN.

        Parameters
        ----------
        values : mapping of str to mapping of str to object
            Column, then learned name, to value.

        Warns
        -----
        SqlearnWarning
            If the total variance is 0, as scikit-learn's PCA warns of the
            division by it.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.decompose.pca().learned({"a": {"variance": 1.0}}) is None
        True
        """
        variances = [cast("float", v["variance"]) for v in values.values()]
        if variances and sum(variances) == 0:
            text = (
                "sq.decompose.pca: every column it decomposes is constant, so "
                "each explained variance ratio is NaN. Why: each ratio is a "
                "component's variance over the total variance, and the total "
                "is 0, as scikit-learn's PCA warns of the division by zero. "
                "Fix: drop constant columns first with sq.select.variance(), "
                "or choose columns that vary with cols=."
            )
            warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)

    def row_values(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
    ) -> Mapping[str, Expression]:
        """Centre each value once per row, refusing a missing or infinite one.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The input columns, by name, in input order.
        learned : mapping of str to Learned
            The values learned for each column: its ``mean`` is read.

        Returns
        -------
        mapping of str to duckdb.Expression
            Each column, under its own name: ``x::DOUBLE - mean``, or an
            error raised when the row is fetched if the value is missing
            (NULL or NaN) or infinite.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> xs = {"a": duckdb.ColumnExpression("a")}
        >>> list(
        ...     sq.decompose.pca().row_values(xs, {"a": Learned.values({"mean": 1.0})})
        ... )
        ['a']
        """
        centred: dict[str, Expression] = {}
        for name, x in xs.items():
            v = x.cast(DOUBLE)
            mean = const(float(cast("float", learned[name].raw("mean"))))
            centred[name] = (
                duckdb.CaseExpression(is_missing(x), _refusal(name, *_MISSING))
                .when(duckdb.FunctionExpression("isinf", v), _refusal(name, *_INFINITE))
                .otherwise(v - mean)
            )
        return centred

    def apply_row(
        self,
        xs: Mapping[str, Expression],
        learned: Mapping[str, Learned],
        values: Mapping[str, Expression],
    ) -> Mapping[str, Expression]:
        """Project the centred row on each kept component.

        Parameters
        ----------
        xs : mapping of str to duckdb.Expression
            The input columns, by name, in input order.
        learned : mapping of str to Learned
            The values learned for each column.
        values : mapping of str to duckdb.Expression
            The reference to each centred value (`row_values`); when it is
            empty, the centred values are written into each output.

        Returns
        -------
        mapping of str to duckdb.Expression
            ``pca0`` to ``pca{k-1}``, k being `n_components_`: each the sum
            of every centred value times its weight in that component,
            divided by the component's deviation (floored at the machine
            epsilon, as scikit-learn's) when `whiten`. The weights and means
            are constants in the SQL.

        Raises
        ------
        StepError
            If `n_components` is a whole number above the smaller of the rows
            and the columns, values found in the store included.

        Examples
        --------
        >>> import duckdb
        >>> import sqlearn as sq
        >>> from sqlearn._step import Learned
        >>> xs = {c: duckdb.ColumnExpression(c) for c in "ab"}
        >>> learned = {
        ...     "a": Learned.values(
        ...         {"mean": 1.0, "count": 3, "weights": [1.0, 0.0], "variance": 4.0}
        ...     ),
        ...     "b": Learned.values(
        ...         {"mean": 2.0, "count": 3, "weights": [0.0, 1.0], "variance": 1.0}
        ...     ),
        ... }
        >>> list(sq.decompose.pca(n_components=1).apply_row(xs, learned, {}))
        ['pca0']
        """
        columns = list(xs)
        outputs: dict[str, Expression] = {}
        if not columns:
            return outputs
        rows = cast("int", learned[columns[0]].raw("count"))
        variances = [cast("float", learned[c].raw("variance")) for c in columns]
        kept = _kept_components(self.n_components, rows, variances)
        centred = values or self.row_values(xs, learned)
        weights = {c: cast("list[float]", learned[c].raw("weights")) for c in columns}
        for k in range(kept):
            terms = [centred[c] * const(float(weights[c][k])) for c in columns]
            total = duckdb.FunctionExpression(
                "list_sum", duckdb.FunctionExpression("list_value", *terms)
            )
            if self.whiten:
                # As scikit-learn: the deviation, floored at the machine epsilon.
                total = total / const(max(math.sqrt(variances[k]), EPS))
            outputs[f"pca{k}"] = total
        return outputs

    def _whole(self) -> tuple[list[dict[str, object]], int, list[float]]:
        """Return each column's learned values, the rows and every variance.

        An AttributeError before learning falls through to `Step.__getattr__`,
        which says to learn first.
        """
        learned = cast(
            "dict[str, dict[str, object]] | None", self.__dict__.get("_learned")
        )
        if learned is None:
            raise AttributeError("_learned")
        values = list(learned.values())
        rows = cast("int", values[0]["count"]) if values else 0
        variances = [cast("float", v["variance"]) for v in values]
        return values, rows, variances

    def _kept(self) -> int:
        _, rows, variances = self._whole()
        return _kept_components(self.n_components, rows, variances)

    @property
    def n_components_(self) -> int:
        """The number of components kept, as scikit-learn's ``n_components_``.

        Returns
        -------
        int
            From `n_components`: the smaller of the rows and the columns for
            None, itself for a whole number, found from the ratios for a
            fraction.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 4.0, 6.5]})
        >>> sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"].n_components_
        2
        """
        return self._kept()

    @property
    def components_(self) -> list[list[float]]:
        """The kept components, largest first, as scikit-learn's ``components_``.

        Returns
        -------
        list of list of float
            `n_components_` lists, each one weight per input column.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> pca = sq.Pipeline([sq.decompose.pca(n_components=1)]).learn(data)["pca"]
        >>> [round(w, 4) for w in pca.components_[0]]
        [0.7071, -0.7071]
        """
        values, _, _ = self._whole()
        weights = [cast("list[float]", v["weights"]) for v in values]
        return [[w[k] for w in weights] for k in range(self._kept())]

    @property
    def explained_variance_(self) -> list[float]:
        """Each kept component's variance, as scikit-learn's ``explained_variance_``.

        Returns
        -------
        list of float
            The eigenvalues of the covariance, largest first, `n_components_`
            of them.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"].explained_variance_
        [2.0, 0.0]
        """
        _, _, variances = self._whole()
        return variances[: self._kept()]

    @property
    def explained_variance_ratio_(self) -> list[float]:
        """Each kept component's share of the total variance.

        Returns
        -------
        list of float
            Its variance over the sum of every component's, `n_components_`
            of them, as scikit-learn's ``explained_variance_ratio_``.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> pca = sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"]
        >>> pca.explained_variance_ratio_
        [1.0, 0.0]
        """
        _, _, variances = self._whole()
        return [float(r) for r in _ratios(variances)[: self._kept()]]

    @property
    def singular_values_(self) -> list[float]:
        """Each kept component's singular value, as scikit-learn's.

        Returns
        -------
        list of float
            ``sqrt(variance * (rows - 1))``, `n_components_` of them.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"].singular_values_
        [2.0, 0.0]
        """
        _, rows, variances = self._whole()
        kept = variances[: self._kept()]
        return [math.sqrt(v * (rows - 1)) for v in kept]

    @property
    def mean_(self) -> list[float]:
        """Each input column's mean, as scikit-learn's ``mean_``.

        Returns
        -------
        list of float
            One per input column, in input order.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"].mean_
        [2.0, 2.0]
        """
        values, _, _ = self._whole()
        return [cast("float", v["mean"]) for v in values]

    @property
    def n_samples_(self) -> int:
        """The rows learned from, as scikit-learn's ``n_samples_``.

        Returns
        -------
        int
            The row count.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        >>> sq.Pipeline([sq.decompose.pca()]).learn(data)["pca"].n_samples_
        3
        """
        _, rows, _ = self._whole()
        return rows

    @property
    def noise_variance_(self) -> float:
        """The noise variance of probabilistic PCA, as scikit-learn's.

        Returns
        -------
        float
            The mean variance of the components not kept when fewer are
            kept than the smaller of the rows and the columns, else 0.

        Examples
        --------
        >>> import pandas as pd
        >>> import sqlearn as sq
        >>> data = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 2.0]})
        >>> pca = sq.Pipeline([sq.decompose.pca(n_components=1)]).learn(data)["pca"]
        >>> round(pca.noise_variance_, 4)
        0.0657
        """
        _, rows, variances = self._whole()
        kept = self._kept()
        if kept < min(len(variances), rows):
            return float(np.mean(np.asarray(variances[kept:], dtype=np.float64)))
        return 0.0

"""Generated datasets: rows built in SQL from a seed, any number of them.

Each function returns a relation over ``range(rows)``: creating it reads and
writes nothing, and each use computes the same rows again (ADR 0045). Every
random value is a pure function of ``(seed, row, stream)``; Python draws only
a handful of constants (centres, coefficients) at rows from ``CONSTANT_ROW``.

The streams of each function, so that no two values of one row share one
(a normal of stream ``n`` draws on uniform streams ``2n`` and ``2n + 1``):

==============  =========================  ==================================
Function        Row values                 Constants (row, stream)
==============  =========================  ==================================
``blobs``       centre: uniform stream 0;  centre ``c``'s feature ``j``:
                ``x{j}``'s noise: normal   uniform at row
                stream ``j + 1``           ``CONSTANT_ROW + c``, stream ``j``
``regression``  ``x{j}``: normal stream    coefficient ``j``: uniform at row
                ``j``; the noise: normal   ``CONSTANT_ROW``, stream ``j``
                stream ``n_features``
==============  =========================  ==================================
"""

import math
from collections.abc import Sequence
from numbers import Integral, Real

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn.datasets._random import CONSTANT_ROW, random_columns, uniform

__all__ = ["blobs", "regression"]


def _whole(value: object) -> int | None:
    """Return a whole number (numpy's too) as an int; None for anything else.

    A bool is not a whole number here.
    """
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None
    return int(value)


def _finite(value: object) -> float | None:
    """Return a finite real number (numpy's too) as a float; None otherwise.

    A bool is not a number here.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _shown(value: object) -> str:
    """Return `value` as given, with its type: ``'2' (a str)``."""
    return f"{value!r} (a {type(value).__name__})"


def _as_list(value: object) -> list[object] | None:
    """Return a sequence (a list, a tuple, an array) as a list, else None.

    An array is read by its ``tolist``, so numpy's values become Python's;
    text is not a sequence of values here.
    """
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return None
    return list(value)


def _check_rows(rows: object) -> int:
    """Return `rows`, refusing anything but a whole number from 1 to ``2**63 - 1``.

    Parameters
    ----------
    rows : object
        The setting given: an int, or numpy's.

    Returns
    -------
    int
        `rows`, as a Python int.

    Raises
    ------
    SqlearnError
        If `rows` is not a whole number (a bool is not one), is below 1, or
        reaches ``2**63``, where the constants' rows begin.
    """
    count = _whole(rows)
    if count is None:
        msg = (
            f"sq.datasets got rows={_shown(rows)}. Why: the number of rows is "
            "a whole number. Fix: pass an int, rows=100, say."
        )
        raise SqlearnError(msg)
    if count < 1:
        msg = (
            f"sq.datasets got rows={rows!r}. Why: a dataset has at least one "
            "row (scikit-learn refuses no rows too). Fix: pass rows=100, say."
        )
        raise SqlearnError(msg)
    if count >= CONSTANT_ROW:
        msg = (
            f"sq.datasets got rows={rows!r}. Why: data rows are numbered below "
            "2**63, where the rows of the constants drawn from the seed begin. "
            "Fix: pass rows below 2**63 (9,223,372,036,854,775,808)."
        )
        raise SqlearnError(msg)
    return count


def _check_seed(seed: object) -> int:
    """Return `seed`, refusing anything but a whole number.

    Parameters
    ----------
    seed : object
        The setting given: an int, or numpy's.

    Returns
    -------
    int
        `seed`, as a Python int; any int is taken, modulo ``2**64``.

    Raises
    ------
    SqlearnError
        If `seed` is not a whole number (a bool is not one).
    """
    whole = _whole(seed)
    if whole is None:
        msg = (
            f"sq.datasets got seed={_shown(seed)}. Why: the seed is mixed into "
            "every random value's key and must be a whole number. Fix: pass "
            "an int, seed=0, say."
        )
        raise SqlearnError(msg)
    return whole


def _check_count(function: str, name: str, value: object, least: int) -> int:
    """Return `value` as an int, refusing all but a whole number >= `least`."""
    count = _whole(value)
    if count is None:
        msg = (
            f"sq.datasets.{function} got {name}={_shown(value)}. Why: {name} "
            f"is a whole number. Fix: pass an int, at least {least}."
        )
        raise SqlearnError(msg)
    if count < least:
        msg = (
            f"sq.datasets.{function} got {name}={value!r}. Why: {name} is at "
            f"least {least}. Fix: pass {name}={max(least, 2)}, say."
        )
        raise SqlearnError(msg)
    return count


def _check_number(function: str, name: str, value: object, *, least: float) -> float:
    """Return `value` as a float, refusing all but a finite number >= `least`."""
    number = _finite(value)
    if number is None:
        msg = (
            f"sq.datasets.{function} got {name}={_shown(value)}. Why: {name} "
            "is a finite number. Fix: pass an int or a float, 1.0, say."
        )
        raise SqlearnError(msg)
    if number < least:
        msg = (
            f"sq.datasets.{function} got {name}={value!r}. Why: {name} is at "
            f"least {least}. Fix: pass {name}=1.0, say."
        )
        raise SqlearnError(msg)
    return number


def _double(value: float) -> str:
    """Return `value` as a SQL DOUBLE literal that reads back bit for bit."""
    return f"'{value!r}'::DOUBLE"


def _relation(sql: str) -> duckdb.DuckDBPyRelation:
    """Return `sql` as a relation on sqlearn's connection, computed on use."""
    return connection().sql(sql)


def _blob_centres(
    centers: object, n_features: int, box: tuple[float, float], seed: int
) -> list[list[float]]:
    """Return the centres: the points given, or a count drawn in `box`."""
    if _whole(centers) is not None:
        count = _check_count("blobs", "centers", centers, 1)
        low, high = box
        return [
            [
                low + (high - low) * uniform(seed, CONSTANT_ROW + c, j)
                for j in range(n_features)
            ]
            for c in range(count)
        ]
    points: list[list[float]] = []
    for given in _as_list(centers) or []:
        point = _as_list(given)
        numbers = [_finite(v) for v in point or []]
        if point is None or None in numbers:
            break
        points.append([v for v in numbers if v is not None])
    else:
        if points and points[0] and len({len(p) for p in points}) == 1:
            return points
    msg = (
        f"sq.datasets.blobs got centers={centers!r}. Why: centers is a count "
        "of at least 1, or a list of points, each a list of finite numbers of "
        "one length. Fix: pass centers=3 or centers=[[0, 0], [5, 5]]."
    )
    raise SqlearnError(msg)


def _blob_spreads(cluster_std: object, count: int) -> list[float]:
    """Return one spread per centre, refusing a negative or misplaced one."""
    spreads = _as_list(cluster_std)
    if spreads is not None:
        if len(spreads) != count:
            msg = (
                f"sq.datasets.blobs got cluster_std={cluster_std!r}. Why: a "
                f"list of spreads has one per centre, {count} here. Fix: pass "
                f"{count} numbers, or one number for all."
            )
            raise SqlearnError(msg)
        return [_check_number("blobs", "cluster_std", s, least=0.0) for s in spreads]
    return [_check_number("blobs", "cluster_std", cluster_std, least=0.0)] * count


def _check_box(center_box: object) -> tuple[float, float]:
    """Return `center_box` as two finite floats, low <= high."""
    box = [_finite(v) for v in _as_list(center_box) or []]
    low, high = box if len(box) == 2 else (None, None)
    if low is None or high is None or low > high:
        msg = (
            f"sq.datasets.blobs got center_box={center_box!r}. Why: the box "
            "is two finite numbers, low then high, the range centres are "
            "drawn from. Fix: pass center_box=(-10.0, 10.0)."
        )
        raise SqlearnError(msg)
    return low, high


def blobs(
    rows: int = 100,
    n_features: int = 2,
    centers: int | Sequence[Sequence[float]] = 3,
    cluster_std: float | Sequence[float] = 1.0,
    center_box: tuple[float, float] = (-10.0, 10.0),
    seed: int = 0,
) -> duckdb.DuckDBPyRelation:
    """Return isotropic Gaussian blobs round a few centres, as ``make_blobs``.

    Each row picks its centre uniformly at random, so the counts are equal
    only in expectation (scikit-learn deals equal counts); its features are
    the centre plus normal noise of the centre's spread. The rows are built
    in SQL on use, the same ones for the same seed.

    Parameters
    ----------
    rows : int, default 100
        The number of rows, at least 1.
    n_features : int, default 2
        The number of features, at least 1. Centres given as points set it
        instead, as in scikit-learn.
    centers : int or sequence of sequences of float, default 3
        The number of centres, drawn uniformly in `center_box`, or the
        centres themselves.
    cluster_std : float or sequence of float, default 1.0
        The standard deviation round every centre, or one per centre; at
        least 0.
    center_box : tuple of float, default (-10.0, 10.0)
        The range, low then high, each coordinate of a drawn centre is
        uniform in.
    seed : int, default 0
        The seed of every random value; any int.

    Returns
    -------
    duckdb.DuckDBPyRelation
        Columns ``x0``, ``x1``, ... (``DOUBLE``), then ``target``
        (``BIGINT``), the centre's number from 0; on sqlearn's connection.

    Raises
    ------
    SqlearnError
        If a setting is not of the kind above.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.blobs(rows=1_000, centers=[[0, 0], [5, 5]], seed=0)
    >>> rel.columns
    ['x0', 'x1', 'target']
    >>> rel.project("target").distinct().order("target").fetchall()
    [(0,), (1,)]
    """
    rows = _check_rows(rows)
    seed = _check_seed(seed)
    if _whole(centers) is not None:
        n_features = _check_count("blobs", "n_features", n_features, 1)
    box = _check_box(center_box)
    points = _blob_centres(centers, n_features, box, seed)
    n_features = len(points[0])
    spreads = _blob_spreads(cluster_std, len(points))
    count = len(points)
    noise = {f"_z{j}": j + 1 for j in range(n_features)}
    source = random_columns(seed, rows, {"_c": 0}, noise)
    target = f"least(floor(_c * {count})::BIGINT, {count - 1})"
    spread = f"[{', '.join(_double(s) for s in spreads)}][target + 1]"
    features = []
    for j in range(n_features):
        centre = f"[{', '.join(_double(p[j]) for p in points)}][target + 1]"
        features.append(f"{centre} + {spread} * _z{j} AS x{j}")
    return _relation(
        f"SELECT {', '.join(features)}, target "
        f"FROM (SELECT *, {target} AS target FROM ({source}))"
    )


def regression(
    rows: int = 100,
    n_features: int = 100,
    n_informative: int = 10,
    bias: float = 0.0,
    noise: float = 0.0,
    seed: int = 0,
) -> duckdb.DuckDBPyRelation:
    """Return a linear regression problem, as ``make_regression``.

    The features are standard normal; the first `n_informative`
    coefficients are uniform in ``[0, 100)``, the rest 0, and
    ``target = x @ coef + bias + noise * N(0, 1)``. Without scikit-learn's
    rank and tail settings. The rows are built in SQL on use, the same ones
    for the same seed.

    Parameters
    ----------
    rows : int, default 100
        The number of rows, at least 1.
    n_features : int, default 100
        The number of features, at least 1.
    n_informative : int, default 10
        The number of features the target depends on, from 0 to
        `n_features`; they are the first ones.
    bias : float, default 0.0
        The intercept, a finite number.
    noise : float, default 0.0
        The standard deviation of the normal noise added to the target, at
        least 0.
    seed : int, default 0
        The seed of every random value; any int.

    Returns
    -------
    duckdb.DuckDBPyRelation
        Columns ``x0``, ``x1``, ... and ``target``, all ``DOUBLE``; on
        sqlearn's connection.

    Raises
    ------
    SqlearnError
        If a setting is not of the kind above, or `n_informative` exceeds
        `n_features`.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.regression(rows=10, n_features=3, n_informative=1)
    >>> rel.columns
    ['x0', 'x1', 'x2', 'target']
    """
    rows = _check_rows(rows)
    seed = _check_seed(seed)
    n_features = _check_count("regression", "n_features", n_features, 1)
    n_informative = _check_count("regression", "n_informative", n_informative, 0)
    if n_informative > n_features:
        msg = (
            f"sq.datasets.regression got n_informative={n_informative} with "
            f"n_features={n_features}. Why: the informative features are "
            "some of the features. Fix: pass n_informative at most n_features."
        )
        raise SqlearnError(msg)
    bias = _check_number("regression", "bias", bias, least=-math.inf)
    noise = _check_number("regression", "noise", noise, least=0.0)
    coef = [100.0 * uniform(seed, CONSTANT_ROW, j) for j in range(n_informative)]
    normals = {f"x{j}": j for j in range(n_features)}
    if noise:
        normals["_noise"] = n_features
    source = random_columns(seed, rows, {}, normals)
    terms = [f"{_double(c)} * x{j}" for j, c in enumerate(coef)]
    terms.append(_double(bias))
    if noise:
        terms.append(f"{_double(noise)} * _noise")
    features = ", ".join(f"x{j}" for j in range(n_features))
    return _relation(
        f"SELECT {features}, {' + '.join(terms)} AS target FROM ({source})"
    )

"""Generated datasets: rows built in SQL from a seed, any number of them.

Each function returns a relation over the row numbers ``0`` to ``rows - 1``,
from work tickets or, with ``parallel=False``, from ``range(rows)``: each use
computes the same rows again (ADR 0045). Every
random value is a pure function of ``(seed, row, stream)``; Python draws only
a handful of constants (centres, coefficients, matrices) at rows from
``CONSTANT_ROW``.

The streams of each function, so that no two values of one row share one
(a normal of stream ``n`` draws on uniform streams ``2n`` and ``2n + 1``):

======================  =========================  ==========================
Function                Row values                 Constants (row, stream)
======================  =========================  ==========================
``blobs``               centre: uniform stream     centre ``c``'s feature
                        0; ``x{j}``'s noise:       ``j``: uniform at row
                        normal stream ``j + 1``    ``CONSTANT_ROW + c``,
                                                   stream ``j``
``regression``          ``x{j}``: normal stream    coefficient ``j``: uniform
                        ``j``; the noise: normal   at row ``CONSTANT_ROW``,
                        stream ``n_features``      stream ``j``
``classification``      informative ``i``:         cluster ``k``'s matrix
                        normal stream ``i``;       entry ``(i, j)``: uniform
                        noise feature ``m``:       at row ``CONSTANT_ROW +
                        normal stream              k``, stream ``i * d + j``;
                        ``d + m``; with ``N``      the vertices: Floyd's step
                        normals in all, the        ``s`` keys at row
                        cluster: uniform stream    ``CONSTANT_ROW + s``,
                        ``2N``, the flip: uniform  streams from ``2**63``;
                        ``2N + 1``, the new        redundant ``r``'s weight
                        label: uniform ``2N + 2``  of ``i``: uniform at row
                                                   ``2**64 - 1``, stream
                                                   ``i * n_redundant + r``
``customers``           age, income, the target's  none
                        noise: normal streams 0, 1,
                        2; city, plan: uniform
                        streams 6, 7; the gap in
                        age, in income: uniform
                        streams 8, 9
======================  =========================  ==========================

In ``classification``, ``d`` is ``n_informative``.
"""

import math
import warnings
from collections.abc import Sequence
from numbers import Integral, Real
from pathlib import Path

import duckdb

from sqlearn._config import connection
from sqlearn._errors import SqlearnError, SqlearnWarning
from sqlearn.datasets._random import CONSTANT_ROW, MASK, key, random_columns, uniform
from sqlearn.datasets._tickets import row_source

_PACKAGE = (str(Path(__file__).parents[1]),)

__all__ = ["blobs", "classification", "customers", "regression"]


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


def _check_ordered(function: str, ordered: object) -> bool:
    """Return `ordered`, refusing anything but a bool (numpy's too, by name)."""
    if type(ordered).__name__ not in ("bool", "bool_"):
        msg = (
            f"sq.datasets.{function} got ordered={_shown(ordered)}. Why: "
            "ordered is True or False. Fix: pass ordered=True to sort the "
            "rows by their number, or leave it out."
        )
        raise SqlearnError(msg)
    return bool(ordered)


def _check_parallel(function: str, parallel: object) -> bool:
    """Return `parallel`, refusing anything but a bool (numpy's too, by name)."""
    if type(parallel).__name__ not in ("bool", "bool_"):
        msg = (
            f"sq.datasets.{function} got parallel={_shown(parallel)}. Why: "
            "parallel is True or False. Fix: pass parallel=False to number "
            "the rows with range on one thread, or leave it out."
        )
        raise SqlearnError(msg)
    return bool(parallel)


def _relation(sql: str, ordered: bool) -> duckdb.DuckDBPyRelation:
    """Return `sql` as a relation on sqlearn's connection, computed on use.

    `sql` has the row number `i` as its first column; the relation drops it,
    and sorts by it first when `ordered`.
    """
    sort = " ORDER BY i" if ordered else ""
    return connection().sql(f"SELECT * EXCLUDE (i) FROM ({sql}){sort}")


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
    ordered: bool = False,
    parallel: bool = True,
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
    ordered : bool, default False
        Whether the rows come in row order whatever DuckDB's settings. By
        default they do only while ``preserve_insertion_order`` is on. True
        sorts the relation by the row number: it costs a sort, and the
        relation is no longer lazy (it reads every row to sort them).
    parallel : bool, default True
        Whether the rows are numbered from work tickets, so that DuckDB runs
        the work on every thread it is allowed, not one. The rows are the
        same either way. Tickets are kept in an in-memory database,
        ``meta_sqlearn``, and a large export may overflow them to DuckDB's
        temporary folder. False numbers the rows with ``range`` instead: one
        thread, no temporary disk for an ordered export, and SQL that stays
        valid without ``meta_sqlearn``, as a saved view needs or text run on
        another connection.

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
    ordered = _check_ordered("blobs", ordered)
    parallel = _check_parallel("blobs", parallel)
    if _whole(centers) is not None:
        n_features = _check_count("blobs", "n_features", n_features, 1)
    box = _check_box(center_box)
    points = _blob_centres(centers, n_features, box, seed)
    n_features = len(points[0])
    spreads = _blob_spreads(cluster_std, len(points))
    count = len(points)
    noise = {f"_z{j}": j + 1 for j in range(n_features)}
    source = random_columns(seed, rows, {"_c": 0}, noise, row_source(rows, parallel))
    target = f"least(floor(_c * {count})::BIGINT, {count - 1})"
    spread = f"[{', '.join(_double(s) for s in spreads)}][target + 1]"
    features = []
    for j in range(n_features):
        centre = f"[{', '.join(_double(p[j]) for p in points)}][target + 1]"
        features.append(f"{centre} + {spread} * _z{j} AS x{j}")
    return _relation(
        f"SELECT i, {', '.join(features)}, target "
        f"FROM (SELECT *, {target} AS target FROM ({source}))",
        ordered,
    )


def regression(
    rows: int = 100,
    n_features: int = 100,
    n_informative: int | None = None,
    bias: float = 0.0,
    noise: float = 0.0,
    seed: int = 0,
    ordered: bool = False,
    parallel: bool = True,
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
    n_informative : int, optional
        The number of features the target depends on, from 0 to
        `n_features`; they are the first ones. The default, None, is 10 or
        `n_features` when that is fewer. A larger number is clipped to
        `n_features`, with a warning.
    bias : float, default 0.0
        The intercept, a finite number.
    noise : float, default 0.0
        The standard deviation of the normal noise added to the target, at
        least 0.
    seed : int, default 0
        The seed of every random value; any int.
    ordered : bool, default False
        Whether the rows come in row order whatever DuckDB's settings. By
        default they do only while ``preserve_insertion_order`` is on. True
        sorts the relation by the row number: it costs a sort, and the
        relation is no longer lazy (it reads every row to sort them).
    parallel : bool, default True
        Whether the rows are numbered from work tickets, so that DuckDB runs
        the work on every thread it is allowed, not one. The rows are the
        same either way. Tickets are kept in an in-memory database,
        ``meta_sqlearn``, and a large export may overflow them to DuckDB's
        temporary folder. False numbers the rows with ``range`` instead: one
        thread, no temporary disk for an ordered export, and SQL that stays
        valid without ``meta_sqlearn``, as a saved view needs or text run on
        another connection.

    Returns
    -------
    duckdb.DuckDBPyRelation
        Columns ``x0``, ``x1``, ... and ``target``, all ``DOUBLE``; on
        sqlearn's connection.

    Raises
    ------
    SqlearnError
        If a setting is not of the kind above.

    Warns
    -----
    SqlearnWarning
        If `n_informative` exceeds `n_features`; it is clipped to it.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.regression(rows=10, n_features=3, n_informative=1)
    >>> rel.columns
    ['x0', 'x1', 'x2', 'target']
    """
    rows = _check_rows(rows)
    seed = _check_seed(seed)
    ordered = _check_ordered("regression", ordered)
    parallel = _check_parallel("regression", parallel)
    n_features = _check_count("regression", "n_features", n_features, 1)
    if n_informative is None:
        n_informative = min(10, n_features)
    n_informative = _check_count("regression", "n_informative", n_informative, 0)
    if n_informative > n_features:
        text = (
            f"sq.datasets.regression got n_informative={n_informative} above "
            f"n_features={n_features}; using {n_features}. Why: the "
            "informative features are some of the features. Fix: pass "
            f"n_informative at most {n_features}, or more features."
        )
        warnings.warn(text, SqlearnWarning, skip_file_prefixes=_PACKAGE)
        n_informative = n_features
    bias = _check_number("regression", "bias", bias, least=-math.inf)
    noise = _check_number("regression", "noise", noise, least=0.0)
    coef = [100.0 * uniform(seed, CONSTANT_ROW, j) for j in range(n_informative)]
    normals = {f"x{j}": j for j in range(n_features)}
    if noise:
        normals["_noise"] = n_features
    source = random_columns(seed, rows, {}, normals, row_source(rows, parallel))
    terms = [f"{_double(c)} * x{j}" for j, c in enumerate(coef)]
    terms.append(_double(bias))
    if noise:
        terms.append(f"{_double(noise)} * _noise")
    features = ", ".join(f"x{j}" for j in range(n_features))
    return _relation(
        f"SELECT i, {features}, {' + '.join(terms)} AS target FROM ({source})",
        ordered,
    )


def _below(seed: int, row: int, bound: int) -> int:
    """Return a whole number uniform in ``[0, bound)``, drawn at `row`.

    Enough keys (streams from ``2**63``) are joined for 64 bits beyond
    `bound`'s, and the product with `bound` is shifted down: the bias is below
    ``2**-64``, for a bound of any size.
    """
    words = (bound.bit_length() + 63) // 64 + 1
    joined = 0
    for t in range(words):
        joined = (joined << 64) | key(seed, row, 2**63 + t)
    return (joined * bound) >> (64 * words)


def _vertices(count: int, dimensions: int, seed: int) -> list[int]:
    """Return `count` distinct vertices of the `dimensions`-cube, as bit masks.

    Floyd's sampling without replacement from ``2**dimensions``: one draw per
    vertex, at row ``CONSTANT_ROW + step``, however many dimensions there are.
    """
    size = 2**dimensions
    chosen: list[int] = []
    seen: set[int] = set()
    for step, top in enumerate(range(size - count, size)):
        drawn = _below(seed, CONSTANT_ROW + step, top + 1)
        pick = top if drawn in seen else drawn
        seen.add(pick)
        chosen.append(pick)
    return chosen


def _class_weights(weights: object, n_classes: int) -> list[float]:
    """Return each class's share, summing to 1, from `weights` as given.

    None gives equal shares. ``n_classes - 1`` weights leave the last class
    the rest of 1; ``n_classes`` weights summing below 1 leave the rest of 1
    shared equally by the classes, as scikit-learn deals the rows they leave
    round-robin over every cluster.
    """
    if weights is None:
        return [1.0 / n_classes] * n_classes
    given = _as_list(weights)
    numbers = [_finite(w) for w in given or []]
    shares = [w for w in numbers if w is not None and w >= 0]
    if given is None or len(shares) != len(numbers):
        msg = (
            f"sq.datasets.classification got weights={weights!r}. Why: weights "
            "is a list of finite numbers of at least 0, one per class. Fix: "
            "pass weights=[0.9, 0.1], say, or None for equal classes."
        )
        raise SqlearnError(msg)
    if len(shares) not in (n_classes, n_classes - 1):
        msg = (
            f"sq.datasets.classification got {len(shares)} weights for "
            f"n_classes={n_classes}. Why: weights has one per class, or one "
            "fewer and the last class takes the rest of 1. Fix: pass "
            f"{n_classes} or {n_classes - 1} weights."
        )
        raise SqlearnError(msg)
    total = math.fsum(shares)
    # Decimal weights summing to 1 can round a little above it.
    if total > 1 + 1e-9:
        msg = (
            f"sq.datasets.classification got weights={weights!r}, summing to "
            f"{total!r}. Why: weights are the classes' shares of the rows, so "
            "they sum to at most 1. Fix: pass weights summing to 1."
        )
        raise SqlearnError(msg)
    if len(shares) == n_classes - 1:
        shares.append(max(0.0, 1.0 - total))
        total = math.fsum(shares)
    # scikit-learn deals the rows the weights leave round-robin over every
    # cluster, so each class gets an equal part of the rest of 1.
    rest = max(0.0, 1.0 - total) / n_classes
    return [w + rest for w in shares]


def _check_classes(
    n_features: object,
    n_informative: object,
    n_redundant: object,
    n_classes: object,
    n_clusters_per_class: object,
) -> tuple[int, int, int, int, int]:
    """Return classification's counts, refusing those that do not fit."""
    n_features = _check_count("classification", "n_features", n_features, 1)
    n_informative = _check_count("classification", "n_informative", n_informative, 1)
    n_redundant = _check_count("classification", "n_redundant", n_redundant, 0)
    n_classes = _check_count("classification", "n_classes", n_classes, 1)
    n_clusters_per_class = _check_count(
        "classification", "n_clusters_per_class", n_clusters_per_class, 1
    )
    if n_informative + n_redundant > n_features:
        msg = (
            f"sq.datasets.classification got n_informative={n_informative} "
            f"and n_redundant={n_redundant} with n_features={n_features}. "
            "Why: the informative and redundant features are some of the "
            "features. Fix: pass n_informative + n_redundant at most n_features."
        )
        raise SqlearnError(msg)
    clusters = n_classes * n_clusters_per_class
    if (clusters - 1) >> n_informative:
        msg = (
            f"sq.datasets.classification got n_classes={n_classes} and "
            f"n_clusters_per_class={n_clusters_per_class} with "
            f"n_informative={n_informative}. Why: each of the {clusters} "
            "clusters sits at its own vertex of the informative features' "
            "hypercube, which has 2**n_informative. Fix: raise n_informative "
            "or lower n_classes or n_clusters_per_class."
        )
        raise SqlearnError(msg)
    return n_features, n_informative, n_redundant, n_classes, n_clusters_per_class


def _check_share(name: str, value: object) -> float:
    """Return `value` as a float, refusing all but a number in ``[0, 1]``."""
    share = _check_number("classification", name, value, least=0.0)
    if share > 1:
        msg = (
            f"sq.datasets.classification got {name}={value!r}. Why: {name} is "
            "a share of the rows, from 0 to 1. Fix: pass a number from 0 to 1."
        )
        raise SqlearnError(msg)
    return share


def _check_positive(name: str, value: object) -> float:
    """Return `value` as a float, refusing all but a finite number above 0."""
    number = _check_number("classification", name, value, least=-math.inf)
    if number <= 0:
        msg = (
            f"sq.datasets.classification got {name}={value!r}. Why: {name} is "
            "above 0. Fix: pass 1.0, say."
        )
        raise SqlearnError(msg)
    return number


def _picked_cluster(shares: list[float]) -> str:
    """Return the SQL of a row's cluster: uniform ``_u`` against the shares.

    A cluster of share 0 is never picked; the last one with a share takes
    the uniforms past the others, so rounding never drops a row.
    """
    held = [k for k, share in enumerate(shares) if share > 0]
    if len(held) == 1:
        return f"{held[0]}::BIGINT"
    branches = []
    running = 0.0
    for k in held[:-1]:
        running += shares[k]
        branches.append(f"WHEN _u < {_double(running)} THEN {k}")
    return f"(CASE {' '.join(branches)} ELSE {held[-1]} END)::BIGINT"


def _by_cluster(values: list[float]) -> str:
    """Return the SQL of the value of the row's cluster ``_k`` in `values`."""
    return f"[{', '.join(_double(v) for v in values)}][_k + 1]"


def classification(
    rows: int = 100,
    n_features: int = 20,
    n_informative: int = 2,
    n_redundant: int = 2,
    n_classes: int = 2,
    n_clusters_per_class: int = 2,
    weights: Sequence[float] | None = None,
    flip_y: float = 0.01,
    class_sep: float = 1.0,
    seed: int = 0,
    ordered: bool = False,
    parallel: bool = True,
) -> duckdb.DuckDBPyRelation:
    """Return a random n-class classification problem, as ``make_classification``.

    Each class has `n_clusters_per_class` clusters, each at its own vertex of
    a hypercube of side ``2 * class_sep`` in the informative features. Each
    row picks its cluster by the class weights (a class's weight shared
    equally by its clusters), so the counts follow the weights only in
    expectation (scikit-learn deals them). Its informative features are
    standard normal times the cluster's random matrix (entries uniform in
    ``[-1, 1)``) plus its vertex; the redundant features are random
    combinations of the informative ones (weights uniform in ``[-1, 1)``),
    the rest standard normal noise. With probability `flip_y` the label is
    replaced by a class drawn uniformly. Without scikit-learn's
    ``n_repeated``, ``hypercube=False``, ``shift``, ``scale`` and
    ``shuffle``. The rows are built in SQL on use, the same ones for the
    same seed.

    Parameters
    ----------
    rows : int, default 100
        The number of rows, at least 1.
    n_features : int, default 20
        The number of features, at least ``n_informative + n_redundant``.
    n_informative : int, default 2
        The number of informative features, at least 1; the hypercube has
        ``2**n_informative`` vertices, at least one per cluster.
    n_redundant : int, default 2
        The number of features that are combinations of the informative
        ones, at least 0.
    n_classes : int, default 2
        The number of classes, at least 1.
    n_clusters_per_class : int, default 2
        The number of clusters of each class, at least 1.
    weights : sequence of float, optional
        Each class's share of the rows, at least 0 each and at most 1 in
        all; or one fewer than `n_classes`, the last class taking the rest of
        1. Of weights summing below 1, the rest of 1 is shared equally by the
        classes, as scikit-learn deals the rows they leave round-robin
        (``[0.5, 0.3]`` gives 0.6 and 0.4). None gives equal classes.
    flip_y : float, default 0.01
        The share of rows whose label is redrawn uniformly from the classes,
        from 0 to 1 (a redrawn label may land on its own class).
    class_sep : float, default 1.0
        Half the hypercube's side, above 0: larger spreads the clusters
        apart.
    seed : int, default 0
        The seed of every random value; any int.
    ordered : bool, default False
        Whether the rows come in row order whatever DuckDB's settings. By
        default they do only while ``preserve_insertion_order`` is on. True
        sorts the relation by the row number: it costs a sort, and the
        relation is no longer lazy (it reads every row to sort them).
    parallel : bool, default True
        Whether the rows are numbered from work tickets, so that DuckDB runs
        the work on every thread it is allowed, not one. The rows are the
        same either way. Tickets are kept in an in-memory database,
        ``meta_sqlearn``, and a large export may overflow them to DuckDB's
        temporary folder. False numbers the rows with ``range`` instead: one
        thread, no temporary disk for an ordered export, and SQL that stays
        valid without ``meta_sqlearn``, as a saved view needs or text run on
        another connection.

    Returns
    -------
    duckdb.DuckDBPyRelation
        Columns ``x0``, ``x1``, ... (``DOUBLE``: the informative features,
        then the redundant, then the noise), then ``target`` (``BIGINT``), the
        class from 0; on sqlearn's connection.

    Raises
    ------
    SqlearnError
        If a setting is not of the kind above, the informative and redundant
        features outnumber `n_features`, or the clusters outnumber the
        hypercube's vertices.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.classification(rows=10, n_features=5, seed=0)
    >>> rel.columns
    ['x0', 'x1', 'x2', 'x3', 'x4', 'target']
    """
    rows = _check_rows(rows)
    seed = _check_seed(seed)
    ordered = _check_ordered("classification", ordered)
    parallel = _check_parallel("classification", parallel)
    n_features, n_informative, n_redundant, n_classes, per_class = _check_classes(
        n_features, n_informative, n_redundant, n_classes, n_clusters_per_class
    )
    classes = _class_weights(weights, n_classes)
    flip_y = _check_share("flip_y", flip_y)
    class_sep = _check_positive("class_sep", class_sep)
    d = n_informative
    clusters = n_classes * per_class
    shares = [classes[k % n_classes] / per_class for k in range(clusters)]
    vertices = _vertices(clusters, d, seed)
    matrices = [
        [
            [2.0 * uniform(seed, CONSTANT_ROW + k, i * d + j) - 1.0 for j in range(d)]
            for i in range(d)
        ]
        for k in range(clusters)
    ]
    mixing = [
        [
            2.0 * uniform(seed, MASK, i * n_redundant + r) - 1.0
            for r in range(n_redundant)
        ]
        for i in range(d)
    ]
    n_noise = n_features - d - n_redundant
    noise = [f"x{d + n_redundant + m}" for m in range(n_noise)]
    normals = {f"_z{i}": i for i in range(d)} | {
        name: d + m for m, name in enumerate(noise)
    }
    count = len(normals)
    uniforms = {"_u": 2 * count}
    if flip_y > 0:
        uniforms |= {"_flip": 2 * count + 1, "_new": 2 * count + 2}
    source = random_columns(seed, rows, uniforms, normals, row_source(rows, parallel))
    target = f"_k % {n_classes}"
    if flip_y > 0:
        redrawn = f"least(floor(_new * {n_classes})::BIGINT, {n_classes - 1})"
        target = f"CASE WHEN _flip < {_double(flip_y)} THEN {redrawn} ELSE {target} END"
    informative = []
    for j in range(d):
        vertex = [class_sep if (v >> j) & 1 else -class_sep for v in vertices]
        terms = [_by_cluster(vertex)]
        terms += [
            f"_z{i} * {_by_cluster([m[i][j] for m in matrices])}" for i in range(d)
        ]
        informative.append(f"{' + '.join(terms)} AS x{j}")
    redundant = [
        " + ".join(f"x{i} * {_double(mixing[i][r])}" for i in range(d))
        + f" AS x{d + r}"
        for r in range(n_redundant)
    ]
    first = ", ".join(["i", *informative, *noise, f"({target})::BIGINT AS target"])
    last = ", ".join(
        ["i"] + [f"x{j}" for j in range(d)] + redundant + noise + ["target"]
    )
    return _relation(
        f"SELECT {last} FROM (SELECT {first} FROM "
        f"(SELECT *, {_picked_cluster(shares)} AS _k FROM ({source})))",
        ordered,
    )


def _picked(uniform_column: str, values: Sequence[str], shares: Sequence[float]) -> str:
    """Return the SQL of the text value `uniform_column` picks by `shares`.

    The uniform is compared with the running total of the shares; the last
    value takes whatever is left, so rounding never leaves a row without one.
    """
    branches = []
    running = 0.0
    for value, share in zip(values[:-1], shares[:-1], strict=True):
        running += share
        branches.append(f"WHEN {uniform_column} < {_double(running)} THEN '{value}'")
    return f"(CASE {' '.join(branches)} ELSE '{values[-1]}' END)"


_CITIES = ("Oslo", "Lima", "Kyoto", "Cairo")
_PLANS = ("basic", "plus", "pro")
_PLAN_SHARES = (0.5, 0.3, 0.2)


def customers(
    rows: int = 1000,
    seed: int = 0,
    ordered: bool = False,
    parallel: bool = True,
) -> duckdb.DuckDBPyRelation:
    """Return sqlearn's own table of customers: numbers and text with gaps.

    ``age`` is normal (mean 40, standard deviation 12) with a tenth of it
    missing; ``income`` is log-normal (``exp(10.5 + 0.5 * z)``) with a
    twentieth missing; ``city`` is one of Oslo, Lima, Kyoto and Cairo, evenly;
    ``plan`` is basic (0.5), plus (0.3) or pro (0.2). ``target`` is 1 for a
    customer who churned: a signal of the age, an income above its median
    ``exp(10.5)``, the basic plan, Cairo and a normal noise, past 0.4. The
    signal is computed from the values before the gaps are made. The rows
    are built in SQL on use, the same ones for the same seed.

    Parameters
    ----------
    rows : int, default 1000
        The number of rows, at least 1.
    seed : int, default 0
        The seed of every random value; any int.
    ordered : bool, default False
        Whether the rows come in row order whatever DuckDB's settings. By
        default they do only while ``preserve_insertion_order`` is on. True
        sorts the relation by the row number: it costs a sort, and the
        relation is no longer lazy (it reads every row to sort them).
    parallel : bool, default True
        Whether the rows are numbered from work tickets, so that DuckDB runs
        the work on every thread it is allowed, not one. The rows are the
        same either way. Tickets are kept in an in-memory database,
        ``meta_sqlearn``, and a large export may overflow them to DuckDB's
        temporary folder. False numbers the rows with ``range`` instead: one
        thread, no temporary disk for an ordered export, and SQL that stays
        valid without ``meta_sqlearn``, as a saved view needs or text run on
        another connection.

    Returns
    -------
    duckdb.DuckDBPyRelation
        Columns ``age`` and ``income`` (``DOUBLE``, with NULLs), ``city`` and
        ``plan`` (``VARCHAR``), and ``target`` (``BIGINT``, 0 or 1); on
        sqlearn's connection.

    Raises
    ------
    SqlearnError
        If `rows` is not a positive whole number or `seed` is not an int.

    Examples
    --------
    >>> import sqlearn as sq
    >>> rel = sq.datasets.customers(rows=10, seed=1)
    >>> rel.columns
    ['age', 'income', 'city', 'plan', 'target']
    """
    rows = _check_rows(rows)
    seed = _check_seed(seed)
    ordered = _check_ordered("customers", ordered)
    parallel = _check_parallel("customers", parallel)
    source = random_columns(
        seed,
        rows,
        {"_city": 6, "_plan": 7, "_age_gap": 8, "_income_gap": 9},
        {"_age_z": 0, "_income_z": 1, "_noise": 2},
        row_source(rows, parallel),
    )
    drawn = (
        "SELECT i, 40.0 + 12.0 * _age_z AS _age,"
        f" exp(10.5 + 0.5 * _income_z) AS _income,"
        f" {_picked('_city', _CITIES, [0.25] * 4)} AS _town,"
        f" {_picked('_plan', _PLANS, _PLAN_SHARES)} AS _tier,"
        " _noise, _age_gap, _income_gap"
        f" FROM ({source})"
    )
    signal = (
        "0.04 * (_age - 40.0)"
        " - 0.8 * (_income > exp(10.5))::DOUBLE"
        " + 0.9 * (_tier = 'basic')::DOUBLE"
        " + 0.5 * (_town = 'Cairo')::DOUBLE"
        " + _noise"
    )
    return _relation(
        f"SELECT i, CASE WHEN _age_gap < {_double(0.1)} THEN NULL ELSE _age END"
        " AS age,"
        f" CASE WHEN _income_gap < {_double(0.05)} THEN NULL ELSE _income END"
        " AS income,"
        " _town AS city, _tier AS plan,"
        f" ({signal} > {_double(0.4)})::BIGINT AS target"
        f" FROM ({drawn})",
        ordered,
    )

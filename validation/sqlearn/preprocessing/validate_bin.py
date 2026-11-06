"""Validate sq.bin: the edges against the mathematics, the bins against scikit-learn.

``uniform`` and ``quantile`` learn, through a one-step pipeline, from the
numeric datasets with ``n`` bins. Each inner edge is compared with the
canonical value (ADR 0016): ``min + i * (max - min) / n`` exactly, as a
`Fraction`, for ``uniform``; for ``quantile`` the exact
``averaged_inverted_cdf`` quantile at the share scikit-learn asks numpy for
(``i * (100 / n) / 100`` in doubles), its ranks found as numpy finds them.
Then the edges and every bin are compared value by value with scikit-learn's
``KBinsDiscretizer(encode="ordinal", subsample=None)``, given the present
values (it takes no NULL or NaN; sqlearn's missing values must stay NULL):
any difference fails.

``binarize`` learns nothing, so its cases are its outputs, value by value
against scikit-learn's ``Binarizer`` at a few thresholds.
"""

import warnings
from fractions import Fraction

import numpy as np
from sklearn.preprocessing import Binarizer, KBinsDiscretizer

import sqlearn as sq
from sqlearn.preprocessing.bin import _percent_level
from validation import _cases
from validation.sqlearn.agg.validate_aggregates import exact_quantile

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: uniform
# edges 1 ULP (the step and the sum are each rounded, as numpy's linspace);
# quantile edges 0 ULPs (a value, or halfway between two), so the floor of 1.
BOUNDS = {"uniform": 1, "quantile": 1}

FORMULAS = {
    "uniform": "uniform edge i: min + i * (max - min) / n",
    "quantile": "quantile edge i: averaged_inverted_cdf quantile at i / n",
}

N_BINS = (3, 5, 10)
"""The numbers of bins measured: 3 and 10 make shares that are not i / n."""

THRESHOLDS = (0.0, 1_000.0, 1_100.5)
"""The thresholds of binarize: below every value, at the centre, in the tail."""

COMPARED_WITH = {
    "uniform": 'scikit-learn KBinsDiscretizer(strategy="uniform", encode="ordinal")',
    "quantile": 'scikit-learn KBinsDiscretizer(strategy="quantile", encode="ordinal")',
    "binarize": "scikit-learn Binarizer",
}


def _exact_edges(method: str, n: int, values: list[float]) -> list[Fraction]:
    """Return the inner edges before any merge: none for a constant column."""
    low, high = Fraction(min(values)), Fraction(max(values))
    if low == high:
        return []
    if method == "uniform":
        return [low + i * (high - low) / n for i in range(1, n)]
    return [
        exact_quantile(values, _percent_level(i, n), "averaged_inverted_cdf")
        for i in range(1, n)
    ]


def _sqlearn(data: _cases.Dataset, method: str, n: int) -> tuple[list, list]:
    """Return sqlearn's inner edges and its bins of the data."""
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", sq.errors.SqlearnWarning)
        pipe = sq.Pipeline([sq.bin(data.column, method=method, n=n)]).learn(rel)
    bins = [row[0] for row in pipe.apply(rel).fetchall()]
    return pipe[method].edges_[data.column], bins


def _sklearn(method: str, n: int, present: np.ndarray) -> tuple[list, list]:
    """Return scikit-learn's inner edges and its bins of the present values."""
    kbins = KBinsDiscretizer(
        n_bins=n, strategy=method, encode="ordinal", subsample=None
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        kbins.fit(present[:, None])
    bins = kbins.transform(present[:, None])[:, 0]
    return kbins.bin_edges_[0][1:-1].tolist(), bins.tolist()


def _bins_misses(values: tuple, ours: list, theirs: list) -> int:
    """Count the bins that differ; a missing value must give NULL."""
    present = iter(theirs)
    misses = 0
    for v, got in zip(values, ours, strict=True):
        if _cases.is_missing(v):
            misses += got is not None
        else:
            misses += got != next(present)
    return misses


def _refused(head: dict, formula: str, run: object) -> dict:
    """Record a dataset with no rows: sqlearn must refuse it, as scikit-learn."""
    try:
        run()  # type: ignore[operator]
    except sq.errors.SqlearnError as exc:
        result, note = "pass", f"refused, as specified: {_cases.first_line(exc)}"
    else:
        result, note = "fail", "no rows to learn from, yet sqlearn learned"
    return _cases.skipped(
        reference="sqlearn",
        formula=formula,
        note=note + "; scikit-learn refuses no rows too (ValueError)",
        bound=0,
        result=result,
        **head,
    )


def _edge_cases(head: dict, method: str, n: int, ours: list, exact: list) -> list:
    """Measure each inner edge against its exact value, where none was merged."""
    if len(ours) != len(exact):
        note = f"{len(exact) - len(ours)} edges merged, as scikit-learn; see below"
        return [
            _cases.skipped(
                reference="sqlearn",
                formula=FORMULAS[method],
                note=note,
                bound=BOUNDS[method],
                **head,
            )
        ]
    return [
        _cases.case(
            reference="sqlearn",
            formula=f"{FORMULAS[method]}, i = {i}, n = {n}",
            value=value,
            exact=edge,
            bound=BOUNDS[method],
            **head,
        )
        for i, (value, edge) in enumerate(zip(ours, exact, strict=True), 1)
    ]


def bin_cases() -> list[dict]:
    """Return uniform's and quantile's cases: edges, then bins, per dataset."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        for method in ("uniform", "quantile"):
            for n in N_BINS:
                head = {
                    "step": f"bin.{method}",
                    "dataset": data.name,
                    "rows": len(data.values),
                    "type": "DOUBLE",
                }
                if not values:
                    out.append(
                        _refused(
                            head,
                            f"{method}, n = {n}",
                            lambda d=data, m=method, k=n: _sqlearn(d, m, k),
                        )
                    )
                    continue
                ours, bins = _sqlearn(data, method, n)
                exact = _exact_edges(method, n, values)
                out += _edge_cases(head, method, n, ours, exact)
                edges, theirs = _sklearn(method, n, np.array(values, dtype=float))
                compared = {**head, "compared_with": COMPARED_WITH[method]}
                out.append(
                    _cases.exact_case(
                        formula=f"{method} inner edges, n = {n}",
                        mismatches=sum(
                            a != b for a, b in zip(ours, edges, strict=False)
                        )
                        + abs(len(ours) - len(edges)),
                        cells=max(len(edges), 1),
                        note=f"{data.note}; merged edges left out on both sides",
                        **compared,
                    )
                )
                out.append(
                    _cases.exact_case(
                        formula=f"{method} bins, n = {n}",
                        mismatches=_bins_misses(data.values, bins, theirs),
                        cells=len(data.values),
                        note=f"{data.note}; every bin, missing kept NULL",
                        **compared,
                    )
                )
    return out


def binarize_cases() -> list[dict]:
    """Return binarize's cases: every output against Binarizer, per threshold."""
    out = []
    for data in _cases.numbers():
        values = _cases.present(data.values)
        rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
        for threshold in THRESHOLDS:
            step = sq.bin.binarize(data.column, threshold=threshold)
            got = [
                row[0] for row in sq.Pipeline([step]).learn(rel).apply(rel).fetchall()
            ]
            theirs = (
                Binarizer(threshold=threshold)
                .fit_transform(np.array(values, dtype=float)[:, None])[:, 0]
                .tolist()
                if values
                else []
            )
            out.append(
                _cases.exact_case(
                    step="bin.binarize",
                    formula=f"binarize: 1 where x > {threshold}, else 0",
                    dataset=data.name,
                    rows=len(data.values),
                    type="DOUBLE",
                    mismatches=_bins_misses(data.values, got, theirs),
                    cells=len(data.values),
                    compared_with=COMPARED_WITH["binarize"],
                    note=f"{data.note}; every output, missing kept NULL",
                )
            )
    return out


def cases() -> list[dict]:
    """Return sq.bin's cases: uniform, quantile and binarize."""
    return bin_cases() + binarize_cases()

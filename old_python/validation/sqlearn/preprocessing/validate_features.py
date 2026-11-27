"""Validate sq.features: terms and bases against the mathematics and scikit-learn.

``polynomial`` learns nothing. It runs on two columns made from each numeric
dataset (``a`` the values, ``b`` the same values reversed), at degrees 2 and
3, with and without ``interaction_only``. Each term is compared with the
exact product of its factors (`Fraction`): the worst distance in ULPs is the
case (ADR 0016). The names are compared with ``PolynomialFeatures``'
``get_feature_names_out`` (its space written ``*``) and every value with its
output on the rows without a missing value, exactly; a missing factor must
give NULL (NaN for NaN).

``spline`` learns the knots through a one-step pipeline. Each learned knot
is compared with its exact value: ``min + i * (max - min) / (n_knots - 1)``
for uniform knots and numpy's ``"linear"`` quantile for quantile ones, at
the levels scikit-learn asks for (the knots added on each side are exact
arithmetic on these, compared the same way). The basis is then applied to
the present values: each row's sum must be 1 (the B-splines are a partition
of unity inside the knots), measured in ULPs; each value is compared with
the exact B-spline (de Boor's recursion in `Fraction`, at sqlearn's knots
and the row's value) and with ``SplineTransformer``'s output, within an
absolute tolerance, since a basis value near 0 has no meaningful ULP
distance. A missing value is refused when fetched, as scikit-learn refuses
NaN; a dataset with no rows is refused at learn.
"""

import math
from fractions import Fraction

import duckdb
import numpy as np
from sklearn.preprocessing import PolynomialFeatures, SplineTransformer

import sqlearn as sq
from sqlearn.preprocessing.features import _rank
from validation import _cases
from validation.sqlearn.agg.validate_aggregates import exact_quantile

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: polynomial
# terms 1 ULP (a cube is rounded twice, as numpy's); uniform knots 1 ULP (the
# step and the sum are each rounded, as numpy's linspace), quantile knots
# 0 ULPs, so the floor of 1; the added knots 2 ULPs (the distance, its
# multiple and the sum or difference are each rounded, as numpy's); the sum
# of a row's basis 6 ULPs (each value carries its own rounding), so 8.
BOUNDS = {"polynomial": 1, "uniform": 1, "quantile": 1, "added": 2, "sum": 8}

TOLERANCE = 2.0**-51
"""The absolute distance a basis value may have from the exact B-spline and
from scikit-learn's, set from the first measurement: the worst was 4.4e-16
(2^-51) against both, the values written as Horner polynomials in the
distance from each interval's left knot."""

POLYNOMIALS = ((2, False), (2, True), (3, False), (3, True))
"""The (degree, interaction_only) measured."""

SPLINES = ((5, 3), (4, 2), (7, 1))
"""The (n_knots, degree) measured."""

EXACT_ROWS = 1_000
"""The rows whose basis is compared with the exact one: the exact recursion
in fractions is slow, so the large dataset is measured on its first rows."""


def _poly_columns(data: _cases.Dataset) -> dict[str, tuple]:
    """Return the two columns ``a`` and ``b`` made from a dataset."""
    return {"a": data.values, "b": tuple(reversed(data.values))}


def _exact_term(name: str, row: dict[str, float]) -> Fraction:
    """Return the exact product a term's name stands for."""
    out = Fraction(1)
    for factor in name.split("*"):
        column, _, power = factor.partition("^")
        out *= Fraction(row[column]) ** int(power or 1)
    return out


def _polynomial_cases(data: _cases.Dataset) -> list[dict]:
    """Return polynomial's cases on a dataset: terms, names and values."""
    columns = _poly_columns(data)
    rows = len(data.values)
    out = []
    for degree, interaction_only in POLYNOMIALS:
        setting = f"degree = {degree}, interaction_only = {interaction_only}"
        head = {
            "step": "features.polynomial",
            "dataset": data.name,
            "rows": rows,
            "type": "DOUBLE",
        }
        step = sq.features.polynomial(degree=degree, interaction_only=interaction_only)
        rel = _cases.sqlearn_table(columns, "DOUBLE")
        pipe = sq.Pipeline([step]).learn(rel)
        names = pipe.columns_out_
        got = pipe.apply(rel).fetchall()
        inputs = [
            dict(zip(columns, r, strict=True))
            for r in zip(*columns.values(), strict=True)
        ]
        whole = [
            (row, g)
            for row, g in zip(inputs, got, strict=True)
            if not any(_cases.is_missing(v) for v in row.values())
        ]
        if not whole:
            out.append(
                _cases.skipped(
                    reference="sqlearn",
                    formula=f"each term against its exact product, {setting}",
                    note="no row without a missing value",
                    bound=BOUNDS["polynomial"],
                    **head,
                )
            )
            continue
        worst = (0, 0.0, Fraction(0), "")
        for row, g in whole:
            for name, value in zip(names, g, strict=True):
                exact = _exact_term(name, row)
                distance = _cases.ulps(value, _cases.nearest(exact))
                if distance >= worst[0]:
                    worst = (distance, value, exact, name)
        out.append(
            _cases.case(
                reference="sqlearn",
                formula=(
                    f"each term against its exact product, {setting}; worst {worst[3]}"
                ),
                value=worst[1],
                exact=worst[2],
                bound=BOUNDS["polynomial"],
                note=f"{data.note}; the worst of {len(whole) * len(names)} values",
                **head,
            )
        )
        model = PolynomialFeatures(
            degree=degree, interaction_only=interaction_only, include_bias=False
        )
        present = np.array([[row["a"], row["b"]] for row, _ in whole])
        theirs = model.fit_transform(present)
        expected = [
            n.replace(" ", "*") for n in model.get_feature_names_out(["a", "b"])
        ]
        compared = {**head, "compared_with": "scikit-learn PolynomialFeatures"}
        out.append(
            _cases.exact_case(
                formula=f"names against get_feature_names_out, {setting}",
                mismatches=sum(a != b for a, b in zip(names, expected, strict=False))
                + abs(len(names) - len(expected)),
                cells=len(expected),
                note="the space of a product written *",
                **compared,
            )
        )
        ours = np.array([g for _, g in whole], dtype=float)
        out.append(
            _cases.exact_case(
                formula=f"every term, {setting}",
                mismatches=int((ours != theirs).sum()),
                cells=theirs.size,
                note=f"{data.note}; the rows without a missing value",
                **compared,
            )
        )
        out.append(
            _cases.exact_case(
                formula=f"a missing factor gives a missing term, {setting}",
                mismatches=_missing_terms(names, inputs, got),
                cells=len(got) * len(names),
                compared_with="NULL in, NULL out; NaN in, NaN out",
                note=data.note,
                **head,
            )
        )
    return out


def _missing_terms(names: list[str], inputs: list[dict], got: list[tuple]) -> int:
    """Count the terms that are not missing as their factors say they must be."""
    misses = 0
    for row, values in zip(inputs, got, strict=True):
        for name, value in zip(names, values, strict=True):
            factors = [f.partition("^")[0] for f in name.split("*")]
            if any(row[f] is None for f in factors):
                misses += value is not None
            elif any(_cases.is_missing(row[f]) for f in factors):
                misses += not (isinstance(value, float) and math.isnan(value))
    return misses


def _exact_base(knots: str, n: int, values: list[float]) -> list[Fraction]:
    """Return the exact learned knots, before those added on each side."""
    if knots == "uniform":
        low, high = Fraction(min(values)), Fraction(max(values))
        return [low + i * (high - low) / (n - 1) for i in range(n)]
    return [exact_quantile(values, _rank(i, n), "linear") for i in range(n)]


def _exact_extended(base: list[float], degree: int) -> list[Fraction]:
    """Return the exact knots added on each side of sqlearn's learned ones."""
    b = [Fraction(v) for v in base]
    low, high = b[1] - b[0], b[-1] - b[-2]
    below = [b[0] - (degree - i) * low for i in range(degree)]
    above = [b[-1] + (i + 1) * high for i in range(degree)]
    return [*below, *b, *above]


def _exact_basis(t: list[Fraction], k: int, x: Fraction) -> list[Fraction]:
    """Return the exact B-spline basis at `x`, on scipy's interval (de Boor)."""
    n = len(t) - k - 1
    ell = max(e for e in range(k, n) if t[e] <= x)
    h = [Fraction(1)] + [Fraction(0)] * k
    for j in range(1, k + 1):
        hh = h[:j]
        h[0] = Fraction(0)
        for m in range(1, j + 1):
            xb, xa = t[ell + m], t[ell + m - j]
            if xb == xa:
                h[m] = Fraction(0)
                continue
            w = hh[m - 1] / (xb - xa)
            h[m - 1] += w * (xb - x)
            h[m] = w * (x - xa)
    out = [Fraction(0)] * n
    for j, value in enumerate(h):
        out[ell - k + j] = value
    return out


def _spline(data: _cases.Dataset, knots: str, n: int, degree: int) -> tuple:
    """Return sqlearn's knots and its basis of the dataset's present values."""
    rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
    step = sq.features.spline(data.column, n_knots=n, degree=degree, knots=knots)
    pipe = sq.Pipeline([step]).learn(rel)
    present = _cases.present(data.values)
    applied = _cases.sqlearn_table({data.column: tuple(present)}, "DOUBLE")
    return pipe["spline"].knots_[data.column], pipe.apply(applied).fetchall(), pipe


def _refused(head: dict, formula: str, run: object, what: str, theirs: str) -> dict:
    """Record an input sqlearn must refuse, as scikit-learn refuses it."""
    try:
        run()  # type: ignore[operator]
    except (sq.errors.SqlearnError, duckdb.InvalidInputException) as exc:
        result, note = "pass", f"refused, as specified: {_cases.first_line(exc)}"
    else:
        result, note = "fail", f"{what}, yet sqlearn gave an answer"
    return _cases.skipped(
        reference="sqlearn",
        formula=formula,
        note=f"{note}; {theirs}",
        bound=0,
        result=result,
        **head,
    )


def _knot_cases(
    head: dict, setting: str, knots: str, ours: list, exact: list, bound: int
) -> dict:
    """Return the case of the worst knot against its exact value."""
    worst = max(
        range(len(ours)), key=lambda i: _cases.ulps(ours[i], _cases.nearest(exact[i]))
    )
    return _cases.case(
        reference="sqlearn",
        formula=f"{knots} knots, {setting}; worst knot {worst}",
        value=ours[worst],
        exact=exact[worst],
        bound=bound,
        note=f"the worst of {len(ours)} knots",
        **head,
    )


def _basis_cases(
    head: dict, setting: str, t: list[float], degree: int, present: list, got: list
) -> list[dict]:
    """Return the cases of the basis: the sum of each row, and the exact values."""
    exact_knots = [Fraction(v) for v in t]
    worst_sum = (0, 1.0)
    far = 0
    cells = 0
    for x, row in zip(present[:EXACT_ROWS], got[:EXACT_ROWS], strict=False):
        total = math.fsum(row)
        distance = _cases.ulps(total, 1.0)
        if distance >= worst_sum[0]:
            worst_sum = (distance, total)
        if t[degree] == t[-degree - 1]:
            exact = [Fraction(0)] * len(row)  # a constant column: zeros, as scipy
        else:
            exact = _exact_basis(exact_knots, degree, Fraction(x))
        far += sum(
            abs(Fraction(v) - e) > TOLERANCE for v, e in zip(row, exact, strict=True)
        )
        cells += len(row)
    out = []
    if t[degree] != t[-degree - 1]:
        out.append(
            _cases.case(
                reference="sqlearn",
                formula=f"sum of a row's basis, exactly 1, {setting}",
                value=worst_sum[1],
                exact=Fraction(1),
                bound=BOUNDS["sum"],
                note=f"the worst of {min(len(got), EXACT_ROWS)} rows, summed exactly",
                **head,
            )
        )
    out.append(
        _cases.exact_case(
            formula=f"each basis value within 2^-51 of the exact B-spline, {setting}",
            mismatches=far,
            cells=cells,
            compared_with="the exact B-spline (de Boor's recursion in fractions)",
            note=f"the first {EXACT_ROWS:,} rows at most, at sqlearn's knots",
            **head,
        )
    )
    return out


def _spline_cases(data: _cases.Dataset) -> list[dict]:
    """Return spline's cases on a dataset: knots, basis, scikit-learn."""
    present = _cases.present(data.values)
    out = []
    for knots in ("uniform", "quantile"):
        for n, degree in SPLINES:
            setting = f"n_knots = {n}, degree = {degree}"
            head = {
                "step": f"features.spline ({knots})",
                "dataset": data.name,
                "rows": len(data.values),
                "type": "DOUBLE",
            }
            if not present:
                out.append(
                    _refused(
                        head,
                        setting,
                        lambda d=data, k=knots, m=n, g=degree: _spline(d, k, m, g),
                        "no value to learn from",
                        "scikit-learn refuses no rows too (ValueError)",
                    )
                )
                continue
            t, got, pipe = _spline(data, knots, n, degree)
            base = t[degree : degree + n]
            exact = _exact_base(knots, n, present)
            out.append(_knot_cases(head, setting, knots, base, exact, BOUNDS[knots]))
            added = t[:degree] + t[degree + n :]
            exact_added = _exact_extended(base, degree)
            exact_added = exact_added[:degree] + exact_added[degree + n :]
            if added:
                out.append(
                    _knot_cases(
                        head,
                        f"{setting}, added",
                        knots,
                        added,
                        exact_added,
                        BOUNDS["added"],
                    )
                )
            out += _basis_cases(head, setting, t, degree, present, got)
            if len(data.values) != len(present):
                rel = _cases.sqlearn_table({data.column: data.values}, "DOUBLE")
                out.append(
                    _refused(
                        head,
                        f"a missing value, {setting}",
                        lambda p=pipe, r=rel: p.apply(r).fetchall(),
                        "a missing value reached the basis",
                        "scikit-learn refuses NaN too (handle_missing='error')",
                    )
                )
            if len(present) < 2:
                out.append(
                    _cases.skipped(
                        reference="sqlearn",
                        formula=f"basis against SplineTransformer, {setting}",
                        note="scikit-learn needs 2 rows; a constant column gives "
                        "zeros in both",
                        bound=0,
                        **head,
                    )
                )
                continue
            model = SplineTransformer(n_knots=n, degree=degree, knots=knots)
            values = np.array(present, dtype=float)[:, None]
            theirs = model.fit(values).transform(values)
            ours = np.array(got, dtype=float)
            compared = {**head, "compared_with": "scikit-learn SplineTransformer"}
            names = list(model.get_feature_names_out([data.column]))
            out.append(
                _cases.exact_case(
                    formula=f"names against get_feature_names_out, {setting}",
                    mismatches=int(pipe.columns_out_ != names),
                    cells=1,
                    **compared,
                )
            )
            out.append(
                _cases.exact_case(
                    formula=f"knots against bsplines_[0].t, {setting}",
                    mismatches=int(
                        sum(
                            a != b for a, b in zip(t, model.bsplines_[0].t, strict=True)
                        )
                    ),
                    cells=len(t),
                    **compared,
                )
            )
            out.append(
                _cases.exact_case(
                    formula=f"each basis value within 2^-51, {setting}",
                    mismatches=int((abs(ours - theirs) > TOLERANCE).sum()),
                    cells=theirs.size,
                    note=f"{data.note}; the present values",
                    **compared,
                )
            )
    return out


def cases() -> list[dict]:
    """Return sq.features' cases: polynomial's terms, then spline's bases."""
    out = []
    for data in _cases.numbers():
        out += _polynomial_cases(data)
    for data in _cases.numbers():
        out += _spline_cases(data)
    return out

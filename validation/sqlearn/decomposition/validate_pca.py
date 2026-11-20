"""Validate PCA against the exact eigenvalues, eigenvectors and outputs.

The canonical values (ADR 0016): the covariance of each dataset, divided by
the rows less one, is exact, a `Fraction` from the doubles' exact values;
its eigenvalues and eigenvectors are `mpmath.eigsy`'s at `_cases.DIGITS`
digits, largest first, each eigenvector's sign the one making its largest
entry in absolute value positive (spec §4.3, scikit-learn's ``svd_flip``
with ``u_based_decision=False``); each output is the row less the exact
mean, times the exact eigenvector, at the same precision. Every component
is kept (``n_components=None``: the smaller of the rows and the columns).

The answers are measured as the perturbation theory of a symmetric matrix
says they can be reached in doubles, not each against its own last digit:
the covariance carries a rounding of the size of its largest eigenvalue
``λ₁`` in every entry, so

- an eigenvalue moves by up to that much (Weyl): it is measured in ULPs of
  ``λ₁``;
- an eigenvector turns by up to that much over its gap ``g``, its distance
  to the nearest other eigenvalue (Davis and Kahan): each entry is measured
  in ULPs of ``κ = max(1, λ₁ / g)``, the worst entry the case;
- an output is the row less the mean, times the eigenvector: it is
  measured in ULPs of ``κ`` times the length of the row less the exact
  mean, plus the mean's length (the mean is rounded to a double before it
  is subtracted, by ``½`` ULP of each of its values: 7e-9 at 1e8, beside
  rows of length 1), the worst row the case.

``ulps`` holds that distance (a float) and ``ulps_of`` the scale it is
counted at; ``abs_error`` and ``rel_error`` are against the exact value
itself. A plain ULP distance would call a tiny eigenvalue (the nearly
collinear columns' 5e-13) or a tiny output wrong that no computation in
doubles gets closer to.

A component whose eigenvalue lies within 1e-8 (an absolute distance) of a
neighbour's (spec §7: the more columns than rows' zero eigenvalues) is
ill-defined alone: its eigenvector is recorded as skipped, and the outputs
of its group of neighbours are measured together, as the length of each
row's projection on the group, which no choice of basis inside the group
changes (measured at ``κ`` of the group's gap to the other eigenvalues).
Where ``n_components`` keeps only part of a group, the exact length of the
kept part lies between 0 and the whole group's: the distance is measured
to that range.

The datasets: ``devdata``'s iris, wine and breast cancer (development data,
ADR 0053), and generated ones from `_cases.SEED`: nearly collinear columns
(one column another plus 1e-6 noise), a constant column, more columns than
rows, and values of magnitude 1e8 with a spread of 1. Beside sqlearn:
scikit-learn's ``PCA(svd_solver="covariance_eigh")`` and numpy (``eigh`` of
``numpy.cov``, sorted, signed and applied the same way).

Anomalies expected of the references, by design rather than defect:

- scikit-learn's ``covariance_eigh`` takes the uncentred XᵀX and subtracts
  the means' outer product afterwards (spec §4.3 centres first): on
  ``far from zero`` (values at 1e8, spread 1) its covariance is a
  difference of terms near 2e18 and keeps no correct digit (5e16 ULPs of
  the largest eigenvalue; its components and outputs as far off), and on
  iris (means near 5 beside spreads near 1) its largest eigenvalue is 36
  ULPs off and its first component 17.
- numpy's ``cov`` centres by its own mean, a pairwise sum 3 ULPs off on
  ``far from zero``, and does not centre again: its covariance carries
  the mean's error squared times n / (n - 1), 2e-15, and its components
  are 9 to 13 ULPs off there (its eigenvalues 10, within 4 times the
  bound). sqlearn's mean is compensated (``sqlearn.agg.mean``), within
  a rounding, and leaves that term below one.
"""

import functools
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import mpmath
import numpy as np
from sklearn import decomposition as skd

import devdata
import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016), in ULPs of each measure's scale
# (the module's docstring), each about a tenth above the most sqlearn
# measured over every dataset (in brackets). Loosening a bound needs a
# written reason here, never a quiet edit. First measured 2026-11-20:
# - eigenvalue [7.48, wine's largest]: the Gram matrix of the centred rows
#   in numpy, then numpy's eigh; numpy's own ``cov`` and ``eigh`` measure
#   the same there.
# - component [1.74, breast cancer's first entry]: numpy's eigh of that
#   covariance, the sign chosen exactly.
# - output [1.93, breast cancer's pca0]: the row less the learned mean
#   (compensated, ``sqlearn.agg.mean``), times the weights, summed in
#   DuckDB.
BOUNDS = {
    "eigenvalue": 8.3,
    "component": 2.0,
    "output": 2.2,
}

NEIGHBOUR = 1e-8
"""Eigenvalues this close are one group: their components are measured
through their outputs only (spec §7)."""


@dataclass(frozen=True)
class Problem:
    """A table of numeric columns, every row present and finite."""

    name: str
    note: str
    columns: dict[str, tuple[float, ...]]

    @property
    def rows(self) -> int:
        """Return the number of rows."""
        return len(next(iter(self.columns.values())))

    def matrix(self) -> np.ndarray:
        """Return the rows as a float array, one column per input."""
        return np.column_stack(
            [np.array(v, dtype=float) for v in self.columns.values()]
        )


def _bundled(name: str, make: Callable) -> Problem:
    rel = make()
    names = [c for c in rel.columns if c != "target"]
    rows = rel.project(", ".join(f'"{c}"' for c in names)).fetchall()
    columns = {c: tuple(float(r[j]) for r in rows) for j, c in enumerate(names)}
    return Problem(
        name, f"devdata's {name}: {len(rows)} rows, {len(names)} columns", columns
    )


def _problems() -> list[Problem]:
    """Return each dataset: devdata's three and the generated ones."""
    out = [
        _bundled("iris", devdata.iris),
        _bundled("wine", devdata.wine),
        _bundled("breast cancer", devdata.breast_cancer),
    ]
    rng = np.random.default_rng(_cases.SEED)

    def floats(values: np.ndarray) -> tuple[float, ...]:
        return tuple(float(v) for v in values)

    a, b, c = (rng.normal(size=200) for _ in range(3))
    out.append(
        Problem(
            "nearly collinear",
            "200 rows, a column a + 1e-6 noise",
            {
                "a": floats(a),
                "b": floats(b),
                "a again": floats(a + 1e-6 * rng.normal(size=200)),
                "c": floats(c),
            },
        )
    )
    out.append(
        Problem(
            "constant",
            "200 rows, a column of 2.5",
            {"a": floats(a), "flat": (2.5,) * 200, "b": floats(b)},
        )
    )
    wide = rng.normal(size=(5, 8))
    out.append(
        Problem(
            "more columns than rows",
            "5 rows, 8 columns",
            {f"x{j}": floats(wide[:, j]) for j in range(8)},
        )
    )
    far = 1e8 + rng.normal(size=(200, 3))
    out.append(
        Problem(
            "far from zero",
            "200 rows at 1e8, spread 1",
            {f"x{j}": floats(far[:, j]) for j in range(3)},
        )
    )
    return out


# The exact values.


def _mpf(value: Fraction) -> mpmath.mpf:
    return mpmath.mpf(value.numerator) / value.denominator


@dataclass(frozen=True)
class Exact:
    """The exact decomposition: eigenvalues largest first, signed eigenvectors.

    ``centred`` holds each row less the exact mean, at `_cases.DIGITS`, and
    ``mean_length`` the length of the exact mean.
    """

    values: list[mpmath.mpf]
    vectors: list[list[mpmath.mpf]]
    centred: list[list[mpmath.mpf]]
    mean_length: mpmath.mpf

    def output(self, row: int, k: int) -> mpmath.mpf:
        """Return the exact output of component `k` for `row`."""
        return mpmath.fsum(
            d * w for d, w in zip(self.centred[row], self.vectors[k], strict=True)
        )

    def scale(self, row: int, kappa: float) -> float:
        """Return the scale an output of `row` is measured at: κ‖x - m‖ + ‖m‖."""
        length = mpmath.sqrt(mpmath.fsum(d * d for d in self.centred[row]))
        return float(kappa * length + self.mean_length)


@functools.cache
def _exact(name: str) -> Exact:
    """Return the exact decomposition of dataset `name`'s covariance."""
    problem = PROBLEMS[name]
    columns = [[Fraction(v) for v in values] for values in problem.columns.values()]
    n, p = problem.rows, len(columns)
    means = [sum(c, Fraction(0)) / n for c in columns]
    centred = [[v - m for v in c] for c, m in zip(columns, means, strict=True)]
    with mpmath.workdps(_cases.DIGITS):
        covariance = mpmath.matrix(p, p)
        for i in range(p):
            for j in range(i, p):
                total = sum(
                    (x * y for x, y in zip(centred[i], centred[j], strict=True)),
                    Fraction(0),
                )
                covariance[i, j] = covariance[j, i] = _mpf(total / (n - 1))
        values, vectors = mpmath.eigsy(covariance)
        order = sorted(range(p), key=lambda k: -values[k])
        signed = []
        for k in order:
            v = [vectors[j, k] for j in range(p)]
            largest = max(range(p), key=lambda j: abs(v[j]))
            signed.append([-w for w in v] if v[largest] < 0 else v)
        rows = [[_mpf(centred[j][r]) for j in range(p)] for r in range(n)]
        length = mpmath.sqrt(mpmath.fsum(_mpf(m) ** 2 for m in means))
        return Exact([values[k] for k in order], signed, rows, length)


def _groups(values: list[mpmath.mpf]) -> list[list[int]]:
    """Return the eigenvalues in groups: each within `NEIGHBOUR` of the next."""
    out = [[0]]
    with mpmath.workdps(_cases.DIGITS):
        for k in range(1, len(values)):
            if values[k - 1] - values[k] <= NEIGHBOUR:
                out[-1].append(k)
            else:
                out.append([k])
    return out


def _kappa(values: list[mpmath.mpf], group: list[int]) -> float:
    """Return ``max(1, λ₁ / gap)``: the gap from `group` to the other eigenvalues."""
    others = [v for k, v in enumerate(values) if k not in group]
    if not others:
        return 1.0
    with mpmath.workdps(_cases.DIGITS):
        gap = min(abs(values[g] - v) for g in group for v in others)
        return max(1.0, float(values[0] / gap))


# The answers.


@dataclass(frozen=True)
class Answer:
    """One library's decomposition: kept eigenvalues, components and outputs."""

    values: list[float]
    vectors: list[list[float]]
    outputs: np.ndarray


@functools.cache
def _sqlearn(name: str) -> Answer:
    problem = PROBLEMS[name]
    names = list(problem.columns)
    rel = _cases.sqlearn_table(
        problem.columns | {"row": tuple(range(problem.rows))},
        dict.fromkeys(names, "DOUBLE") | {"row": "BIGINT"},
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipe = sq.Pipeline([sq.decompose.pca(cols=names)]).learn(rel)
        pca = pipe["pca"]
        k = pca.n_components_
        outputs = [f'"pca{i}"' for i in range(k)]
        got = pipe.apply(rel).order('"row"').project(", ".join(outputs)).fetchall()
    return Answer(
        list(pca.explained_variance_),
        pca.components_,
        np.array(got, dtype=float).reshape(problem.rows, k),
    )


def _sklearn(name: str) -> Answer:
    x = PROBLEMS[name].matrix()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pca = skd.PCA(svd_solver="covariance_eigh").fit(x)
        outputs = pca.transform(x)
    return Answer(
        [float(v) for v in pca.explained_variance_], pca.components_.tolist(), outputs
    )


def _numpy(name: str) -> Answer:
    x = PROBLEMS[name].matrix()
    k = min(x.shape)
    values, vectors = np.linalg.eigh(np.cov(x, rowvar=False))
    values, vectors = values[::-1], vectors[:, ::-1].T
    largest = np.abs(vectors).argmax(axis=1)
    vectors = vectors * np.sign(vectors[np.arange(len(vectors)), largest])[:, None]
    outputs = (x - x.mean(axis=0)) @ vectors[:k].T
    return Answer(values[:k].tolist(), vectors[:k].tolist(), outputs)


ANSWERS: dict[str, Callable[[str], Answer]] = {
    "sqlearn": _sqlearn,
    "numpy": _numpy,
    "scikit-learn": _sklearn,
}


# The cases.


def _measured(
    head: dict,
    reference: str,
    value: float,
    exact: mpmath.mpf,
    scale: float,
    note: str,
) -> dict:
    """Return the case of `value` against `exact`, in ULPs of `scale`."""
    with mpmath.workdps(_cases.DIGITS):
        distance = float(abs(mpmath.mpf(value) - exact) / math.ulp(scale))
        out = _cases.case(
            reference=reference, value=value, exact=exact, note=note, **head
        )
    out["ulps"] = distance
    out["ulps_of"] = scale
    out["result"] = _cases.judge(reference, distance, head["bound"])
    return out


def _worst(
    head: dict,
    reference: str,
    values: list[float],
    exact: list[mpmath.mpf],
    scales: list[float],
    what: str,
    note: str = "",
) -> dict:
    """Return the case of the worst of `values`, each in ULPs of its scale."""
    with mpmath.workdps(_cases.DIGITS):
        distances = [
            abs(mpmath.mpf(v) - e) / math.ulp(s)
            for v, e, s in zip(values, exact, scales, strict=True)
        ]
    i = max(range(len(values)), key=lambda j: distances[j])
    worst = f"the worst of {len(values)}: {what} {i}" + (f"; {note}" if note else "")
    return _measured(head, reference, values[i], exact[i], scales[i], worst)


def _head(problem: Problem, formula: str, measure: str) -> dict:
    return {
        "step": "pca",
        "formula": formula,
        "dataset": problem.name,
        "rows": problem.rows,
        "type": "DOUBLE",
        "bound": BOUNDS[measure],
    }


def _between(value: float, top: mpmath.mpf) -> mpmath.mpf:
    """Return the point of [0, `top`] nearest `value`."""
    return min(max(mpmath.mpf(value), mpmath.mpf(0)), top)


def _group_cases(
    problem: Problem,
    exact: Exact,
    group: list[int],
    kept: int,
    answer: Answer,
    reference: str,
) -> list[dict]:
    """Return the cases of a group of near-equal eigenvalues' outputs and vectors."""
    out = []
    members = [k for k in group if k < kept]
    kappa = _kappa(exact.values, group)
    for k in members:
        note = (
            f"eigenvalue within {NEIGHBOUR:g} of a neighbour's: ill-defined "
            f"alone, measured through the outputs of pca{group[0]} to "
            f"pca{group[-1]} together"
        )
        out.append(
            _cases.skipped(
                reference=reference,
                note=note,
                **_head(problem, f"components_[{k}]", "component"),
            )
        )
    with mpmath.workdps(_cases.DIGITS):
        whole = [
            mpmath.sqrt(mpmath.fsum(exact.output(r, k) ** 2 for k in group))
            for r in range(problem.rows)
        ]
        values = [math.hypot(*answer.outputs[r, members]) for r in range(problem.rows)]
        if members == group:
            want, note = whole, ""
        else:
            want = [_between(v, w) for v, w in zip(values, whole, strict=True)]
            note = (
                f"n_components keeps {len(members)} of the group's {len(group)}: "
                "measured to the range from 0 to the whole group's length"
            )
        scales = [exact.scale(r, kappa) for r in range(problem.rows)]
    formula = f"length of pca{members[0]} to pca{members[-1]}"
    head = _head(problem, formula, "output")
    out.append(_worst(head, reference, values, want, scales, "row", note))
    return out


def _problem_cases(problem: Problem) -> list[dict]:
    """Return every case of one dataset, for each reference."""
    exact = _exact(problem.name)
    lam = float(exact.values[0])
    groups = _groups(exact.values)
    out = []
    for reference, compute in ANSWERS.items():
        try:
            answer = compute(problem.name)
        except Exception as exc:  # noqa: BLE001  (each library's own refusal is recorded)
            result = "fail" if reference == "sqlearn" else "skipped"
            out.append(
                _cases.skipped(
                    reference=reference,
                    result=result,
                    note=_cases.first_line(exc),
                    **_head(problem, "PCA", "eigenvalue"),
                )
            )
            continue
        kept = len(answer.values)
        for k in range(kept):
            head = _head(problem, f"explained_variance_[{k}]", "eigenvalue")
            out.append(
                _measured(
                    head,
                    reference,
                    answer.values[k],
                    exact.values[k],
                    lam,
                    "in ULPs of the largest eigenvalue",
                )
            )
        for group in groups:
            if group[0] >= kept:
                break
            if len(group) > 1:
                out += _group_cases(problem, exact, group, kept, answer, reference)
                continue
            k = group[0]
            kappa = _kappa(exact.values, group)
            head = _head(problem, f"components_[{k}]", "component")
            p = len(exact.vectors[k])
            out.append(
                _worst(
                    head,
                    reference,
                    answer.vectors[k],
                    exact.vectors[k],
                    [kappa] * p,
                    "entry",
                )
            )
            with mpmath.workdps(_cases.DIGITS):
                want = [exact.output(r, k) for r in range(problem.rows)]
                scales = [exact.scale(r, kappa) for r in range(problem.rows)]
            head = _head(problem, f"pca{k}", "output")
            out.append(
                _worst(
                    head, reference, answer.outputs[:, k].tolist(), want, scales, "row"
                )
            )
    return out


PROBLEMS = {p.name: p for p in _problems()}


def cases() -> list[dict]:
    """Return the cases of PCA: each dataset and reference."""
    out = []
    for problem in PROBLEMS.values():
        out += _problem_cases(problem)
    return out

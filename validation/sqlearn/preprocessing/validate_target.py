"""Validate sq.encode.target against scikit-learn's TargetEncoder and the formulae.

Each encoding is a rational function of the target's values, so its exact
value is computed with `Fraction` from scikit-learn's formulae (the
population variances, ``λ = n·v / (n·v + s²)``, an empty or spreadless
category getting the mean) and compared with sqlearn's and scikit-learn's
(ADR 0016). Three things are measured on each dataset:

- **fit then transform:** ``learn(data, target=)`` then ``apply`` against
  ``TargetEncoder().fit(X, y).transform(X)``, one case per category (NULL
  included when seen), with ``smooth="auto"`` and with ``smooth=10``;
- **cross-fitted:** ``train``'s prepared rows against ``fit_transform``,
  scikit-learn given sqlearn's own inner folds as ``cv`` splits, one case
  per inner fold and category;
- **the pipeline:** the mean a standard scaler after the encoder learns in
  ``train``, from the cross-fitted values, as scikit-learn's ``Pipeline``.

The "unseen" dataset learns without NULL and is applied to a word never
learned and to NULL: both get the target's mean, as scikit-learn's.
"""

import math
from collections.abc import Callable, Sequence
from fractions import Fraction

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.preprocessing import TargetEncoder

import sqlearn as sq
from validation import _cases
from validation.sqlearn.preprocessing._encoders import UNSEEN_WORD

COMPARED_WITH = "scikit-learn TargetEncoder, given sqlearn's inner folds as cv"
CV = 5

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: worst 1
# ULP for every formula and dataset, inner folds dealt by a hash of the
# features. Measured again with folds dealt by position (Ruling T10a): the
# cross-fitted binary values showed 2 ULPs from the rounding of the formula
# in doubles, so the formula moved to exact arithmetic over the fetched sums
# (`Fraction`, one rounding): worst 0 ULPs, but 1 for the scaler's mean (its
# own sum). The bounds stay at 1. scikit-learn's plain sums drift up to 6
# ULPs on the continuous target (an anomaly against these bounds).
BOUNDS = {"all": 1, "smooth": 1, "crossed": 1, "pipeline": 1}

FORMULAS = {
    "all": "fit then transform: λ·mean + (1 - λ)·m, λ = n·v / (n·v + s²)",
    "smooth": "fit then transform, smooth=10: (n·mean + 10·m) / (n + 10)",
    "crossed": "cross-fitted: each fold's complement, as fit_transform",
    "pipeline": "standard scaler after it: mean of the cross-fitted values",
}


class _Recorder(BaseEstimator, ClassifierMixin):
    """A model that keeps the features it is trained on."""

    seen: list[np.ndarray] = []  # noqa: RUF012  (read after train)

    def fit(self, x: np.ndarray, y: np.ndarray) -> "_Recorder":
        _Recorder.seen.append(np.array(x))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.zeros(len(x))


def _datasets() -> list[tuple[str, str, tuple, tuple, str]]:
    """Return name, kind, plans, targets and a note per dataset, seed 0."""
    rng = np.random.default_rng(_cases.SEED)
    words = np.array([*_cases.WORDS, None], dtype=object)
    shift = {w: 0.15 * (i + 1) for i, w in enumerate(words)}

    def plans(n: int, null: bool = True) -> tuple:
        return tuple(rng.choice(words if null else words[:-1], n))

    out = []
    for name, n in (("small", 1_000), ("large", 100_000)):
        p = plans(n)
        y = tuple(int(rng.random() < shift[v]) for v in p)
        out.append((name, "binary", p, y, f"{n:,} rows, 5 words and NULL, 0/1"))
    p = plans(1_000)
    y = tuple(float(rng.normal(1_000.0 + 100 * shift[v], 100.0)) for v in p)
    out.append(("continuous", "continuous", p, y, "1,000 rows, normal(~1000, 100)"))
    p = plans(1_000, null=False)
    y = tuple(int(rng.random() < shift[v]) for v in p)
    out.append(("unseen", "binary", p, y, "learned without NULL; applied to new"))
    return out


def _exact(ys: Sequence[Fraction], by: dict[object, list[Fraction]], smooth: object):
    """Return the exact encoding per category over the rows given, and the mean."""
    n = len(ys)
    m = sum(ys, Fraction(0)) / n
    v = sum(((y - m) ** 2 for y in ys), Fraction(0)) / n
    out: dict[object, Fraction] = {}
    for c, values in by.items():
        k = len(values)
        if smooth != "auto":
            s = Fraction(smooth)  # type: ignore[arg-type]
            out[c] = m if k + s == 0 else (sum(values, Fraction(0)) + s * m) / (k + s)
            continue
        if k == 0:
            out[c] = m
            continue
        mu = sum(values, Fraction(0)) / k
        s2 = sum(((y - mu) ** 2 for y in values), Fraction(0)) / k
        weight = k * v + s2
        if weight == 0:
            out[c] = m
            continue
        lam = k * v / weight
        out[c] = lam * mu + (1 - lam) * m
    return out, m


def _group(plans: Sequence, ys: Sequence, rows: Sequence[int], cats: Sequence):
    by: dict[object, list[Fraction]] = {c: [] for c in cats}
    for i in rows:
        by[plans[i]].append(Fraction(ys[i]))
    return [Fraction(ys[i]) for i in rows], by


def _sk(plans: Sequence) -> np.ndarray:
    return np.array([[math.nan if p is None else p] for p in plans], dtype=object)


def _table(plans: Sequence, ys: Sequence, kind: str):
    y_kind = "INTEGER" if kind == "binary" else "DOUBLE"
    return _cases.sqlearn_table(
        {"plan": tuple(plans), "y": tuple(ys)}, {"plan": "VARCHAR", "y": y_kind}
    )


def _folds(rows: int) -> np.ndarray:
    """Return sqlearn's inner folds: KFold over each row's position, from 1."""
    fold = sq.KFold(CV, 0).expression("d")
    positions = _cases.sqlearn_table({"p": tuple(range(1, rows + 1))}, "BIGINT")
    return np.array([r[0] for r in positions.set_alias("d").project(fold).fetchall()])


def _measure(
    name: str, formula: str, dataset: str, rows: int, kind: str, exact: Fraction,
    answers: dict[str, Callable[[], float]], note: str = "",
) -> list[dict]:  # fmt: skip
    data = _cases.Dataset(dataset, "plan", tuple(range(rows)), note)
    return _cases.measure_all(
        step="encode.target",
        formula=f"{FORMULAS[formula]} [{name}]",
        data=data,
        type="VARCHAR",
        exact=exact,
        bound=BOUNDS[formula],
        answers=answers,
        notes={"scikit-learn": COMPARED_WITH},
    )


def _label(c: object) -> str:
    return "NULL" if c is None else str(c)


def _fit_cases(name: str, kind: str, plans: tuple, ys: tuple, note: str) -> list[dict]:
    """fit then transform: one case per category, smooth auto and 10."""
    out: list[dict] = []
    rel = _table(plans, ys, kind)
    cats = list(dict.fromkeys(plans))
    applied = [*cats, UNSEEN_WORD, None] if name == "unseen" else cats
    new = _cases.sqlearn_table({"plan": tuple(applied)}, "VARCHAR")
    for formula, smooth in (("all", "auto"), ("smooth", 10.0)):
        pipe = sq.Pipeline([sq.encode.target("plan", smooth=smooth)])
        got = pipe.learn(rel, target="y").apply(new, out="numpy")["plan"]
        encoder = TargetEncoder(target_type=kind, smooth=smooth)
        theirs = encoder.fit(_sk(plans), np.array(ys)).transform(_sk(applied))[:, 0]
        exact, mean = _exact(*_group(plans, ys, range(len(plans)), cats), smooth)
        for j, c in enumerate(applied):
            seen = c in exact
            out += _measure(
                f"{_label(c)}" + ("" if seen else ", not learned: the mean"),
                formula, name, len(plans), kind, exact[c] if seen else mean,
                {
                    "sqlearn": lambda j=j, got=got: float(got[j]),
                    "scikit-learn": lambda j=j, theirs=theirs: float(theirs[j]),
                },
                note,
            )  # fmt: skip
    return out


def _crossed_cases(
    name: str, kind: str, plans: tuple, ys: tuple, note: str
) -> list[dict]:
    """Cross-fitted rows and the scaler after: per inner fold and category."""
    rel = _table(plans, ys, kind)
    folds = _folds(len(plans))
    _Recorder.seen.clear()
    sq.Pipeline([sq.encode.target("plan", cv=CV), _Recorder()]).train(rel, target="y")
    ours = _Recorder.seen[-1][:, 0]
    pipe = sq.Pipeline(
        [sq.encode.target("plan", cv=CV), sq.scale.standard("plan"), _Recorder()]
    )
    center = pipe.train(rel, target="y")["standard"].center_["plan"]
    splits = [
        (np.flatnonzero(folds != k), np.flatnonzero(folds == k))
        for k in range(CV)
        if (folds == k).any()
    ]
    theirs = TargetEncoder(target_type=kind, cv=splits).fit_transform(
        _sk(plans), np.array(ys)
    )[:, 0]
    cats = list(dict.fromkeys(plans))
    out: list[dict] = []
    crossed: list[Fraction] = [Fraction(0)] * len(plans)
    for k in range(CV):
        inside = np.flatnonzero(folds == k)
        if not len(inside):
            continue
        exact, _ = _exact(*_group(plans, ys, np.flatnonzero(folds != k), cats), "auto")
        for i in inside:
            crossed[i] = exact[plans[i]]
        for c in cats:
            rows = [i for i in inside if plans[i] == c]
            if not rows:
                continue
            first = rows[0]
            out += _measure(
                f"fold {k}, {_label(c)}", "crossed", name, len(plans), kind,
                exact[c],
                {
                    "sqlearn": lambda first=first: float(ours[first]),
                    "scikit-learn": lambda first=first: float(theirs[first]),
                },
                note,
            )  # fmt: skip
    out += _measure(
        "centre", "pipeline", name, len(plans), kind,
        sum(crossed, Fraction(0)) / len(crossed),
        {
            "sqlearn": lambda: float(center),
            "scikit-learn": lambda: float(np.mean(theirs)),
        },
        note,
    )  # fmt: skip
    return out


def cases() -> list[dict]:
    """Return sq.encode.target's cases: all rows, cross-fitted, the pipeline."""
    out: list[dict] = []
    for name, kind, plans, ys, note in _datasets():
        out += _fit_cases(name, kind, plans, ys, note)
        if name != "unseen":
            out += _crossed_cases(name, kind, plans, ys, note)
    return out

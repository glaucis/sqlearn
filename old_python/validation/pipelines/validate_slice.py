"""Validate the slice's preparation, whole, against scikit-learn's pipeline.

sqlearn: ``impute.median → OneHot(city) → Ordinal(plan) → scale.standard(numeric())``,
where the scaler also scales the new one-hot and ordinal columns, being numeric.
scikit-learn's equivalent: a ``ColumnTransformer`` of ``SimpleImputer``,
``OneHotEncoder`` and ``OrdinalEncoder``, then ``StandardScaler`` over every
column. Both learn on the data and are applied to it; each output column's
worst absolute and relative difference is recorded (ADR 0016: whole
pipelines are validated, not only single steps).

``ulps`` here is the worst absolute difference counted in units of 2^-52,
the spacing of doubles at 1.0: every prepared column is standardised to a
spread of 1, so that is the scale its errors live on. A ULP count at each
value would be ruled by the values near 0, where the smallest difference in
a learned mean is a large relative error (the subtraction is ill
conditioned there, whoever computes it); that count is kept, for the
record, as ``ulps_at_value``.
"""

import math

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP difference measured, at least 1. Loosening it needs a
# written reason here, never a quiet edit. First measured: 3,100 units of
# 2^-52 in the large set's age column, from a mean 119 ULPs off; tightened
# to 128 when the mean moved to `favg` (ADR 0033), worst then 84.
BOUND = 128

COMPARED_WITH = (
    "scikit-learn Pipeline(ColumnTransformer(SimpleImputer(median), "
    "OneHotEncoder, OrdinalEncoder), StandardScaler)"
)
NOTE = (
    f"compared row by row with {COMPARED_WITH}; ulps is the worst absolute "
    "difference in units of 2^-52 (columns have unit spread), ulps_at_value "
    "the worst ULP count at a value"
)
CITIES = ("kyiv", "oslo", "rome")
PLANS = ("basic", "pro", "team")
KINDS = {"age": "DOUBLE", "income": "DOUBLE", "city": "VARCHAR", "plan": "VARCHAR"}


def _data() -> list[tuple[str, dict[str, tuple]]]:
    """Return the slice's data at each size: two numbers with gaps, two texts."""
    rng = np.random.default_rng(_cases.SEED)
    out = []
    for name, n in _cases.SIZES.items():
        age = _cases._gaps(rng, [float(v) for v in rng.normal(45.0, 12.0, n)], None)
        income = _cases._gaps(
            rng, [float(v) for v in rng.normal(3_000.0, 800.0, n)], None
        )
        city = [str(v) for v in rng.choice(CITIES, n)]
        plan = [str(v) for v in rng.choice(PLANS, n)]
        out.append(
            (
                name,
                {
                    "age": tuple(age),
                    "income": tuple(income),
                    "city": tuple(city),
                    "plan": tuple(plan),
                },
            )
        )
    return out


def _sqlearn(columns: dict[str, tuple]) -> pd.DataFrame:
    rel = _cases.sqlearn_table(columns, KINDS)
    pipe = sq.Pipeline(
        [
            ("impute", sq.impute.median(cols=sq.cols.numeric())),
            ("onehot", sq.encode.onehot(cols=["city"])),
            ("ordinal", sq.encode.ordinal(cols=["plan"])),
            ("scale", sq.scale.standard(cols=sq.cols.numeric())),
        ]
    ).learn(rel)
    return pipe.apply(rel, out="pandas")


def _sklearn(columns: dict[str, tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "age": _cases.as_nan(columns["age"]),
            "income": _cases.as_nan(columns["income"]),
            "city": list(columns["city"]),
            "plan": list(columns["plan"]),
        }
    )
    prep = ColumnTransformer(
        [
            ("impute", SimpleImputer(strategy="median"), ["age", "income"]),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ["city"],
            ),
            (
                "ordinal",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                ["plan"],
            ),
        ],
        verbose_feature_names_out=False,
    )
    pipe = Pipeline([("prep", prep), ("scale", StandardScaler())])
    return pipe.set_output(transform="pandas").fit_transform(frame)


def cases() -> list[dict]:
    """Return the slice's cases: each output column at each size."""
    out = []
    for name, columns in _data():
        ours, theirs = _sqlearn(columns), _sklearn(columns)
        rows = len(columns["age"])
        for col in theirs.columns:
            head = {
                "step": "slice",
                "formula": f"prepared column {col}",
                "dataset": name,
                "rows": rows,
                "type": "DOUBLE",
                "reference": "sqlearn",
                "bound": BOUND,
            }
            if col not in ours.columns:
                out.append(
                    _cases.skipped(
                        result="fail", note=f"sqlearn has no column {col!r}", **head
                    )
                )
                continue
            a = ours[col].to_numpy(dtype=float)
            b = theirs[col].to_numpy(dtype=float)
            diff = np.abs(a - b)
            scale = np.abs(b)
            with np.errstate(divide="ignore", invalid="ignore"):
                rel = np.where(diff == 0, 0.0, diff / scale)
            at_value = max(
                _cases.ulps(float(x), float(y)) for x, y in zip(a, b, strict=True)
            )
            distance = math.ceil(float(diff.max()) / 2**-52)
            worst = int(np.argmax(diff))
            case = _cases._head(note=NOTE, **head)
            case |= {
                "compared_with": "scikit-learn",
                "value": float(a[worst]),
                "canonical": None,
                "abs_error": float(diff.max()),
                "rel_error": float(rel.max()),
                "ulps": distance,
                "ulps_at_value": at_value,
                "result": "pass" if distance <= BOUND else "fail",
            }
            out.append(case)
        extra = sorted(set(ours.columns) - set(theirs.columns))
        if extra:
            out.append(
                _cases.skipped(
                    result="fail",
                    note=f"sqlearn has columns scikit-learn has not: {extra}",
                    step="slice",
                    formula="columns",
                    dataset=name,
                    rows=len(columns["age"]),
                    type="DOUBLE",
                    reference="sqlearn",
                    bound=BOUND,
                )
            )
    return out

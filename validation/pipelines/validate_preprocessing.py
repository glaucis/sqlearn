"""Validate the preprocessing spec's script (§2), whole, against scikit-learn.

sqlearn runs the script as the spec writes it: two imputers, ``log1p``, a
robust scaler searched over its centre, one-hot and target encoders, quantile
bins, polynomial features and a logistic regression, searched with five folds.
scikit-learn's equivalent is a ``Pipeline`` of one ``ColumnTransformer`` per
step, in the same order, searched by ``GridSearchCV``, and handed sqlearn's
own folds as splits: the outer folds (``GridSearchCV(cv=...)``) and, through
each fold's training rows, the target encoder's inner folds
(``TargetEncoder(cv=...)``). The robust scaler centred on the mean is
scikit-learn's ``StandardScaler(with_std=False)`` then
``RobustScaler(with_centering=False)``: the interquartile range does not move
with the centre.

The cases: each setting's mean score, the best setting, every prediction on
new data, and each column the best pipeline prepares from the new data, by
name (scikit-learn writes ``age income`` where sqlearn writes ``age*income``,
ADR 0035, and places the one-hot and polynomial columns elsewhere).
"""

import contextlib
import json
import math
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, PredefinedSplit
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import (
    FunctionTransformer,
    KBinsDiscretizer,
    OneHotEncoder,
    PolynomialFeatures,
    RobustScaler,
    StandardScaler,
    TargetEncoder,
)

import sqlearn as sq
from sqlearn._config import connection
from validation import _cases

ROWS = 10_000
"""The training rows, in two Parquet files."""

NEW_ROWS = 2_000
"""The rows predicted, drawn after the training rows from the same seed."""

CV = 5
"""The outer folds (the search's default) and the target encoder's inner folds."""

POSITION = "position"
"""The column scikit-learn is given beside the data: each row's position from 1."""

# Set from the first measurement (ADR 0016), as the slice's: the smallest
# power of two at or above the worst difference measured, in units of 2^-52,
# at least 1. Loosening it needs a written reason here, never a quiet edit.
# First measured: 104, in income^2, whose values reach 12 (so its absolute
# differences are an order above the unit-spread columns'); 13 to 26 ULPs at
# the value in income, age*income and income^2, from log1p and the exact
# quantiles of the robust scaler against numpy's interpolated ones. Every
# other column, the scores, the best setting and the predictions agree exactly.
BOUND = 128

COMPARED_WITH = (
    "scikit-learn GridSearchCV(Pipeline(ColumnTransformer per step), "
    "cv=sqlearn's folds), TargetEncoder(cv=sqlearn's inner folds)"
)
NOTE = (
    "the new data as each side's best pipeline prepares it, compared by "
    "column name; ulps is the worst absolute difference in units of 2^-52, "
    "ulps_at_value the worst ULP count at a value"
)
CITIES = ("kyiv", "lima", "oslo", "rome")
PLANS = ("basic", "plus", "pro")


def customers(rows: int, start: int = 0) -> pd.DataFrame:
    """Return rows `start` to `start + rows` of the script's data, seed 0.

    Age and income with gaps, a city with gaps, a plan, and whether the
    customer churned, which depends on all four.
    """
    rng = np.random.default_rng(_cases.SEED)
    n = start + rows
    age = rng.normal(40.0, 12.0, n)
    income = rng.lognormal(10.5, 0.5, n)
    city = rng.choice(np.array(CITIES, dtype=object), n)
    plan = rng.choice(np.array(PLANS, dtype=object), n, p=[0.5, 0.3, 0.2])
    signal = (
        0.04 * (age - 40.0)
        - 0.8 * (np.log(income) - 10.5) / 0.5
        + 0.9 * (plan == "basic")
        + 0.5 * (city == "oslo")
        + rng.normal(0.0, 1.0, n)
    )
    frame = pd.DataFrame(
        {
            "age": np.where(rng.random(n) < 0.1, np.nan, age),
            "income": np.where(rng.random(n) < 0.05, np.nan, income),
            "city": np.where(rng.random(n) < 0.05, None, city),
            "plan": plan,
            "churned": (signal > 0.4).astype(np.int64),
        }
    )
    return frame.iloc[start:].reset_index(drop=True)


def write_data(root: Path) -> None:
    """Write the script's files under `root`: data/train/*.parquet, data/new.parquet."""
    (root / "data" / "train").mkdir(parents=True)
    every = customers(ROWS + NEW_ROWS)
    half = ROWS // 2
    parts = {
        root / "data" / "train" / "0.parquet": every.iloc[:half],
        root / "data" / "train" / "1.parquet": every.iloc[half:ROWS],
        root / "data" / "new.parquet": every.iloc[ROWS:].drop(columns="churned"),
    }
    for path, part in parts.items():
        duckdb.from_df(part.reset_index(drop=True)).write_parquet(str(path))


def run_the_script() -> tuple[sq.Search, pd.DataFrame]:
    """Run spec §2's script, as written there, from the current directory."""
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.impute("city", value="mode"),
            sq.transform.log1p("income"),
            sq.scale.robust(),
            sq.encode.onehot("city"),
            sq.encode.target("plan"),
            sq.bin.quantile("age", n=5),
            sq.features.polynomial("age", "income"),
            LogisticRegression(),
        ]
    )

    search = sq.Search(
        pipe,
        params={"robust__center": [sq.agg.median, sq.agg.mean], "model__C": [0.1, 1]},
        metric=sq.metrics.accuracy,
    )
    search.train("data/train/*.parquet", target="churned")
    return search, search.predict("data/new.parquet", out="pandas")


def inner_folds(rows: int, cv: int = CV, seed: int = 0) -> np.ndarray:
    """Return ``sq.KFold(cv, seed)``'s fold of each position from 1 to `rows`.

    The target encoder deals its inner folds by the row's position in the
    data as read, numbered once before a search splits the outer folds
    (as ``position_folds`` in the target encoder's tests).
    """
    positions = connection().sql(f"SELECT range + 1 AS p FROM range({rows})")
    fold = sq.KFold(cv, seed).expression("d")
    return np.array([r[0] for r in positions.set_alias("d").project(fold).fetchall()])


def splits(folds: np.ndarray, cv: int = CV) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return the folds as scikit-learn's splits: (train, test) per fold."""
    return [
        (np.flatnonzero(folds != k), np.flatnonzero(folds == k))
        for k in range(cv)
        if (folds == k).any()
    ]


class ByPosition(BaseEstimator, TransformerMixin):
    """scikit-learn's TargetEncoder, with sqlearn's inner folds as its `cv`.

    It is given the column and each row's position; the splits are dealt
    from the positions of the rows it is fitted on, so inside an outer fold
    they are taken within that fold's training rows, as sqlearn takes them.
    """

    def __init__(self, column: str = "plan", folds: np.ndarray | None = None) -> None:
        self.column = column
        self.folds = folds

    def fit_transform(self, x: pd.DataFrame, y: object = None) -> np.ndarray:
        """Fit on the rows' own inner folds, cross-fitting them."""
        assert self.folds is not None
        positions = x[POSITION].to_numpy(dtype=np.int64)
        cv = splits(self.folds[positions - 1])
        self.encoder_ = TargetEncoder(target_type="binary", cv=cv)
        return self.encoder_.fit_transform(_objects(x[[self.column]]), y)

    def fit(self, x: pd.DataFrame, y: object = None) -> "ByPosition":
        """Fit, as fit_transform does."""
        self.fit_transform(x, y)
        return self

    def transform(self, x: pd.DataFrame) -> np.ndarray:
        """Encode with what was learned on every row fitted."""
        return self.encoder_.transform(_objects(x[[self.column]]))

    def get_feature_names_out(self, input_features: object = None) -> np.ndarray:
        """Name the one column made: the column encoded."""
        return np.array([self.column], dtype=object)


def _objects(frame: pd.DataFrame) -> np.ndarray:
    """Return text columns as an object array, a missing value as NaN."""
    return np.array(
        [[math.nan if pd.isna(v) else v for v in row] for row in frame.to_numpy()],
        dtype=object,
    )


def _step(name: str, transformer: object, columns: list[str]) -> ColumnTransformer:
    """Return one sqlearn step as scikit-learn's: a transformer on `columns`."""
    return ColumnTransformer(
        [(name, transformer, columns)],
        remainder="passthrough",
        verbose_feature_names_out=False,
    )


def sklearn_pipeline(folds: np.ndarray) -> Pipeline:
    """Return the script's pipeline in scikit-learn, step for step."""
    steps = [
        ("median", _step("i", SimpleImputer(strategy="median"), ["age", "income"])),
        (
            "mode",
            _step("i", SimpleImputer(strategy="most_frequent"), ["city"]),
        ),
        (
            "log1p",
            _step(
                "t",
                FunctionTransformer(np.log1p, feature_names_out="one-to-one"),
                ["income"],
            ),
        ),
        ("robust", _step("scaler", RobustScaler(), ["age", "income"])),
        ("onehot", _step("e", OneHotEncoder(sparse_output=False), ["city"])),
        ("target", _step("e", ByPosition("plan", folds), ["plan", POSITION])),
        (
            "quantile",
            _step(
                "b",
                KBinsDiscretizer(
                    n_bins=5, encode="ordinal", strategy="quantile", subsample=None
                ),
                ["age"],
            ),
        ),
        (
            "polynomial",
            _step("f", PolynomialFeatures(include_bias=False), ["age", "income"]),
        ),
        ("model", LogisticRegression()),
    ]
    return Pipeline(steps).set_output(transform="pandas")


CENTRES = {
    "median": RobustScaler(),
    "mean": make_pipeline(
        StandardScaler(with_std=False), RobustScaler(with_centering=False)
    ),
}
"""``robust__center`` in scikit-learn: the median, or the mean then the IQR."""
for _centre in CENTRES.values():
    _centre.set_output(transform="pandas")


def sklearn_search(train: pd.DataFrame, outer: np.ndarray) -> GridSearchCV:
    """Return scikit-learn's search of the script, fitted on sqlearn's folds."""
    folds = inner_folds(len(train))
    sk = GridSearchCV(
        sklearn_pipeline(folds),
        {
            "model__C": [0.1, 1],
            "robust__scaler": list(CENTRES.values()),
        },
        scoring="accuracy",
        cv=PredefinedSplit(outer),
    )
    x = _for_sklearn(train.drop(columns="churned"))
    return sk.fit(x, train["churned"].to_numpy())


def _for_sklearn(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the data with text as objects (NaN for missing) and positions."""
    out = frame.copy()
    for column in ("city", "plan"):
        out[column] = pd.Series(_objects(out[[column]])[:, 0], dtype=object)
    out[POSITION] = np.arange(1, len(out) + 1)
    return out


def read_training() -> tuple[pd.DataFrame, np.ndarray]:
    """Return the training rows as sqlearn reads them, and each row's outer fold."""
    rel = connection().read_parquet("data/train/*.parquet")
    numbered = sq.KFold(CV, 0).numbered(rel, "__fold").df()
    outer = numbered.pop("__fold").to_numpy()
    return numbered, outer


def as_sqlearn(params: dict) -> dict:
    """Return a scikit-learn setting in sqlearn's names, in the search's order."""
    centre = next(k for k, v in CENTRES.items() if v is params["robust__scaler"])
    return {"model__C": params["model__C"], "robust__center": getattr(sq.agg, centre)}


@contextlib.contextmanager
def in_directory(root: Path) -> Iterator[None]:
    """Run the block from `root`, as the script runs from its own folder."""
    before = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(before)


def prepared(search: sq.Search, new: pd.DataFrame) -> pd.DataFrame:
    """Return the new data as sqlearn's best pipeline prepares it.

    Its steps learn on every training row (``learn`` then ``apply``, as
    scikit-learn's ``fit`` then ``transform``): the values ``predict`` uses.
    """
    pipe = search.best_pipeline_
    prep = sq.Pipeline([pipe[i] for i in range(len(pipe.steps) - 1)])
    prep.learn("data/train/*.parquet", target="churned")
    return prep.apply(new, out="pandas")


@dataclass
class Compared:
    """What each side gave, in sqlearn's names."""

    search: sq.Search
    """sqlearn's search, trained."""
    best: dict
    """scikit-learn's best setting."""
    scores: dict[tuple[str, int], float]
    """sqlearn's score per setting (as the results write it) and fold."""
    sk_scores: dict[tuple[str, int], float]
    """scikit-learn's, keyed alike."""
    predicted: np.ndarray
    """sqlearn's predictions on the new data."""
    sk_predicted: np.ndarray
    """scikit-learn's."""
    prepared: pd.DataFrame
    """The new data as sqlearn's best pipeline prepares it."""
    sk_prepared: pd.DataFrame
    """scikit-learn's, its columns renamed to sqlearn's labels."""


def compare() -> Compared:
    """Run the script and scikit-learn's search on the generated data."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_data(root)
        with in_directory(root):
            search, predicted = run_the_script()
            train, outer = read_training()
            new = connection().read_parquet("data/new.parquet").df()
            ours = prepared(search, new)
    grid = sklearn_search(train, outer)
    results = grid.cv_results_
    sk_scores = {
        (json.dumps(as_sqlearn(params), default=repr), k): float(
            results[f"split{k}_test_score"][i]
        )
        for i, params in enumerate(results["params"])
        for k in range(CV)
    }
    theirs = grid.best_estimator_[:-1].transform(_for_sklearn(new))
    return Compared(
        search=search,
        best=as_sqlearn(grid.best_params_),
        scores={(s, k): v for s, k, v in search.results_.fetchall()},
        sk_scores=sk_scores,
        predicted=predicted["prediction"].to_numpy(),
        sk_predicted=grid.predict(_for_sklearn(new)),
        prepared=ours,
        sk_prepared=theirs.rename(columns=lambda c: c.replace(" ", "*")),
    )


def _case(formula: str, rows: int, **fields: object) -> dict:
    """The fields every case of the script shares."""
    head = {
        "step": "preprocessing script",
        "formula": formula,
        "dataset": "generated",
        "rows": rows,
        "type": "DOUBLE",
    }
    return head | fields


def _column_case(name: str, ours: pd.Series, theirs: pd.Series) -> dict:
    """One prepared column, measured as the slice's are."""
    a = ours.to_numpy(dtype=float)
    b = theirs.to_numpy(dtype=float)
    diff = np.abs(a - b)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(diff == 0, 0.0, diff / np.abs(b))
    distance = math.ceil(float(diff.max()) / 2**-52)
    worst = int(np.argmax(diff))
    out = _cases._head(
        **_case(f"prepared column {name}", len(a), reference="sqlearn", bound=BOUND)
    )
    out["note"] = NOTE
    return out | {
        "compared_with": "scikit-learn",
        "value": float(a[worst]),
        "canonical": None,
        "abs_error": float(diff.max()),
        "rel_error": float(rel.max()),
        "ulps": distance,
        "ulps_at_value": max(
            _cases.ulps(float(x), float(y)) for x, y in zip(a, b, strict=True)
        ),
        "result": "pass" if distance <= BOUND else "fail",
    }


def cases() -> list[dict]:
    """Return the script's cases: scores, best setting, predictions, columns."""
    got = compare()
    mismatched = [k for k in got.sk_scores if got.scores.get(k) != got.sk_scores[k]]
    out = [
        _cases.exact_case(
            **_case("score of each setting on each fold", ROWS),
            mismatches=len(mismatched) + len(set(got.scores) - set(got.sk_scores)),
            cells=len(got.sk_scores),
            compared_with=COMPARED_WITH,
            note="accuracy per setting and outer fold, compared exactly",
        ),
        _cases.exact_case(
            **_case("best setting", ROWS),
            mismatches=int(got.search.best_params_ != got.best),
            cells=1,
            compared_with=COMPARED_WITH,
            note=f"sqlearn chose {json.dumps(got.search.best_params_, default=repr)}",
        ),
        _cases.exact_case(
            **_case("predictions on new data", NEW_ROWS),
            mismatches=int((got.predicted != got.sk_predicted).sum()),
            cells=NEW_ROWS,
            compared_with=COMPARED_WITH,
            note="the best pipeline, trained on every training row",
        ),
    ]
    theirs = got.sk_prepared
    for name in theirs.columns:
        if name not in got.prepared.columns:
            out.append(
                _cases.skipped(
                    **_case(f"prepared column {name}", NEW_ROWS),
                    reference="sqlearn",
                    result="fail",
                    note=f"sqlearn has no column {name!r}",
                    bound=BOUND,
                )
            )
            continue
        out.append(_column_case(name, got.prepared[name], theirs[name]))
    extra = sorted(set(got.prepared.columns) - set(theirs.columns))
    if extra:
        out.append(
            _cases.skipped(
                **_case("columns", NEW_ROWS),
                reference="sqlearn",
                result="fail",
                note=f"sqlearn has columns scikit-learn has not: {extra}",
                bound=BOUND,
            )
        )
    return out

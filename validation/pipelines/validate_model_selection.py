"""Validate the model-selection spec's search (§2, §9) against scikit-learn.

The script itself (``run_the_script``) runs as the spec writes it, scaled
down: CatBoost through ``feed="pandas"``, Optuna over two ranges, stratified
folds, the log loss, the prepared folds kept in a DuckDB file, then a
streamed ``SGDClassifier``. One line differs from §2: the streamed pipeline
one-hot encodes the text columns, which §2's data has for CatBoost and the
stream refuses (spec §3.1: it hands numbers only). Its test is
``tests/src/sqlearn/test_model_selection_script.py``.

The cases compare what a search computes with scikit-learn's, handed
sqlearn's own folds (``PredefinedSplit``):

- a grid and a random search of the §2 preparation (``impute.median``,
  ``scale.standard``) before a logistic regression, scored by the log loss
  and the accuracy: each setting's score on each fold, and the best
  setting. For random, scikit-learn is given the settings sqlearn drew, as
  a fixed list: sqlearn does not copy scikit-learn's sampler (spec §9).
  CatBoost is not compared: it learns in the order it is given the rows,
  and a fold's rows reach each side in a different order.
- each fold scheme against its scikit-learn twin, on the property that
  defines it, since the rows are dealt differently: class balance
  (``StratifiedKFold``), groups kept together (``GroupKFold``), and the
  order in time kept (``TimeSeriesSplit``, whose folds sqlearn's equal row
  for row when no two rows share a time).
- the same seeds giving the same ``results_``, byte for byte, for the
  random and the Optuna methods.
"""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.model_selection import (
    GridSearchCV,
    GroupKFold,
    PredefinedSplit,
    StratifiedKFold,
    TimeSeriesSplit,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.metrics import Metric
from sqlearn.model_selection import Folds, Grid, Search
from validation import _cases

ROWS = 5_000
"""The rows each comparison searches."""

FOLDS = 5
"""The folds of every scheme compared."""

CITIES = ("kyiv", "lima", "oslo", "rome")
PLANS = ("basic", "plus", "pro")

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst difference measured between sqlearn's score and
# scikit-learn's, in ULPs at the score, at least 1. Loosening it needs a
# written reason here, never a quiet edit. First measured (2026-11-08): 1 ULP,
# in a fold's log loss (sqlearn sums it in SQL, scikit-learn with numpy, and
# each fits the model on the fold's rows in its own order); the accuracies
# and the best settings agree exactly.
BOUND = 1

COMPARED_WITH = (
    "scikit-learn GridSearchCV(Pipeline(SimpleImputer(median), StandardScaler, "
    "LogisticRegression), cv=PredefinedSplit(sqlearn's folds))"
)


def customers(rows: int, seed: int = _cases.SEED) -> pd.DataFrame:
    """Return `rows` rows of the script's data, drawn from `seed`.

    Age and income with gaps, a city and a plan (no gaps: CatBoost refuses a
    missing category), and whether the customer churned, which depends on
    all four.
    """
    rng = np.random.default_rng(seed)
    age = rng.normal(40.0, 12.0, rows)
    income = rng.lognormal(10.5, 0.5, rows)
    city = rng.choice(np.array(CITIES, dtype=object), rows)
    plan = rng.choice(np.array(PLANS, dtype=object), rows, p=[0.5, 0.3, 0.2])
    signal = (
        0.04 * (age - 40.0)
        - 0.8 * (np.log(income) - 10.5) / 0.5
        + 0.9 * (plan == "basic")
        + 0.5 * (city == "oslo")
        + rng.normal(0.0, 1.0, rows)
    )
    return pd.DataFrame(
        {
            "age": np.where(rng.random(rows) < 0.1, np.nan, age),
            "income": np.where(rng.random(rows) < 0.05, np.nan, income),
            "city": city,
            "plan": plan,
            "churned": (signal > 0.4).astype(np.int64),
        }
    )


def write_data(root: Path, rows: int) -> Path:
    """Write the script's files under `root` and return `root`.

    ``data/train/0.parquet`` and ``1.parquet`` hold `rows` rows between
    them; ``data/new/0.parquet`` holds a fifth as many more, without the
    target.
    """
    (root / "data" / "train").mkdir(parents=True)
    (root / "data" / "new").mkdir(parents=True)
    new = rows // 5
    every = customers(rows + new)
    half = rows // 2
    parts = {
        root / "data" / "train" / "0.parquet": every.iloc[:half],
        root / "data" / "train" / "1.parquet": every.iloc[half:rows],
        root / "data" / "new" / "0.parquet": every.iloc[rows:].drop(columns="churned"),
    }
    for path, part in parts.items():
        duckdb.from_df(part.reset_index(drop=True)).write_parquet(str(path))
    return root


def run_the_script(trials: int = 40, **catboost: object) -> tuple[Search, sq.Pipeline]:
    """Run spec §2's script from the current directory; return what it trains.

    `trials` and `catboost` (more settings for ``CatBoostClassifier``, such
    as ``iterations``) scale it down. CatBoost is told which columns are
    text (``cat_features``), as it would be without sqlearn, and writes no
    files of its own (``allow_writing_files=False``).
    """
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.scale.standard(),
            sq.Model(
                CatBoostClassifier(
                    verbose=0,
                    cat_features=["city", "plan"],
                    allow_writing_files=False,
                    **catboost,
                ),
                feed="pandas",
            ),  # text reaches it as categories
        ]
    )

    search = sq.search(
        pipe,
        params={
            "model__depth": sq.search.range(4, 10),
            "model__learning_rate": sq.search.range(0.01, 0.3, log=True),
        },
        method=sq.search.optuna(trials=trials, seed=0),
        folds=sq.folds.stratified(5, seed=0),
        metric=sq.metrics.log_loss,
        keep_prepared="churn.duckdb",
    )
    search.train("data/train/*.parquet", target="churned")
    search.predict("data/new/*.parquet", out=sq.out.parquet("scored.parquet"))

    # A model that learns in pieces trains on data larger than memory.
    stream = sq.Pipeline(
        [
            sq.impute.median(),
            sq.scale.standard(),
            sq.encode.onehot(),  # not in §2: the stream takes numbers only
            sq.Model(
                SGDClassifier(loss="log_loss"), feed="stream", rows=1_000
            ),  # §2 says 100,000 rows: here a fold is smaller than that
        ]
    )
    stream.train("data/train/*.parquet", target="churned")
    return search, stream


def numbers(rows: int = ROWS) -> pd.DataFrame:
    """Return the script's numeric columns and target: what a numpy model takes."""
    return customers(rows).drop(columns=["city", "plan"])


def sqlearn_pipe() -> sq.Pipeline:
    """Return §2's preparation before a logistic regression."""
    return sq.Pipeline(
        [sq.impute.median(), sq.scale.standard(), ("model", LogisticRegression())]
    )


def sklearn_pipe() -> Pipeline:
    """Return scikit-learn's twin of `sqlearn_pipe`."""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression()),
        ]
    )


def assigned(scheme: Folds, data: pd.DataFrame, target: str) -> pd.DataFrame:
    """Return `data` as `scheme` numbers it, with a training and held flag per fold.

    The flags ``train_k`` and ``held_k`` are the scheme's own predicates,
    computed in DuckDB beside the rows, so they line up with them whatever
    order the numbering returns the rows in.
    """
    name = "__fold"
    rel = scheme.numbered(connection().from_df(data), name, target)
    flags = []
    for k in range(scheme.splits):
        flags += [
            scheme.training(name, k).alias(f"train_{k}"),
            scheme.held(name, k).alias(f"held_{k}"),
        ]
    columns = [duckdb.ColumnExpression(c) for c in data.columns]
    return rel.project(*columns, *flags).df()


def held_fold(flags: pd.DataFrame, splits: int) -> np.ndarray:
    """Return each row's held-out fold, for ``PredefinedSplit``."""
    held = np.column_stack([flags[f"held_{k}"].to_numpy() for k in range(splits)])
    assert (held.sum(axis=1) == 1).all(), "every row is held out once"
    return held.argmax(axis=1)


def _settings(search: Search) -> list[dict]:
    """Return the settings a search tried, in its order, from ``results_``."""
    texts = [s for (s,) in search.results_.project("setting").distinct().fetchall()]
    order = [s for (s,) in search.results_.project("setting").fetchall()]
    return [json.loads(s) for s in sorted(texts, key=order.index)]


def compare_search(method: object, metric: Metric, scoring: str) -> dict:
    """Run one search on each side, on sqlearn's stratified folds; return both."""
    data = numbers()
    scheme = sq.folds.stratified(FOLDS, seed=0)
    params = (
        {"model__C": [0.01, 0.1, 1.0, 10.0]}
        if isinstance(method, Grid)
        else {"model__C": sq.search.range(0.001, 100.0, log=True)}
    )
    ours = sq.search(
        sqlearn_pipe(), params=params, metric=metric, method=method, folds=scheme
    ).train(data, target="churned")
    tried = _settings(ours)
    flags = assigned(scheme, data, "churned")
    x = flags[["age", "income"]]
    sk = GridSearchCV(
        sklearn_pipe(),
        [{"model__C": [s["model__C"]]} for s in tried],
        scoring=scoring,
        cv=PredefinedSplit(held_fold(flags, FOLDS)),
    ).fit(x, flags["churned"].to_numpy())
    sign = -1.0 if scoring.startswith("neg_") else 1.0
    theirs = {
        (json.dumps(p), k): sign * float(sk.cv_results_[f"split{k}_test_score"][i])
        for i, p in enumerate(sk.cv_results_["params"])
        for k in range(FOLDS)
    }
    scores = {(s, k): v for s, k, v in ours.results_.fetchall()}
    return {
        "scores": scores,
        "sk_scores": theirs,
        "best": ours.best_params_,
        "sk_best": sk.best_params_,
    }


def _search_cases(name: str, method: object, metric: object, scoring: str) -> list:
    got = compare_search(method, metric, scoring)
    distance, worst, missing = 0, 0.0, 0
    for key, theirs in got["sk_scores"].items():
        ours = got["scores"].get(key)
        if ours is None:
            missing += 1
            continue
        distance = max(distance, _cases.ulps(ours, theirs))
        worst = max(worst, abs(ours - theirs))
    head = {
        "step": "search",
        "formula": f"{name} search, {metric.name}: score of each setting on each fold",
        "dataset": "generated",
        "rows": ROWS,
        "type": "DOUBLE",
        "reference": "sqlearn",
        "bound": BOUND,
    }
    case = _cases._head(
        note=(
            "ULPs at the score, worst over every setting and fold; "
            f"{missing} cells missing from sqlearn's results"
        ),
        **head,
    )
    worst_ok = distance <= BOUND and missing == 0
    case |= {
        "compared_with": COMPARED_WITH,
        "value": None,
        "canonical": None,
        "abs_error": worst,
        "rel_error": None,
        "ulps": distance,
        "result": "pass" if worst_ok else "fail",
    }
    best = _cases.exact_case(
        step="search",
        formula=f"{name} search, {metric.name}: best setting",
        dataset="generated",
        rows=ROWS,
        type="DOUBLE",
        mismatches=int(got["best"] != got["sk_best"]),
        cells=1,
        compared_with=COMPARED_WITH,
        note=f"sqlearn chose {json.dumps(got['best'])}",
    )
    return [case, best]


def fold_data(rows: int = ROWS, ties: bool = False) -> pd.DataFrame:
    """Return rows for the fold schemes: a customer, a day, a three-class target.

    A customer has about four rows; the classes are unbalanced (60%, 30%,
    10%). The days are distinct and shuffled, or with `ties`, about ten rows
    share each day.
    """
    rng = np.random.default_rng(_cases.SEED + 1)
    day = rng.permutation(rows) // 10 if ties else rng.permutation(rows)
    return pd.DataFrame(
        {
            "x": rng.normal(size=rows),
            "customer": rng.integers(0, rows // 4, rows),
            "day": day.astype(np.int64),
            "label": rng.choice(np.arange(3), rows, p=[0.6, 0.3, 0.1]),
        }
    )


def _fold_case(
    formula: str, rows: int, mismatches: int, cells: int, twin: str, note: str
) -> dict:
    return _cases.exact_case(
        step="folds",
        formula=formula,
        dataset="generated",
        rows=rows,
        type="BIGINT",
        mismatches=mismatches,
        cells=cells,
        compared_with=twin,
        note=note,
    )


def _imbalance(held: list[np.ndarray], labels: np.ndarray) -> float:
    """Return the worst gap, in rows, between a fold's class count and its share."""
    worst = 0.0
    for rows in held:
        for c in np.unique(labels):
            want = (labels == c).sum() * len(rows) / len(labels)
            worst = max(worst, abs(float((labels[rows] == c).sum()) - want))
    return worst


def _split_copies(held: list[np.ndarray], copy_of: np.ndarray) -> int:
    """Return how many repeated rows have copies held out in more than one fold."""
    fold_of: dict[int, set[int]] = {}
    for k, rows in enumerate(held):
        for c in np.unique(copy_of[rows]):
            fold_of.setdefault(int(c), set()).add(k)
    repeated = set(np.flatnonzero(np.bincount(copy_of) > 1).tolist())
    return sum(len(f) > 1 for c, f in fold_of.items() if c in repeated)


def stratified_duplicates_case() -> dict:
    """Repeated rows: every copy of a row is held out in the same fold."""
    data = fold_data()
    rng = np.random.default_rng(_cases.SEED + 2)
    picks = rng.integers(0, len(data), len(data))
    repeated = data.iloc[picks].reset_index(drop=True)
    repeated["copy_of"] = picks
    flags = assigned(sq.folds.stratified(FOLDS, seed=0), repeated, "label")
    copy_of = flags["copy_of"].to_numpy()
    ours = [np.flatnonzero(flags[f"held_{k}"]) for k in range(FOLDS)]
    twin = StratifiedKFold(FOLDS, shuffle=True, random_state=0)
    theirs = [t for _, t in twin.split(repeated, repeated["label"])]
    many = int((np.bincount(picks) > 1).sum())
    return _fold_case(
        "stratified: every copy of a repeated row held out in one fold",
        len(repeated),
        _split_copies(ours, copy_of),
        many,
        "scikit-learn StratifiedKFold(5, shuffle=True)",
        f"{many} rows repeat (drawn with replacement); scikit-learn holds out "
        f"copies of {_split_copies(theirs, picks)} of them in more than one fold",
    )


def stratified_cases() -> list[dict]:
    """Class balance: each fold holds each class's share, to within a row."""
    data = fold_data()
    flags = assigned(sq.folds.stratified(FOLDS, seed=0), data, "label")
    labels = flags["label"].to_numpy()
    ours = [np.flatnonzero(flags[f"held_{k}"]) for k in range(FOLDS)]
    twin = StratifiedKFold(FOLDS, shuffle=True, random_state=0)
    theirs = [t for _, t in twin.split(data, data["label"])]
    a = _imbalance(ours, labels)
    b = _imbalance(theirs, data["label"].to_numpy())
    held = np.column_stack([flags[f"held_{k}"].to_numpy() for k in range(FOLDS)])
    once = int((held.sum(axis=1) != 1).sum())
    return [
        _fold_case(
            "stratified: each class's share in every held-out fold",
            len(data),
            int(a > max(1.0, b)),
            1,
            "scikit-learn StratifiedKFold(5, shuffle=True)",
            f"worst gap from a class's share: sqlearn {a:.2f} rows, scikit-learn "
            f"{b:.2f} rows; passes when sqlearn's is within a row or scikit-learn's",
        ),
        _fold_case(
            "stratified: every row held out once",
            len(data),
            once,
            len(data),
            "scikit-learn StratifiedKFold(5, shuffle=True)",
            "each row in exactly one held-out fold",
        ),
        stratified_duplicates_case(),
    ]


def _split_groups(held: list[np.ndarray], groups: np.ndarray) -> int:
    """Return how many groups have rows held out in more than one fold."""
    fold_of: dict[int, set[int]] = {}
    for k, rows in enumerate(held):
        for g in np.unique(groups[rows]):
            fold_of.setdefault(int(g), set()).add(k)
    return sum(len(f) > 1 for f in fold_of.values())


def group_cases() -> list[dict]:
    """Groups kept together: no customer's rows in two held-out folds."""
    data = fold_data()
    flags = assigned(sq.folds.group("customer", FOLDS, seed=0), data, None)
    groups = flags["customer"].to_numpy()
    ours = [np.flatnonzero(flags[f"held_{k}"]) for k in range(FOLDS)]
    theirs = [t for _, t in GroupKFold(FOLDS).split(data, groups=data["customer"])]
    trained_and_held = sum(
        len(
            set(groups[flags[f"train_{k}"].to_numpy()])
            & set(groups[flags[f"held_{k}"].to_numpy()])
        )
        for k in range(FOLDS)
    )
    sizes = [len(r) for r in ours]
    sk_sizes = [len(r) for r in theirs]
    return [
        _fold_case(
            "group: no group held out in two folds",
            len(data),
            _split_groups(ours, groups),
            len(np.unique(groups)),
            "scikit-learn GroupKFold(5)",
            f"scikit-learn splits {_split_groups(theirs, data['customer'].to_numpy())}"
            f" groups; held-out sizes: sqlearn {sizes}, scikit-learn {sk_sizes} "
            "(sqlearn deals the groups by a hash, scikit-learn balances sizes)",
        ),
        _fold_case(
            "group: no group both trained on and held out in a fold",
            len(data),
            trained_and_held,
            len(np.unique(groups)) * FOLDS,
            "scikit-learn GroupKFold(5)",
            "the groups of each fold's training rows and held-out rows are apart",
        ),
    ]


def _days(flags: pd.DataFrame, prefix: str, k: int) -> list[int]:
    return sorted(flags.loc[flags[f"{prefix}_{k}"].to_numpy(), "day"].tolist())


def time_cases() -> list[dict]:
    """Order kept: each fold learns from the past only, as TimeSeriesSplit does."""
    out = []
    for gap in (0, 3):
        data = fold_data()
        flags = assigned(sq.folds.time("day", FOLDS, gap=gap), data, None)
        by_day = data.sort_values("day").reset_index(drop=True)
        twin = TimeSeriesSplit(FOLDS, gap=gap)
        mismatches = 0
        for k, (train, test) in enumerate(twin.split(by_day)):
            want_train = sorted(by_day["day"].to_numpy()[train].tolist())
            want_test = sorted(by_day["day"].to_numpy()[test].tolist())
            mismatches += int(_days(flags, "train", k) != want_train)
            mismatches += int(_days(flags, "held", k) != want_test)
        out.append(
            _fold_case(
                f"time, gap={gap}: each fold's rows, by day",
                len(data),
                mismatches,
                2 * FOLDS,
                f"scikit-learn TimeSeriesSplit(5, gap={gap}) on the rows sorted by day",
                "distinct days: the training and held-out days of every fold "
                "equal scikit-learn's",
            )
        )
    data = fold_data(ties=True)
    flags = assigned(sq.folds.time("day", FOLDS), data, None)
    late = sum(
        int(max(_days(flags, "train", k)) >= min(_days(flags, "held", k)))
        for k in range(FOLDS)
    )
    out.append(
        _fold_case(
            "time, shared days: every training day before every held-out day",
            len(data),
            late,
            FOLDS,
            "scikit-learn TimeSeriesSplit(5)",
            "about ten rows a day: a fold's boundary moves to the end of its "
            "day, so no day is both trained on and held out (TimeSeriesSplit "
            "cuts by position and may split a day)",
        )
    )
    return out


def results_bytes(method: object) -> bytes:
    """Return a fresh search's ``results_``, as bytes, for `method`."""
    STORE.clear()
    search = sq.search(
        sqlearn_pipe(),
        params={"model__C": sq.search.range(0.001, 100.0, log=True)},
        method=method,
        folds=sq.folds.stratified(FOLDS, seed=0),
        metric=sq.metrics.log_loss,
    ).train(numbers(), target="churned")
    rows = search.results_.order("setting, fold").fetchall()
    return json.dumps([list(r) for r in rows]).encode() + repr(rows).encode()


def repeat_cases() -> list[dict]:
    """The same seed gives the same ``results_``, byte for byte."""
    out = []
    for name, make in (
        ("random", lambda: sq.search.random(trials=6, seed=3)),
        ("optuna", lambda: sq.search.optuna(trials=6, seed=3)),
    ):
        first, second = results_bytes(make()), results_bytes(make())
        out.append(
            _cases.exact_case(
                step="search",
                formula=f"{name} search: results_ for one seed, run twice",
                dataset="generated",
                rows=ROWS,
                type="DOUBLE",
                mismatches=int(first != second),
                cells=1,
                compared_with="sqlearn",
                note=f"{len(first)} bytes compared",
            )
        )
    return out


def cases() -> list[dict]:
    """Return the search's and the fold schemes' cases."""
    out = []
    for name, method in (
        ("grid", sq.search.grid()),
        ("random", sq.search.random(trials=8, seed=0)),
    ):
        out += _search_cases(name, method, sq.metrics.log_loss, "neg_log_loss")
        out += _search_cases(name, method, sq.metrics.accuracy, "accuracy")
    out += stratified_cases() + group_cases() + time_cases() + repeat_cases()
    return out

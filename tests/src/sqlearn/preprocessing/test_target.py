"""Tests of TargetEncoder: learned on the target, cross-fitted in train."""

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.preprocessing import TargetEncoder as SkTargetEncoder

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.preprocessing.target import TargetEncoder

PLANS = ("basic", "pro", "team", None)


def sample(rows=300, seed=0, continuous=False, nulls=True):
    """Return a plan (with NULLs), a number and a target, binary or continuous."""
    rng = np.random.default_rng(seed)
    plan = rng.choice(np.array(PLANS if nulls else PLANS[:-1], dtype=object), rows)
    shift = np.select([plan == "basic", plan == "pro"], [0.2, 0.5], 0.8)
    if continuous:
        y = rng.normal(10 * shift, 1.0, rows)
    else:
        y = (rng.random(rows) < shift).astype(int)
    return pd.DataFrame({"plan": list(plan), "x": rng.normal(0, 1, rows), "y": y})


def as_sklearn(frame, column="plan"):
    """Return one column for scikit-learn: an object array, NULL as NaN."""
    return np.array(
        [[math.nan if v is None else v] for v in frame[column]], dtype=object
    )


def inner_folds(frame, target="y", cv=5, seed=0):
    """Return each row's inner fold, as sqlearn deals it: by its position."""
    return position_folds(len(frame), cv, seed)


def position_folds(rows, cv=5, seed=0):
    """Return KFold(cv, seed)'s fold of positions 1 to `rows`."""
    positions = connection().sql(f"SELECT range + 1 AS p FROM range({rows})")
    fold = sq.folds.kfold(cv, seed).expression("d")
    return np.array(
        [r[0] for r in positions.set_alias("d").project(fold).fetchall()],
    )


def splits(folds, cv=5):
    """Return the folds as scikit-learn's splits: (train, test) per fold."""
    return [
        (np.flatnonzero(folds != k), np.flatnonzero(folds == k))
        for k in range(cv)
        if (folds == k).any()
    ]


class Recorder(BaseEstimator, ClassifierMixin):
    """A model that keeps what it was trained on."""

    seen: list[np.ndarray] = []  # noqa: RUF012  (shared across clones on purpose)
    predicted: list[np.ndarray] = []  # noqa: RUF012

    def fit(self, x, y):
        """Keep the features."""
        Recorder.seen.append(np.array(x))
        self.classes_ = np.unique(y)
        return self

    def predict(self, x):
        """Keep the features; predict the first class."""
        Recorder.predicted.append(np.array(x))
        return np.full(len(x), self.classes_[0])


@pytest.fixture(autouse=True)
def _forget():
    Recorder.seen.clear()
    Recorder.predicted.clear()


def test_learn_then_apply_matches_fit_then_transform():
    """learn(target=) then apply is scikit-learn's fit then transform."""
    frame = sample()
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    got = pipe.apply(frame.drop(columns="y"), out="pandas")
    theirs = SkTargetEncoder(target_type="binary").fit(as_sklearn(frame), frame["y"])
    assert list(got.columns) == ["plan", "x"]
    assert got["plan"].to_numpy() == pytest.approx(
        theirs.transform(as_sklearn(frame))[:, 0], rel=1e-12
    )
    assert pipe["target"].target_mean_ == {"plan": pytest.approx(frame["y"].mean())}
    assert pipe.columns_out_ == ["plan", "x"]


def test_train_cross_fits_like_fit_transform():
    """train's prepared rows are fit_transform's, given sqlearn's inner folds."""
    frame = sample()
    pipe = sq.Pipeline([sq.encode.target("plan"), Recorder()])
    pipe.train(frame, target="y")
    [x] = Recorder.seen
    theirs = SkTargetEncoder(target_type="binary", cv=splits(inner_folds(frame)))
    expected = theirs.fit_transform(as_sklearn(frame), frame["y"])[:, 0]
    assert x[:, 0] == pytest.approx(expected, rel=1e-12)
    assert x[:, 1] == pytest.approx(frame["x"].to_numpy())


def test_train_cross_fits_a_continuous_target():
    """A continuous target is found as such and cross-fitted the same way."""
    frame = sample(continuous=True)
    pipe = sq.Pipeline([sq.encode.target("plan"), Recorder()])
    pipe.train(frame, target="y")
    theirs = SkTargetEncoder(target_type="continuous", cv=splits(inner_folds(frame)))
    expected = theirs.fit_transform(as_sklearn(frame), frame["y"])[:, 0]
    assert Recorder.seen[0][:, 0] == pytest.approx(expected, rel=1e-9)
    assert pipe["target"].target_type_ == {"plan": "continuous"}


def test_a_scaler_after_target_learns_from_cross_fitted_values():
    """The scaler learns the cross-fitted values, as scikit-learn's Pipeline.fit."""
    frame = sample()
    pipe = sq.Pipeline(
        [sq.encode.target("plan"), sq.scale.standard("plan"), Recorder()]
    )
    pipe.train(frame, target="y")
    theirs = SkTargetEncoder(target_type="binary", cv=splits(inner_folds(frame)))
    crossed = theirs.fit_transform(as_sklearn(frame), frame["y"])[:, 0]
    assert pipe["standard"].center_["plan"] == pytest.approx(crossed.mean(), rel=1e-12)
    assert pipe["standard"].scale_["plan"] == pytest.approx(crossed.std(), rel=1e-9)
    assert len(pipe.runs_) == 2


def test_predict_uses_the_values_learned_on_all_rows():
    """predict encodes with what was learned on every row, no cross-fitting."""
    frame = sample()
    pipe = sq.Pipeline([sq.encode.target("plan"), Recorder()])
    pipe.train(frame, target="y").predict(frame)
    [x] = Recorder.predicted
    theirs = SkTargetEncoder(target_type="binary").fit(as_sklearn(frame), frame["y"])
    assert x[:, 0] == pytest.approx(theirs.transform(as_sklearn(frame))[:, 0])


def test_the_store_entry_holds_all_rows_and_each_fold():
    """The entry keeps the values learned on all rows and each fold's complement."""
    frame = sample()
    sq.Pipeline([sq.encode.target("plan", cv=3), Recorder()]).train(frame, target="y")
    [entry] = [e for e in STORE._entries.values() if e.folds]
    assert set(entry.folds) == {"0", "1", "2"}
    assert entry.values["target_mean"]["plan"] == pytest.approx(frame["y"].mean())


def test_learn_without_target_is_refused():
    """A step that learns from the target needs target= at learn."""
    frame = sample()
    with pytest.raises(sq.errors.StepError, match=r"target \(step 1\).*target="):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame.drop(columns="y"))


def test_target_unseen_and_null_get_the_overall_mean():
    """A category first met at apply, and NULL unseen at learn, get the mean."""
    frame = sample(nulls=False)
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    new = pd.DataFrame({"plan": ["gold", None, "basic"], "x": [0.0, 0.0, 0.0]})
    got = pipe.apply(new, out="pandas")["plan"].to_numpy()
    mean = frame["y"].mean()
    theirs = SkTargetEncoder(target_type="binary").fit(as_sklearn(frame), frame["y"])
    assert got[:2] == pytest.approx([mean, mean], rel=1e-12)
    assert got == pytest.approx(theirs.transform(as_sklearn(new))[:, 0], rel=1e-12)


def test_null_seen_at_learn_is_a_category():
    """NULL seen at learn gets its own encoding, as scikit-learn's missing value."""
    frame = sample()
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    got = pipe.apply(frame, out="pandas")["plan"].to_numpy()
    theirs = SkTargetEncoder(target_type="binary").fit(as_sklearn(frame), frame["y"])
    nulls = frame["plan"].isna().to_numpy()
    assert got[nulls] == pytest.approx(
        theirs.transform(as_sklearn(frame))[nulls, 0], rel=1e-12
    )
    assert pipe["target"].null_["plan"] != pytest.approx(frame["y"].mean())


def test_a_number_for_smooth_is_the_weighted_mean():
    """smooth=s gives (n * mean + s * m) / (n + s), as scikit-learn."""
    frame = sample()
    pipe = sq.Pipeline([sq.encode.target("plan", smooth=10.0)])
    pipe.learn(frame, target="y")
    got = pipe.apply(frame, out="pandas")["plan"].to_numpy()
    theirs = SkTargetEncoder(target_type="binary", smooth=10.0)
    theirs.fit(as_sklearn(frame), frame["y"])
    assert got == pytest.approx(theirs.transform(as_sklearn(frame))[:, 0], rel=1e-12)


def test_a_binary_target_of_two_numbers_or_a_boolean():
    """Two numbers are label-encoded in sorted order; a boolean is too."""
    frame = sample()
    expected = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    want = expected.apply(frame, out="pandas")["plan"].to_numpy()
    for y in (frame["y"] * 5 + 3, frame["y"].astype(bool)):
        other = frame.assign(y=y)
        pipe = sq.Pipeline([sq.encode.target("plan")]).learn(other, target="y")
        assert pipe.apply(other, out="pandas")["plan"].to_numpy() == pytest.approx(
            want, rel=1e-12
        )


def test_a_multiclass_target_is_refused():
    """Three classes are multiclass, which comes later."""
    frame = sample().assign(y=lambda f: np.arange(len(f)) % 3)
    with pytest.raises(sq.errors.StepError, match="multiclass"):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    pipe = sq.Pipeline([sq.encode.target("plan", target_type="continuous")])
    assert pipe.learn(frame, target="y")["target"].target_type_ == {
        "plan": "continuous"
    }


def test_a_text_target_is_refused():
    """A text target is refused with the fix: map it to numbers first."""
    frame = sample().assign(y=lambda f: np.where(f["y"] == 1, "yes", "no"))
    with pytest.raises(sq.errors.StepError, match="text"):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")


def test_settings_are_checked():
    """Bad settings are refused when the step is built."""
    with pytest.raises(sq.errors.SqlearnError, match="cv"):
        sq.encode.target("plan", cv=1)
    with pytest.raises(sq.errors.SqlearnError, match="smooth"):
        sq.encode.target("plan", smooth=-1.0)
    with pytest.raises(sq.errors.SqlearnError, match="target_type"):
        sq.encode.target("plan", target_type="multiclass")
    with pytest.raises(sq.errors.SqlearnError, match="seed"):
        sq.encode.target("plan", seed=1.5)  # ty: ignore[invalid-argument-type]


def test_encodings_follow_the_formulae():
    """encodings() gives scikit-learn's auto smoothing on hand-made statistics."""
    # fold, category, count, sum(y), sum(y * y)
    stats = [(0, "a", 2, 1.0, 1.0), (1, "a", 2, 2.0, 2.0), (1, "b", 2, 0.0, 0.0)]
    got = TargetEncoder().encodings(stats, 2)
    y = np.array([1, 0, 1, 1, 0, 0], dtype=float)
    m, v = y.mean(), y.var()
    mu, s2 = 0.75, 0.75 * 0.25
    lam = 4 * v / (4 * v + s2)
    assert got["all"]["a"] == pytest.approx(lam * mu + (1 - lam) * m)
    # fold 0's complement is fold 1 alone: "a" mean 1 with no spread, "b" 0.
    assert got["0"]["a"] == pytest.approx(1.0)
    assert got["0"]["b"] == pytest.approx(0.0)
    # fold 1's complement has no "b": it gets that complement's mean.
    assert got["1"]["b"] == pytest.approx(0.5)


def test_repr_and_shortcut():
    """The repr rebuilds the step; the general form builds the same step."""
    step = sq.encode.target("plan", smooth=2.0, cv=3)
    assert repr(step) == "sq.encode.target(cols='plan', smooth=2.0, cv=3)"
    rebuilt = eval(repr(step), {"sq": sq})
    general = sq.encode("plan", method="target", smooth=2.0, cv=3)
    assert rebuilt.settings() == step.settings() == general.settings()
    assert step.default_name() == "target"


def test_a_missing_target_is_refused():
    """A NULL answer is refused: a category's mean needs every answer."""
    frame = sample().astype({"y": float})
    frame.loc[3, "y"] = None
    with pytest.raises(sq.errors.StepError, match="missing"):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")


def test_binary_given_for_three_values_is_refused():
    """target_type="binary" with three whole values is refused as multiclass."""
    frame = sample().assign(y=lambda f: np.arange(len(f)) % 3)
    with pytest.raises(sq.errors.StepError, match="multiclass"):
        sq.Pipeline([sq.encode.target("plan", target_type="binary")]).learn(
            frame, target="y"
        )


def test_a_constant_target_encodes_every_category_as_its_value():
    """No spread anywhere: every category gets the mean, as scikit-learn."""
    frame = sample().assign(y=1)
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    assert set(pipe.apply(frame, out="pandas")["plan"]) == {0.0}


def test_rows_all_in_one_inner_fold_are_refused():
    """One row: its inner fold's complement is empty, so it is refused."""
    frame = pd.DataFrame({"plan": ["a"], "y": [1]})
    with pytest.raises(sq.errors.StepError, match="inner fold"):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")


def test_a_column_of_nulls_gets_nulls_encoding():
    """With NULL the only category, every row gets NULL's encoding."""
    frame = pd.DataFrame({"plan": [None] * 20, "x": range(20), "y": [0, 1] * 10})
    frame["plan"] = frame["plan"].astype(object)
    pipe = sq.Pipeline([sq.encode.target(cols=["plan"])])
    got = pipe.learn(frame, target="y").apply(frame, out="pandas")["plan"]
    assert set(got) == {0.5}
    assert pipe["target"].categories_ == {"plan": []}


def test_nan_categories_are_one_category():
    """NaN fetched in two folds is one category, as scikit-learn's."""
    nan_a, nan_b = float("nan"), float("nan")
    got = TargetEncoder(smooth=0.0).encodings(
        [(0, nan_a, 1, 1.0, 1.0), (1, nan_b, 1, 0.0, 0.0)], 2
    )
    [(key, value)] = got["all"].items()
    assert isinstance(key, float)
    assert math.isnan(key)
    assert value == pytest.approx(0.5)
    # smooth=0: a category absent from a fold's complement gets its mean.
    stats = [(0, "a", 1, 1.0, 1.0), (1, "b", 2, 1.0, 1.0)]
    assert TargetEncoder(smooth=0.0).encodings(stats, 2)["0"] == {"a": 0.5, "b": 0.5}


def test_learn_without_y_is_refused():
    """Called without the target, learn says it needs one."""
    import duckdb

    with pytest.raises(sq.errors.StepError, match="target"):
        TargetEncoder().learn(duckdb.ColumnExpression("a"))


def test_rows_alike_get_folds_of_their_own():
    """A table of a category alone cross-fits to each category's own values.

    Inner folds are dealt by position, so rows alike are spread over the
    folds and each fold's complement holds every category, as with
    fit_transform given the same folds.
    """
    plans = [f"p{i}" for i in range(8)] * 50
    frame = pd.DataFrame({"plan": plans, "y": [int(p in {"p0", "p1"}) for p in plans]})
    pipe = sq.Pipeline([sq.encode.target("plan"), Recorder()])
    pipe.train(frame, target="y")
    got = Recorder.seen[0][:, 0]
    theirs = SkTargetEncoder(target_type="binary", cv=splits(inner_folds(frame)))
    expected = theirs.fit_transform(as_sklearn(frame), frame["y"])[:, 0]
    assert got == pytest.approx(expected, rel=1e-12)
    ones = np.isin(plans, ["p0", "p1"])
    assert got[ones].min() > 0.9
    assert got[~ones].max() < 0.1


def test_two_large_labels_are_binary_and_exact():
    """{1e9, 1e9 + 1} over many rows is binary, its encodings scikit-learn's."""
    frame = sample(rows=20_000)
    frame["y"] = frame["y"] + 1_000_000_000
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    assert pipe["target"].target_type_ == {"plan": "binary"}
    got = pipe.apply(frame, out="pandas")["plan"].to_numpy()
    theirs = SkTargetEncoder(target_type="binary").fit(as_sklearn(frame), frame["y"])
    assert got == pytest.approx(theirs.transform(as_sklearn(frame))[:, 0], rel=1e-12)


def test_three_large_whole_values_are_multiclass():
    """A third whole value between two large ones is found, exactly."""
    frame = sample(rows=3_000)
    frame["y"] = 10_000_000 + np.arange(len(frame)) % 3
    with pytest.raises(sq.errors.StepError, match="more than two whole values"):
        sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")


def test_binary_given_for_values_not_whole_is_refused_as_such():
    """Three values that are not whole, given as binary, are refused as values."""
    frame = sample().assign(y=lambda f: 0.5 + (np.arange(len(f)) % 3) / 4)
    with pytest.raises(sq.errors.StepError, match="more than two values"):
        sq.Pipeline([sq.encode.target("plan", target_type="binary")]).learn(
            frame, target="y"
        )


def test_a_continuous_target_with_a_large_offset_keeps_its_digits():
    """The statistics are of y - min(y), so an offset of 1e7 costs nothing."""
    frame = sample(continuous=True)
    frame["y"] = frame["y"] + 10_000_000
    pipe = sq.Pipeline([sq.encode.target("plan")]).learn(frame, target="y")
    got = pipe.apply(frame, out="pandas")["plan"].to_numpy()
    theirs = SkTargetEncoder(target_type="continuous").fit(
        as_sklearn(frame), frame["y"]
    )
    assert got == pytest.approx(theirs.transform(as_sklearn(frame))[:, 0], rel=1e-14)


def test_another_target_or_cv_learns_the_step_and_those_after_again():
    """The target's name and cv are in the keys: changing either relearns."""
    frame = sample().assign(z=lambda f: 1 - f["y"])
    steps = lambda cv: [sq.encode.target("plan", cv=cv), sq.scale.standard("plan")]  # noqa: E731
    sq.Pipeline(steps(5)).learn(frame.drop(columns="z"), target="y")
    sq.Pipeline(steps(5)).learn(frame.drop(columns="z"), target="y")
    assert (STORE.learns["target"], STORE.learns["standard"]) == (1, 1)
    sq.Pipeline(steps(5)).learn(frame.drop(columns="y"), target="z")
    assert (STORE.learns["target"], STORE.learns["standard"]) == (2, 2)
    sq.Pipeline(steps(3)).learn(frame.drop(columns="z"), target="y")
    assert (STORE.learns["target"], STORE.learns["standard"]) == (3, 3)


def test_rows_read_in_any_order_are_refused():
    """Without insertion order, positions (and so inner folds) could move."""
    con = connection()
    con.execute("SET preserve_insertion_order = false")
    try:
        with pytest.raises(sq.errors.SqlearnError, match="preserve_insertion_order"):
            sq.Pipeline([sq.encode.target("plan")]).learn(sample(), target="y")
    finally:
        con.execute("SET preserve_insertion_order = true")

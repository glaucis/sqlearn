"""Tests of sq.select.variance against scikit-learn's VarianceThreshold."""

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.errors import SqlearnError, StepError


def data(seed=1, rows=60):
    """Return seeded numeric data: spreads below, around and above 0.5."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "narrow": rng.normal(0, 0.3, rows),
            "constant": np.full(rows, 2.5),
            "wide": rng.uniform(-10, 10, rows),
            "mid": rng.normal(1, 0.8, rows),
            "n": rng.integers(0, 3, rows).astype("int64"),
        },
    )


@pytest.mark.parametrize("threshold", [0.0, 0.5])
def test_variance_keeps_the_columns_scikit_learn_keeps(threshold):
    """The same columns are kept, in their own order, unchanged."""
    frame = data()
    sk = VarianceThreshold(threshold=threshold).fit(frame)
    pipe = sq.Pipeline([sq.select.variance(threshold=threshold)]).learn(frame)
    kept = list(sk.get_feature_names_out())
    assert pipe.columns_out_ == kept
    out = pipe.apply(frame, out="pandas")
    pd.testing.assert_frame_equal(out, frame[kept])


@pytest.mark.parametrize("threshold", [0.0, 0.5])
def test_variances_match_scikit_learn(threshold):
    """variances_ is scikit-learn's: at 0 the smaller of variance and range."""
    frame = data()
    sk = VarianceThreshold(threshold=threshold).fit(frame)
    pipe = sq.Pipeline([sq.select.variance(threshold=threshold)]).learn(frame)
    got = pipe["variance"].variances_
    assert list(got) == list(frame.columns)
    assert list(got.values()) == pytest.approx(list(sk.variances_), rel=1e-12)


def test_a_constant_column_is_dropped_whatever_its_rounding():
    """1,000 rows of 0.1: scikit-learn drops it, and so does sqlearn."""
    frame = pd.DataFrame({"c": np.full(1000, 0.1), "x": np.arange(1000.0)})
    sk = VarianceThreshold().fit(frame)
    pipe = sq.Pipeline([sq.select.variance()]).learn(frame)
    assert pipe.columns_out_ == list(sk.get_feature_names_out()) == ["x"]
    assert pipe["variance"].variances_["c"] == 0.0


def test_variance_ignores_nan_and_null():
    """NaN and NULL are skipped, as nanvar skips NaN; with one, the range is not used.

    numpy's peak to peak is NaN when a value is, so scikit-learn's variances_
    is then the variance alone: 25 for ``a``, not its range 10.
    """
    con = connection()
    con.execute(
        "CREATE OR REPLACE TABLE holes AS SELECT * FROM (VALUES "
        "(0.0, 1.0, 3.0), (10.0, NULL, 3.0), ('NaN'::DOUBLE, 2.0, 3.0), "
        "(0.0, 4.0, 'NaN'::DOUBLE), (10.0, 0.5, 3.0)) t(a, b, c)"
    )
    nan = np.nan
    array = np.array(
        [[0, 1, 3], [10, nan, 3], [nan, 2, 3], [0, 4, nan], [10, 0.5, 3]],
        dtype=float,
    )
    sk = VarianceThreshold().fit(array)
    pipe = sq.Pipeline([sq.select.variance()]).learn("holes")
    got = pipe["variance"].variances_
    assert list(got.values()) == pytest.approx(list(sk.variances_), rel=1e-12)
    kept = [c for c, keep in zip("abc", sk.get_support(), strict=True) if keep]
    assert pipe.columns_out_ == kept


def test_variance_raises_when_no_column_passes():
    """As scikit-learn raises, naming the threshold and the largest variance."""
    frame = data()[["narrow", "constant"]]
    with pytest.raises(ValueError, match="threshold"):
        VarianceThreshold(threshold=5.0).fit(frame)
    with pytest.raises(StepError, match="threshold") as e:
        sq.Pipeline([sq.select.variance(threshold=5.0)]).learn(frame).apply(frame)
    largest = frame["narrow"].var(ddof=0)
    assert f"{largest:.6g}" in str(e.value)
    assert "Fix:" in str(e.value)


@pytest.mark.parametrize("threshold", [0.0, 0.5])
@pytest.mark.parametrize("value", ["inf", "-inf"])
def test_variance_refuses_an_infinite_value(threshold, value):
    """An infinite value is refused at learn, naming the column, as the scores.

    scikit-learn's VarianceThreshold refuses it (its input check); without
    the refusal the variance would be infinite or NaN, keeping the column
    at one threshold and dropping it at another.
    """
    array = np.array([[1.0, 1.0], [float(value), 2.0], [3.0, 5.0]])
    with pytest.raises(ValueError, match="infinity"):
        VarianceThreshold(threshold=threshold).fit(array)
    con = connection()
    con.execute(
        "CREATE OR REPLACE TABLE endless AS SELECT * FROM (VALUES "
        f"(1.0::DOUBLE, 1.0::DOUBLE), ('{value}'::DOUBLE, 2.0), (3.0, 5.0)) t(a, b)"
    )
    step = sq.select.variance(threshold=threshold)
    with pytest.raises(StepError, match="infinite") as e:
        sq.Pipeline([step]).learn("endless")
    assert "'a'" in str(e.value)
    assert "Why:" in str(e.value)
    assert "Fix:" in str(e.value)


def test_variance_refuses_a_negative_threshold():
    """As scikit-learn's parameter check: at the call, not at learn."""
    with pytest.raises(SqlearnError, match="Fix:"):
        sq.select.variance(threshold=-0.1)


def test_variance_refuses_a_text_column():
    """A chosen text column is refused, naming it; the default skips text."""
    frame = data().assign(city="x")
    with pytest.raises(StepError, match="Fix:") as e:
        sq.Pipeline([sq.select.variance("city")]).learn(frame)
    assert "'city'" in str(e.value)
    pipe = sq.Pipeline([sq.select.variance()]).learn(frame)
    assert "city" in pipe.columns_out_


def test_a_search_over_the_threshold_learns_each_fold_once():
    """3 thresholds x 3 folds: 3 learns, plus 1 for the final training.

    The threshold only chooses the output (ADR 0056), so it is not in the key.
    """
    frame = data().assign(y=[0, 1, 1] * 20)
    pipe = sq.Pipeline(
        [("variance", sq.select.variance()), ("model", LogisticRegression())]
    )
    search = sq.search(
        pipe,
        params={"variance__threshold": [0.0, 0.5, 1.0]},
        folds=sq.folds.kfold(3),
    )
    search.train(frame, target="y")
    assert dict(STORE.learns) == {"variance": 4}

"""Tests of PCA's learning: its learned values against scikit-learn's (spec §4)."""

import numpy as np
import pandas as pd
import pytest
from sklearn import decomposition

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import StepError

COLUMNS = ["e", "b", "d", "a", "c"]  # not in order, so position is not name


def correlated(rows=200, seed=0):
    """Return `rows` rows of five correlated columns, each its own scale."""
    rng = np.random.default_rng(seed)
    mixing = rng.normal(size=(5, 5)) * [3.0, 2.0, 1.0, 0.5, 0.25]
    data = rng.normal(size=(rows, 5)) @ mixing + [1.0, -2.0, 5.0, 0.0, 10.0]
    return pd.DataFrame(data, columns=COLUMNS)


def learned(data, **settings):
    """Return the PCA step of a one-step pipeline learned on `data`."""
    pipe = sq.Pipeline([("pca", sq.decompose.pca(**settings))]).learn(data)
    return pipe["pca"]


def sk(frame, n_components=None):
    """Return scikit-learn's PCA fitted on `frame` by the same solver."""
    return decomposition.PCA(
        n_components=n_components, svd_solver="covariance_eigh"
    ).fit(frame.to_numpy())


@pytest.mark.parametrize("n_components", [None, 3])
def test_pca_learns_scikit_learns_components_and_signs(n_components):
    """The components, largest first and sign-chosen, are scikit-learn's."""
    frame = correlated()
    pca = learned(frame, n_components=n_components)
    want = sk(frame, n_components)
    assert pca.n_components_ == want.n_components_
    assert np.array(pca.components_) == pytest.approx(want.components_, rel=1e-10)
    assert all(type(v) is float for row in pca.components_ for v in row)


@pytest.mark.parametrize("n_components", [None, 3, 0.9])
def test_pca_learns_scikit_learns_variances(n_components):
    """The variances, ratios, singular values, noise and means are scikit-learn's."""
    frame = correlated()
    pca = learned(frame, n_components=n_components)
    want = sk(frame, n_components)
    assert pca.n_components_ == want.n_components_
    for name in ["explained_variance_", "explained_variance_ratio_"]:
        assert getattr(pca, name) == pytest.approx(
            getattr(want, name).tolist(), rel=1e-10
        )
    assert pca.singular_values_ == pytest.approx(want.singular_values_, rel=1e-10)
    assert pca.noise_variance_ == pytest.approx(want.noise_variance_, rel=1e-10)
    assert pca.mean_ == pytest.approx(want.mean_.tolist(), rel=1e-10)
    assert pca.n_samples_ == want.n_samples_ == 200
    assert type(pca.n_samples_) is int
    assert type(pca.n_components_) is int
    assert type(pca.noise_variance_) is float


def test_pca_keeps_the_whole_decomposition():
    """What is learned does not depend on n_components: all p components."""
    frame = correlated()
    cut = learned(frame, n_components=2)
    whole = learned(frame)
    assert cut.weights_ == whole.weights_
    assert cut.variance_ == whole.variance_
    assert all(len(cut.weights_[c]) == 5 for c in COLUMNS)
    assert len(cut.components_) == 2


def test_pca_casts_integer_and_decimal_columns():
    """INTEGER, BIGINT and DECIMAL columns give the components of their values."""
    rng = np.random.default_rng(3)
    ints = rng.integers(-50, 50, size=(100, 2))
    cents = rng.integers(-5000, 5000, size=100) / 100
    frame = pd.DataFrame({"i": ints[:, 0], "j": ints[:, 0] + ints[:, 1], "k": cents})
    con = connection()
    con.execute(
        "CREATE OR REPLACE TEMP TABLE typed AS SELECT i::INTEGER AS i, "
        "j::BIGINT AS j, k::DECIMAL(10, 2) AS k FROM frame"
    )
    typed = con.table("typed")
    floats = pd.DataFrame({c: frame[c].astype(float) for c in ["i", "j", "k"]})
    pca = learned(typed)
    want = sk(floats)
    assert np.array(pca.components_) == pytest.approx(want.components_, rel=1e-10)
    assert pca.explained_variance_ == pytest.approx(
        want.explained_variance_.tolist(), rel=1e-10
    )


def nan_table():
    """Return a DuckDB table whose column `a` holds a NaN (not a NULL)."""
    con = connection()
    con.execute(
        "CREATE OR REPLACE TEMP TABLE with_nan AS SELECT * FROM (VALUES "
        "(1.0::DOUBLE, 2.0::DOUBLE), ('nan'::DOUBLE, 1.0::DOUBLE), "
        "(3.0::DOUBLE, 0.5::DOUBLE)) t(a, b)"
    )
    return con.table("with_nan")


def test_pca_refuses_a_missing_value():
    """A NULL or a NaN is refused before any batch, naming the PCA step."""
    gappy = correlated(20)
    gappy.iloc[4, 1] = np.nan  # NULL in DuckDB
    pipe = sq.Pipeline([("scale", sq.scale()), ("reduce", sq.decompose.pca())])
    with pytest.raises(StepError, match=r"sq\.impute") as caught:
        pipe.learn(gappy)
    assert caught.value.step == "reduce"
    assert caught.value.position == 2
    assert str(caught.value).startswith("reduce (step 2) ")
    assert "'b'" in str(caught.value)
    with pytest.raises(StepError, match=r"sq\.impute") as caught:
        sq.Pipeline([("pca", sq.decompose.pca())]).learn(nan_table())
    assert caught.value.step == "pca"
    assert caught.value.position == 1
    assert "'a'" in str(caught.value)


def test_pca_refuses_an_infinite_value():
    """An infinite value is refused before any batch, naming the PCA step."""
    frame = correlated(20)
    frame.iloc[2, 3] = np.inf
    with pytest.raises(StepError, match="Fix:") as caught:
        learned(frame)
    assert caught.value.step == "pca"
    assert caught.value.position == 1
    assert "infinite" in str(caught.value)


def test_pca_refuses_one_row():
    """One row has no covariance: it is refused, naming the PCA step."""
    with pytest.raises(StepError, match="Fix:") as caught:
        learned(correlated(1))
    assert caught.value.step == "pca"
    assert caught.value.position == 1
    assert "row" in str(caught.value)


def test_pca_refuses_more_components_than_it_can_learn():
    """A whole number above the smaller of rows and columns is refused at learn."""
    with pytest.raises(StepError, match="Fix:") as caught:
        learned(correlated(), n_components=6)
    assert caught.value.step == "pca"
    assert "n_components=6" in str(caught.value)


def test_pca_refuses_a_text_column_by_name():
    """A text column chosen by name is refused, with its Fix."""
    frame = correlated(20).assign(t="x")
    with pytest.raises(StepError, match="Fix:") as caught:
        sq.Pipeline([("pca", sq.decompose.pca("a", "t"))]).learn(frame)
    assert "'t'" in str(caught.value)

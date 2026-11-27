"""Tests of PCA's learning: its learned values against scikit-learn's (spec §4)."""

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn import decomposition

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE
from sqlearn.errors import SqlearnWarning, StepError

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


def sk(frame, n_components=None, whiten=False):
    """Return scikit-learn's PCA fitted on `frame` by the same solver."""
    return decomposition.PCA(
        n_components=n_components, svd_solver="covariance_eigh", whiten=whiten
    ).fit(frame.to_numpy())


def applied(frame, **settings):
    """Return the outputs of PCA learned and applied on `frame`, as an array."""
    pipe = sq.Pipeline([("pca", sq.decompose.pca(**settings))]).learn(frame)
    out = pipe.apply(frame, out="pandas")
    names = [c for c in pipe.columns_out_ if c.startswith("pca")]
    return pipe, out[names].to_numpy()


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
    STORE.clear()  # else the second learn finds the first's values
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
    assert caught.value.position == 1
    assert "n_components=6" in str(caught.value)


def test_pca_refuses_a_text_column_by_name():
    """A text column chosen by name is refused, with its Fix."""
    frame = correlated(20).assign(t="x")
    with pytest.raises(StepError, match="Fix:") as caught:
        sq.Pipeline([("pca", sq.decompose.pca("a", "t"))]).learn(frame)
    assert caught.value.step == "pca"
    assert caught.value.position == 1
    assert "'t'" in str(caught.value)


@pytest.mark.parametrize("n_components", [None, 2, 0])
def test_pca_applies_as_scikit_learn_transforms(n_components):
    """Each output row is scikit-learn's transform of that row."""
    frame = correlated()
    pipe = sq.Pipeline([("pca", sq.decompose.pca(n_components=n_components))])
    pipe.learn(frame.assign(id="x"))
    out = pipe.apply(frame.assign(id="x"), out="pandas")
    want = sk(frame, n_components)
    names = [f"pca{i}" for i in range(want.n_components_)]
    assert pipe.columns_out_ == [*names, "id"]  # after the last input column
    got = out[names].to_numpy()
    assert got.shape == (200, want.n_components_)
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)


def test_pca_names_its_outputs_as_scikit_learn():
    """pca0, pca1, ... after the last input column; a clash is numbered."""
    frame = correlated(50)[["a", "b", "c"]].assign(id=1.5)[["id", "a", "b", "c"]]
    pca = sq.decompose.pca(n_components=2, cols=["a", "b", "c"])
    pipe = sq.Pipeline([("pca", pca)]).learn(frame)
    want = sk(frame[["a", "b", "c"]], 2)
    assert pipe.columns_out_ == ["id", *want.get_feature_names_out()]
    assert pipe.columns_out_ == ["id", "pca0", "pca1"]
    clash = frame.rename(columns={"id": "pca0"})
    pca = sq.decompose.pca(n_components=2, cols=["a", "b", "c"])
    pipe = sq.Pipeline([("pca", pca)]).learn(clash)
    assert pipe.columns_out_ == ["pca0", "pca0_2", "pca1"]
    out = pipe.apply(clash, out="pandas")
    assert out["pca0"].tolist() == [1.5] * 50
    assert out[["pca0_2", "pca1"]].to_numpy() == pytest.approx(
        want.transform(frame[["a", "b", "c"]].to_numpy()), rel=1e-9
    )
    apart = frame[["a", "b"]].assign(id="x")[["a", "id", "b"]]
    pipe = sq.Pipeline([sq.decompose.pca()]).learn(apart)
    assert pipe.columns_out_ == ["id", "pca0", "pca1"]


def test_pca_of_constant_columns_as_scikit_learn():
    """A constant column gives a zero component; all constant, NaN ratios."""
    frame = correlated(50).assign(b=2.5)
    pipe, got = applied(frame)
    want = sk(frame)
    assert pipe["pca"].explained_variance_ratio_ == pytest.approx(
        want.explained_variance_ratio_.tolist(), rel=1e-9, abs=1e-15
    )
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)
    flat = pd.DataFrame({"a": [2.5] * 6, "b": [-1.0] * 6, "c": [0.0] * 6})
    for n_components in [None, 0.5, 2]:
        with pytest.warns(RuntimeWarning, match="invalid value"):
            want = sk(flat, n_components)
        with pytest.warns(SqlearnWarning, match=r"variance.*Why:.*Fix:"):
            pipe, got = applied(flat, n_components=n_components)
        pca = pipe["pca"]
        assert pca.n_components_ == want.n_components_
        assert np.isnan(pca.explained_variance_ratio_).all()
        assert len(pca.explained_variance_ratio_) == want.n_components_
        assert got == pytest.approx(want.transform(flat.to_numpy()))


def test_pca_on_two_rows_as_scikit_learn():
    """Two rows give one component of variance and one of none."""
    frame = pd.DataFrame({"a": [1.0, 4.0], "b": [2.0, -1.0], "c": [0.5, 3.0]})
    pipe, got = applied(frame)
    want = sk(frame)
    assert pipe["pca"].n_components_ == want.n_components_ == 2
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)


def test_pca_whitens_as_scikit_learn():
    """Each output is divided by its component's deviation, floored at eps."""
    frame = correlated()
    for n_components in [None, 3]:
        _, got = applied(frame, n_components=n_components, whiten=True)
        want = sk(frame, n_components, whiten=True)
        assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)
    assert got.std(axis=0, ddof=1) == pytest.approx([1.0] * 3, rel=1e-9)
    flat = frame.assign(b=0.0)
    _, got = applied(flat, whiten=True)
    want = sk(flat, whiten=True).transform(flat.to_numpy())
    assert np.isfinite(got).all()
    assert got[:, :4] == pytest.approx(want[:, :4], rel=1e-9)
    # The last component has no variance: both outputs are rounding divided
    # by the machine epsilon, so they agree only in being near 0.
    assert np.abs(got[:, 4]).max() < 1e-6
    assert np.abs(want[:, 4]).max() < 1e-6


def test_pca_takes_a_fraction_of_the_variance():
    """A fraction met exactly by a cumulative ratio keeps one more component."""
    frame = pd.DataFrame({"a": [1.0, -1.0, 0.0, 0.0], "b": [0.0, 0.0, 1.0, -1.0]})
    pipe, got = applied(frame, n_components=0.5)
    want = sk(frame, 0.5)
    assert want.explained_variance_ratio_.tolist() == [0.5, 0.5]
    assert pipe["pca"].n_components_ == want.n_components_ == 2
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)
    frame = correlated()
    pipe, got = applied(frame, n_components=0.9)
    want = sk(frame, 0.9)
    assert pipe["pca"].n_components_ == want.n_components_
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9)


def test_pca_with_more_columns_than_rows():
    """10 rows of 20 columns keep 10 components, as scikit-learn's."""
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        rng.normal(size=(10, 20)), columns=[f"x{i}" for i in range(20)]
    )
    pipe, got = applied(frame)
    want = sk(frame)
    assert pipe["pca"].n_components_ == want.n_components_ == 10
    # The 10th component has no variance (10 centred rows span 9): its
    # outputs are rounding, compared within an absolute bound.
    assert got == pytest.approx(want.transform(frame.to_numpy()), rel=1e-9, abs=1e-12)


def test_pca_refuses_more_components_than_rows_or_columns():
    """Above the rows (or the columns) is refused at learn, on the step."""
    rng = np.random.default_rng(7)
    wide = pd.DataFrame(rng.normal(size=(10, 20)), columns=[f"x{i}" for i in range(20)])
    with pytest.raises(ValueError, match="n_components=11"):
        sk(wide, 11)
    for frame, n_components in [(wide, 11), (correlated(), 6)]:
        pipe = sq.Pipeline(
            [sq.scale(), ("reduce", sq.decompose.pca(n_components=n_components))]
        )
        with pytest.raises(StepError, match="Fix:") as caught:
            pipe.learn(frame)
        assert caught.value.step == "reduce"
        assert caught.value.position == 2
        assert f"n_components={n_components}" in str(caught.value)


def test_pca_refuses_too_many_components_found_in_the_store():
    """Learned values found in the store are still checked against n_components."""
    frame = correlated()
    learned(frame)
    with pytest.raises(StepError, match=r"n_components=6.*Fix:") as caught:
        learned(frame, n_components=6)
    assert caught.value.step == "pca"
    assert caught.value.position == 1


def test_pca_refuses_a_missing_value_at_apply():
    """Learned on clean rows, a NULL, a NaN or an infinity is refused when fetched."""
    frame = correlated(20)
    pipe = sq.Pipeline([sq.decompose.pca(n_components=2)]).learn(frame)
    gappy = frame.copy()
    gappy.iloc[3, 1] = np.nan  # NULL in DuckDB
    with pytest.raises(
        duckdb.InvalidInputException, match=r"missing.*'b'.*Fix: .*sq\.impute"
    ):
        pipe.apply(gappy).fetchall()
    with pytest.raises(duckdb.InvalidInputException, match=r"missing.*'a'"):
        pipe.apply(nan_table_of(COLUMNS)).fetchall()
    endless = frame.copy()
    endless.iloc[5, 2] = np.inf
    with pytest.raises(duckdb.InvalidInputException, match=r"infinite.*'d'.*Fix:"):
        pipe.apply(endless).fetchall()


def nan_table_of(columns):
    """Return a DuckDB table of one row of `columns`, a NaN in column `a`."""
    con = connection()
    value = {c: "'nan'" if c == "a" else "1.0" for c in columns}
    values = ", ".join(f'{value[c]}::DOUBLE AS "{c}"' for c in columns)
    return con.sql(f"SELECT {values}")


def test_pca_refuses_columns_whose_products_overflow():
    """Finite values whose squares overflow doubles are refused, with sq.scale."""
    frame = pd.DataFrame({"a": [1e200, -1e200, 3e200], "b": [1.0, 2.0, 4.0]})
    with pytest.raises(StepError, match=r"Why: .*overflow.*Fix: .*sq\.scale") as caught:
        learned(frame)
    assert caught.value.step == "pca"
    assert caught.value.position == 1


def test_pca_takes_n_components_set_after_learning_as_built():
    """A numpy whole number set after learning counts as that number."""
    frame = correlated(20)
    pipe = sq.Pipeline([("pca", sq.decompose.pca())]).learn(frame)
    pipe["pca"].n_components = np.int64(1)
    assert pipe["pca"].n_components_ == 1
    assert len(pipe["pca"].components_) == 1
    assert pipe.learn(frame).apply(frame).columns == ["pca0"]


def test_pca_refuses_n_components_set_after_learning_as_built():
    """A value the step refuses when built is refused when set later too."""
    frame = correlated(20)
    pipe = sq.Pipeline([("pca", sq.decompose.pca())]).learn(frame)
    pipe["pca"].n_components = 1.0
    with pytest.raises(StepError, match=r"n_components=1\.0.*Fix:") as caught:
        pipe.apply(frame)
    assert (caught.value.step, caught.value.position) == ("pca", 1)
    assert str(caught.value).startswith("pca (step 1) ")
    with pytest.raises(sq.errors.SqlearnError, match=r"n_components=1\.0.*Fix:"):
        _ = pipe["pca"].components_
    step = sq.decompose.pca()
    step.n_components = 1.0
    with pytest.raises(StepError, match=r"pca \(step 1\) .*n_components=1\.0.*Fix:"):
        sq.Pipeline([step]).learn(correlated(30, seed=3))


@pytest.mark.parametrize(
    ("value", "found"),
    [
        (np.nan, "1 missing value (NULL or NaN)"),
        (np.inf, "1 infinite value."),
    ],
)
def test_pca_counts_one_refused_value_in_the_singular(value, found):
    """One missing or infinite value is counted as one, not as values."""
    frame = correlated(20)
    frame.iloc[4, 1] = value
    with pytest.raises(StepError, match="Fix:") as caught:
        learned(frame)
    assert f"has {found}" in str(caught.value)
    frame.iloc[5, 1] = value
    with pytest.raises(StepError, match="Fix:") as caught:
        learned(frame)
    assert f"has {found.replace('1 ', '2 ').replace('value', 'values')}" in str(
        caught.value
    )


def test_pca_refusal_of_a_text_column_says_why_once():
    """The refusal of a text column gives a reason, not numbers taking numbers."""
    frame = correlated(20).assign(t="x")
    with pytest.raises(StepError, match="Why: PCA takes the covariance") as caught:
        sq.Pipeline([sq.decompose.pca("a", "t")]).learn(frame)
    assert "numbers, which takes numbers" not in str(caught.value)


def test_pca_keeping_no_component_refuses_a_missing_value_at_apply():
    """With n_components=0 a NULL or an infinity is still refused when fetched."""
    frame = correlated(20)
    pipe = sq.Pipeline([sq.decompose.pca("a", "b", n_components=0)]).learn(frame)
    assert pipe.apply(frame).columns == ["e", "d", "c"]
    gappy = frame.copy()
    gappy.iloc[3, 1] = np.nan  # NULL in column b
    with pytest.raises(duckdb.InvalidInputException, match=r"missing.*'b'.*Fix:"):
        pipe.apply(gappy).fetchall()
    endless = frame.copy()
    endless.iloc[5, 3] = np.inf  # column a
    with pytest.raises(duckdb.InvalidInputException, match=r"infinite.*'a'.*Fix:"):
        pipe.apply(endless).fetchall()


@pytest.mark.parametrize("whiten", [False, True])
def test_pca_applies_with_the_weights_written_once_as_a_matrix(whiten):
    """The apply SQL holds the centred row as one list and the weights once (#73).

    Each output is the dot product of that list with its row of the matrix,
    so the SQL has no product per column and component: the learn binds it
    in about a third of the memory p sums of p products took at 200 columns.
    """
    frame = correlated()
    pipe = sq.Pipeline([sq.decompose.pca(n_components=3, whiten=whiten)])
    sql = pipe.learn(frame).apply(frame).sql_query()
    assert sql.count("list_dot_product") == 3
    assert " * " not in sql.replace("SELECT * ", "")  # no product per weight
    assert sql.count(repr(pipe["pca"].components_[2][4])) == 1
    got = pipe.apply(frame, out="pandas")[["pca0", "pca1", "pca2"]].to_numpy()
    want = sk(frame, 3, whiten=whiten).transform(frame.to_numpy())
    assert got == pytest.approx(want, rel=1e-9)

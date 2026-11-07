"""Tests of sq.features against PolynomialFeatures and SplineTransformer."""

import pickle
import time

import duckdb
import numpy as np
import pandas as pd
import pytest
from duckdb.sqltypes import DOUBLE
from numpy.testing import assert_allclose
from sklearn.preprocessing import PolynomialFeatures, SplineTransformer

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import Learned, classify
from sqlearn.errors import SqlearnError, StepError
from sqlearn.preprocessing.features import Polynomial, Spline


def data(seed=1, rows=200):
    """Return seeded data: two float columns, an int column, a text column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(5, 2, rows),
            "b": rng.exponential(3, rows),
            "n": rng.integers(0, 1000, rows).astype("int64"),
            "city": rng.choice(["x", "y"], rows),
        },
    )


def applied(steps, frame, new=None):
    """Return the frame (or `new`) after the steps, learned on the frame."""
    pipe = sq.Pipeline(steps if isinstance(steps, list) else [steps]).learn(frame)
    return pipe.apply(frame if new is None else new, out="pandas")


def sklearn_names(model, columns):
    """Return scikit-learn's names, with the space of a product written ``*``."""
    return [n.replace(" ", "*") for n in model.get_feature_names_out(columns)]


# --- polynomial -------------------------------------------------------------


@pytest.mark.parametrize("degree", [1, 2, 3])
@pytest.mark.parametrize("interaction_only", [False, True])
def test_polynomial_matches_sklearn(degree, interaction_only):
    """Values and names are PolynomialFeatures', in its powers_ order."""
    frame = data()[["a", "b", "n"]]
    poly = PolynomialFeatures(
        degree=degree, interaction_only=interaction_only, include_bias=False
    ).fit(frame.to_numpy(dtype=float))
    step = sq.features.polynomial(degree=degree, interaction_only=interaction_only)
    pipe = sq.Pipeline([step]).learn(frame)
    names = sklearn_names(poly, ["a", "b", "n"])
    assert pipe.columns_out_ == names
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == names
    assert_allclose(
        got.to_numpy(), poly.transform(frame.to_numpy(dtype=float)), rtol=1e-15
    )


def test_polynomial_names_and_order_for_two_columns():
    """Two columns of degree 2 make a, b, a^2, a*b, b^2, as the spec's table."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    got = applied(sq.features.polynomial(), frame)
    assert list(got.columns) == ["a", "b", "a^2", "a*b", "b^2"]
    assert got.to_numpy().tolist() == [[1, 3, 1, 3, 9], [2, 4, 4, 8, 16]]


def test_polynomial_include_bias_adds_a_column_of_ones_named_1():
    """include_bias=True adds scikit-learn's column ``1``, after the inputs."""
    frame = data()[["a", "b"]]
    poly = PolynomialFeatures(degree=2).fit(frame.to_numpy())
    got = applied(sq.features.polynomial(include_bias=True), frame)
    assert list(got.columns) == ["a", "b", "1", "a^2", "a*b", "b^2"]
    expected = pd.DataFrame(
        poly.transform(frame.to_numpy()), columns=sklearn_names(poly, ["a", "b"])
    )
    assert_allclose(got[expected.columns].to_numpy(), expected.to_numpy(), rtol=1e-15)


def test_polynomial_passes_other_columns_and_keeps_their_place():
    """Unselected columns pass through; the new terms follow the last input."""
    frame = data()
    got = applied(sq.features.polynomial("a", "b"), frame)
    assert list(got.columns) == ["a", "b", "a^2", "a*b", "b^2", "n", "city"]
    assert got["city"].tolist() == frame["city"].tolist()


def test_polynomial_null_stays_null_and_nan_stays_nan():
    """A missing value makes every term it is in missing, as numpy's NaN does."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1.0, 2.0), (NULL, 3.0), (2.0, 'nan'::DOUBLE)) t(a, b)"
    )
    rows = sq.Pipeline([sq.features.polynomial()]).learn(rel).apply(rel).fetchall()
    assert rows[0] == (1.0, 2.0, 1.0, 2.0, 4.0)
    assert rows[1][:2] == (None, 3.0)
    assert rows[1][2:] == (None, None, 9.0)
    assert np.isnan(rows[2][1]) and np.isnan(rows[2][3]) and np.isnan(rows[2][4])
    assert rows[2][2] == 4.0


@pytest.mark.parametrize("kind", ["INTEGER", "BIGINT", "DECIMAL(10,2)"])
def test_polynomial_of_integer_and_decimal_columns_is_double(kind):
    """Integer and decimal inputs give DOUBLE terms, as scikit-learn's float64."""
    rel = connection().sql(
        f"SELECT a::{kind} AS a, b::{kind} AS b "
        "FROM (VALUES (3, 100000), (2, 70000)) t(a, b)"
    )
    pipe = sq.Pipeline([sq.features.polynomial()]).learn(rel)
    out = pipe.apply(rel)
    assert {str(t) for t in out.types} == {"DOUBLE"}
    assert out.fetchall()[0] == (3.0, 100000.0, 9.0, 300000.0, 1e10)


def test_polynomial_names_clash_with_a_column_passing_through():
    """A term whose name a passing column holds is numbered (ADR 0035)."""
    frame = pd.DataFrame({"a": [2.0], "a^2": [7.0]})
    got = applied(sq.features.polynomial("a"), frame)
    assert list(got.columns) == ["a", "a^2_2", "a^2"]
    assert got.to_numpy().tolist() == [[2.0, 4.0, 7.0]]


def test_polynomial_terms_named_like_an_input_are_numbered():
    """A term spelt as an input column (``a^2``) is numbered, not overwritten.

    The input's own term keeps its name; the square of ``a`` follows as
    ``a^2_2``, as the bias ``1`` beside an input named ``1`` is ``1_2``.
    """
    frame = pd.DataFrame({"a": [2.0, 3.0], "a^2": [10.0, 20.0]})
    pipe = sq.Pipeline([sq.features.polynomial()]).learn(frame)
    assert pipe.columns_out_ == ["a", "a^2", "a^2_2", "a*a^2", "a^2^2"]
    got = pipe.apply(frame, out="pandas")
    assert list(got.columns) == pipe.columns_out_
    sk = PolynomialFeatures().fit(frame)
    assert_allclose(got.to_numpy(), sk.transform(frame)[:, 1:])
    swapped = frame[["a^2", "a"]]
    pipe = sq.Pipeline([sq.features.polynomial()]).learn(swapped)
    assert pipe.columns_out_ == ["a^2", "a", "a^2^2", "a^2*a", "a^2_2"]
    got = pipe.apply(swapped, out="pandas")
    assert_allclose(got.to_numpy(), sk.fit_transform(swapped)[:, 1:])
    ones = pd.DataFrame({"1": [2.0, 3.0], "b": [5.0, 7.0]})
    pipe = sq.Pipeline([sq.features.polynomial(include_bias=True)]).learn(ones)
    assert pipe.columns_out_ == ["1", "b", "1_2", "1^2", "1*b", "b^2"]
    assert pipe.apply(ones, out="pandas")["1_2"].tolist() == [1.0, 1.0]


def test_polynomial_learns_nothing_and_reads_the_whole_row():
    """Polynomial is static, whole-row, and names its outputs in full."""
    assert Polynomial.static is True
    assert Polynomial.rowwise is True
    assert Polynomial.names_are_labels is False
    assert Polynomial().learn(sq.fn.const(1.0)) == {}
    undeclared = type("Undeclared", (Polynomial,), {"static": None})()
    assert classify(undeclared, [("a", DOUBLE), ("b", DOUBLE)]) == "static"


def test_polynomial_chains_into_the_stage_around_it():
    """A step after it learns from its terms in the same run."""
    frame = data()[["a", "b"]]
    pipe = sq.Pipeline([sq.features.polynomial(), sq.scale.standard("a*b")])
    pipe.learn(frame)
    assert len(pipe.runs_) == 1
    assert_allclose(pipe["standard"].center_["a*b"], (frame.a * frame.b).mean())


def test_polynomial_of_no_column_creates_nothing():
    """With no numeric column selected, nothing changes, not even ``1``."""
    frame = pd.DataFrame({"city": ["x", "y"]})
    assert applied(sq.features.polynomial(), frame).equals(frame)
    assert sq.features.polynomial(include_bias=True).apply_row({}, {}, {}) == []


# --- spline -----------------------------------------------------------------


def sklearn_spline(train, n_knots=5, degree=3, knots="uniform"):
    """Return scikit-learn's spline transformer fitted to one column."""
    return SplineTransformer(n_knots=n_knots, degree=degree, knots=knots).fit(
        np.asarray(train, dtype=float).reshape(-1, 1)
    )


def basis(model, values):
    """Return scikit-learn's basis of one column of values."""
    return model.transform(np.asarray(values, dtype=float).reshape(-1, 1))


SPLINES = [(5, 3), (4, 2), (3, 1), (6, 0), (2, 3), (7, 4)]


@pytest.mark.parametrize("knots", ["uniform", "quantile"])
@pytest.mark.parametrize(("n_knots", "degree"), SPLINES)
def test_spline_matches_sklearn(knots, n_knots, degree):
    """Values, names and knots are SplineTransformer's on the data it learned."""
    frame = data()[["a"]]
    model = sklearn_spline(frame.a, n_knots, degree, knots)
    step = sq.features.spline(n_knots=n_knots, degree=degree, knots=knots)
    pipe = sq.Pipeline([step]).learn(frame)
    assert pipe.columns_out_ == list(model.get_feature_names_out(["a"]))
    assert_allclose(pipe[step.default_name()].knots_["a"], model.bsplines_[0].t)
    got = pipe.apply(frame, out="pandas")
    assert_allclose(got.to_numpy(), basis(model, frame.a), atol=1e-13)


@pytest.mark.parametrize("knots", ["uniform", "quantile"])
def test_spline_outside_the_training_range_is_constant(knots):
    """Below and above the knots, the boundary values, as extrapolation="constant"."""
    frame = data()[["a"]]
    model = sklearn_spline(frame.a, knots=knots)
    low, high = frame.a.min(), frame.a.max()
    new = pd.DataFrame({"a": [low - 100.0, low - 1e-9, low, high, high + 1e-9, 1e6]})
    got = applied(sq.features.spline(knots=knots), frame, new)
    assert_allclose(got.to_numpy(), basis(model, new.a), atol=1e-13)


def test_spline_of_degree_zero_is_zero_on_both_sides_of_the_knots():
    """degree=0 has no boundary columns: outside the knots, zeros on both sides.

    scikit-learn agrees below the knots and raises above them (a shape
    mismatch in its constant extrapolation); sqlearn gives zeros there too.
    """
    frame = pd.DataFrame({"a": [0.0, 1.0, 2.0]})
    model = sklearn_spline(frame.a, n_knots=3, degree=0)
    step = sq.features.spline(n_knots=3, degree=0)
    inside = pd.DataFrame({"a": [-1.0, 0.0, 1.0, 2.0]})
    assert_allclose(applied(step, frame, inside).to_numpy(), basis(model, inside.a))
    with pytest.raises(ValueError, match="shape mismatch"):
        basis(model, [3.0])
    above = applied(step, frame, pd.DataFrame({"a": [3.0, 1e9]}))
    assert above.to_numpy().tolist() == [[0.0, 0.0], [0.0, 0.0]]


def test_spline_of_a_constant_column():
    """A constant column gives zeros everywhere, as SplineTransformer gives."""
    frame = pd.DataFrame({"a": [3.0] * 6})
    new = pd.DataFrame({"a": [3.0, 2.0, 4.0]})
    for knots in ("uniform", "quantile"):
        model = sklearn_spline(frame.a, knots=knots)
        got = applied(sq.features.spline(knots=knots), frame, new)
        expected = basis(model, new.a)
        assert_allclose(got.to_numpy(), expected, atol=0)
        assert not expected.any()


def test_spline_with_repeated_quantile_knots_matches_sklearn():
    """Equal knots, at the minimum and at the maximum, follow scipy's B-splines."""
    for values in (
        [1.0, 1.0, 1.0, 2.0],
        [1.0, 2.0, 2.0, 2.0, 2.0],
        [0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 9.0],
    ):
        frame = pd.DataFrame({"a": values})
        new = pd.DataFrame({"a": np.linspace(min(values) - 1, max(values) + 1, 41)})
        for n_knots, degree in ((5, 3), (4, 2), (3, 1)):
            model = sklearn_spline(values, n_knots, degree, "quantile")
            step = sq.features.spline(n_knots=n_knots, degree=degree, knots="quantile")
            got = applied(step, frame, new)
            assert_allclose(got.to_numpy(), basis(model, new.a), atol=1e-13)


@pytest.mark.parametrize("knots", ["uniform", "quantile"])
def test_spline_chains_into_the_stage_around_it(knots):
    """A step after it learns from its basis in the same run, as scikit-learn's."""
    frame = data()[["a"]]
    new = pd.DataFrame({"a": [frame.a.min() - 3.0, frame.a.max() + 3.0]})
    together = pd.concat([frame, new], ignore_index=True)
    model = sklearn_spline(frame.a, knots=knots)
    pipe = sq.Pipeline([sq.features.spline(knots=knots), sq.scale.standard()])
    learned = pipe.learn(frame)
    assert len(learned.runs_) == 1
    expected = basis(model, frame.a)
    names = model.get_feature_names_out(["a"])
    means = learned["standard"].center_
    assert_allclose([means[n] for n in names], expected.mean(axis=0), atol=1e-13)
    # A learn never reaches outside its own range, so the placeholder path's
    # values outside it are evaluated directly, against scikit-learn's.
    step = sq.features.spline(knots=knots)
    names_in = list(step.learn(duckdb.ColumnExpression("a")))
    slots = {key: f"v{i}" for i, key in enumerate(names_in)}
    x = duckdb.ColumnExpression("a")
    pairs = step.apply(x, Learned.placeholders("l", slots))
    t = model.bsplines_[0].t
    learned_row = (
        [float(t[3]), float(t[-4]), 0.0]
        if knots == "uniform"
        else [f"[{', '.join(repr(float(v)) for v in t[3:-3])}]", 0.0]
    )
    row = ", ".join(str(v) for v in learned_row)
    values = ", ".join(f"({float(v)!r})" for v in together.a)
    sql = (
        f"SELECT {', '.join(str(e) for _, e in pairs)} "
        f"FROM (VALUES {values}) d(a), (SELECT {row}) l({', '.join(slots.values())})"
    )
    got = np.array(connection().sql(sql).fetchall())
    assert_allclose(got, basis(model, together.a), atol=1e-13)


def test_a_step_naming_a_spline_output_depends_on_it():
    """A step reading x_sp_0 by name relearns when the spline's settings change."""
    frame = data()[["a"]]
    centers = []
    for n_knots in (4, 6):
        pipe = sq.Pipeline(
            [sq.features.spline(n_knots=n_knots), sq.scale.standard("a_sp_0")]
        ).learn(frame)
        centers.append(pipe["standard"].center_["a_sp_0"])
    expected = [basis(sklearn_spline(frame.a, n), frame.a)[:, 0].mean()
                for n in (4, 6)]  # fmt: skip
    assert_allclose(centers, expected, atol=1e-13)


def test_spline_refuses_a_missing_value_when_fetched():
    """A NULL or NaN is refused, as SplineTransformer's handle_missing="error"."""
    rel = connection().sql("SELECT * FROM (VALUES (1.0), (2.0), (NULL), (4.0)) t(a)")
    pipe = sq.Pipeline([sq.features.spline()]).learn(rel)
    with pytest.raises(
        duckdb.InvalidInputException,
        match=r"sq\.features\.spline.*missing.*'a'.*Fix: impute",
    ):
        pipe.apply(rel).fetchall()
    nan = connection().sql("SELECT * FROM (VALUES (1.0), ('nan'::DOUBLE)) t(a)")
    with pytest.raises(duckdb.InvalidInputException, match=r"'a'"):
        pipe.apply(nan).fetchall()


def test_spline_refuses_infinity():
    """Infinity is refused at learn, and when fetched at apply."""
    bad = connection().sql("SELECT * FROM (VALUES (1.0), ('inf'::DOUBLE)) t(a)")
    with pytest.raises(StepError, match=r"\(step 1\).*infinity"):
        sq.Pipeline([sq.features.spline()]).learn(bad)
    good = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    pipe = sq.Pipeline([sq.features.spline()]).learn(good)
    with pytest.raises(duckdb.InvalidInputException, match=r"'a'.*infinite"):
        pipe.apply(bad).fetchall()


def test_spline_of_an_all_missing_column_is_refused():
    """A column with no present value is refused at learn, naming it."""
    rel = connection().sql("SELECT NULL::DOUBLE AS a FROM range(3)")
    with pytest.raises(StepError, match=r"\(step 1\).*'a'.*every value is missing"):
        sq.Pipeline([sq.features.spline()]).learn(rel)


@pytest.mark.parametrize("kind", ["INTEGER", "BIGINT", "DECIMAL(10,2)"])
def test_spline_of_integer_and_decimal_columns_is_double(kind):
    """Integer and decimal inputs give DOUBLE values, as scikit-learn's float64."""
    rel = connection().sql(f"SELECT (range % 17)::{kind} AS a FROM range(50)")
    values = [float(i % 17) for i in range(50)]
    model = sklearn_spline(values)
    out = sq.Pipeline([sq.features.spline()]).learn(rel).apply(rel)
    assert {str(t) for t in out.types} == {"DOUBLE"}
    got = np.array(out.fetchall())
    assert_allclose(got, basis(model, values), atol=1e-13)


def test_spline_works_per_column_and_passes_the_rest():
    """Each column gets its own basis, in place; other columns pass through."""
    frame = data()
    got = applied(sq.features.spline("a", "b", n_knots=3, degree=2), frame)
    expected_a = basis(sklearn_spline(frame.a, 3, 2), frame.a)
    expected_b = basis(sklearn_spline(frame.b, 3, 2), frame.b)
    a_names = [f"a_sp_{i}" for i in range(4)]
    b_names = [f"b_sp_{i}" for i in range(4)]
    assert list(got.columns) == [*a_names, *b_names, "n", "city"]
    assert_allclose(got[a_names].to_numpy(), expected_a, atol=1e-13)
    assert_allclose(got[b_names].to_numpy(), expected_b, atol=1e-13)


def test_spline_is_static_and_creates_double():
    """Spline is declared static: its columns follow from its settings."""
    assert Spline.static is True
    assert Spline.creates == DOUBLE
    assert Spline.rowwise is False
    x = duckdb.ColumnExpression("a")
    assert list(Spline().learn(x)) == ["min", "max", "infinite"]
    assert list(Spline(knots="quantile").learn(x)) == ["quantiles", "infinite"]
    with pytest.raises(AttributeError, match="after the step has learned"):
        _ = Spline().knots_


# --- the group --------------------------------------------------------------


def test_shortcut_equals_general_form():
    """Each shortcut builds the step the general form builds with its settings."""
    pairs = [
        (sq.features.polynomial("a", "b"), sq.features("a", "b", method="polynomial")),
        (
            sq.features.polynomial(degree=3, interaction_only=True, include_bias=True),
            sq.features(
                method="polynomial",
                degree=3,
                interaction_only=True,
                include_bias=True,
            ),
        ),
        (sq.features.spline("a"), sq.features("a", method="spline")),
        (
            sq.features.spline("a", n_knots=4, degree=2, knots="quantile"),
            sq.features("a", method="spline", n_knots=4, degree=2, knots="quantile"),
        ),
    ]
    frame = data()[["a", "b"]]
    for short, general in pairs:
        assert type(short) is type(general)
        assert short.settings() == general.settings()
        assert repr(short) == repr(general)
        assert short.default_name() == general.default_name()
        a = sq.Pipeline([short]).learn(frame)
        b = sq.Pipeline([general]).learn(frame)
        assert a.apply(frame, out="pandas").equals(b.apply(frame, out="pandas"))


def test_no_method_is_a_type_error_and_a_bad_one_is_refused():
    """The general form has no default method; an unknown one is refused."""
    with pytest.raises(TypeError):
        sq.features("a")  # ty: ignore[no-matching-overload]
    with pytest.raises(SqlearnError, match=r"method='fourier'.*polynomial.*spline"):
        sq.features("a", method="fourier")


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (
            lambda: sq.features(method="spline", interaction_only=True),
            "interaction_only=",
        ),
        (lambda: sq.features(method="spline", include_bias=True), "include_bias="),
        (lambda: sq.features(method="polynomial", n_knots=3), "n_knots="),
        (lambda: sq.features(method="polynomial", knots="quantile"), "knots="),
        (
            lambda: sq.features(method="polynomial", extrapolation="constant"),
            "extrapolation=",
        ),
        (lambda: sq.features.polynomial(degree=-1), "degree"),
        (lambda: sq.features.polynomial(degree=2.0), "degree"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.features.polynomial(degree=True), "degree"),
        (lambda: sq.features.polynomial(degree=0), "include_bias"),
        (lambda: sq.features.polynomial(interaction_only=1), "interaction_only"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.features.spline(n_knots=1), "n_knots"),
        (lambda: sq.features.spline(n_knots=4.0), "n_knots"),  # ty: ignore[invalid-argument-type]
        (lambda: sq.features.spline(degree=-1), "degree"),
        (lambda: sq.features.spline(knots="even"), "knots"),
        (lambda: Spline(extrapolation="linear"), "extrapolation"),
    ],
)
def test_bad_settings_are_refused(build, match):
    """Each bad setting is refused with a message naming it."""
    with pytest.raises(SqlearnError, match=match):
        build()


def test_polynomial_of_degree_zero_with_the_bias_is_the_column_of_ones():
    """degree=0 with include_bias=True gives only ``1``, as scikit-learn."""
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    got = applied(sq.features.polynomial(degree=0, include_bias=True), frame)
    assert list(got.columns) == ["1"]
    assert got["1"].tolist() == [1.0, 1.0]


@pytest.mark.parametrize("make", [sq.features.polynomial, sq.features.spline])
def test_a_text_column_is_refused_by_name(make):
    """A text column chosen by name is refused, naming it."""
    with pytest.raises(StepError, match=r"\(step 1\).*'city'"):
        sq.Pipeline([make("a", "city")]).learn(data())


def test_default_columns_are_the_numeric_ones():
    """Without columns, both work on every numeric column."""
    frame = data()
    assert Polynomial().inputs([(c, DOUBLE) for c in "ab"]) == ["a", "b"]
    got = applied(sq.features.spline(n_knots=2, degree=1), frame)
    assert list(got.columns) == [
        "a_sp_0", "a_sp_1", "b_sp_0", "b_sp_1", "n_sp_0", "n_sp_1", "city",
    ]  # fmt: skip


def test_columns_by_name_list_or_selector():
    """Columns come as names, one list, or cols=; a dict is refused."""
    assert sq.features.polynomial("a", "b").cols == ["a", "b"]
    assert sq.features.spline(["a", "b"]).cols == ["a", "b"]
    assert sq.features.spline(cols=sq.cols.numeric()).cols == sq.cols.numeric()
    with pytest.raises(SqlearnError, match="twice"):
        sq.features.spline("a", cols="b")
    with pytest.raises(SqlearnError, match="dict"):
        sq.features({"a": "spline"}, method="spline")


def test_default_names():
    """A step is named after its method."""
    assert sq.features.polynomial(degree=3).default_name() == "polynomial"
    assert sq.features(method="spline", knots="quantile").default_name() == "spline"


def test_repr_is_the_shortest_form_that_rebuilds():
    """The repr names the method and only the settings that differ from it."""
    cases = {
        "sq.features.polynomial()": sq.features(method="polynomial"),
        "sq.features.polynomial(cols=['a', 'b'], degree=3)": sq.features.polynomial(
            "a", "b", degree=3
        ),
        "sq.features.polynomial(interaction_only=True, include_bias=True)": (
            sq.features.polynomial(interaction_only=True, include_bias=True)
        ),
        "sq.features.spline()": sq.features(method="spline", n_knots=5, degree=3),
        "sq.features.spline(cols='a', n_knots=4, degree=2, knots='quantile')": (
            sq.features.spline("a", n_knots=4, degree=2, knots="quantile")
        ),
    }
    for text, step in cases.items():
        assert repr(step) == text
        assert eval(text).settings() == step.settings()


def test_settings_read_back_under_the_init_names():
    """Settings read back under the ``__init__`` names."""
    assert sq.features.polynomial(degree=3).settings() == {
        "cols": None,
        "degree": 3,
        "interaction_only": False,
        "include_bias": False,
    }
    assert sq.features.spline(knots="quantile").settings() == {
        "cols": None,
        "n_knots": 5,
        "degree": 3,
        "knots": "quantile",
        "extrapolation": "constant",
    }


def test_the_steps_pickle():
    """A step pickles and comes back equal (the search copies steps)."""
    for step in (sq.features.polynomial("a", degree=3), sq.features.spline(n_knots=4)):
        back = pickle.loads(pickle.dumps(step))
        assert back.settings() == step.settings()
        assert repr(back) == repr(step)


def test_the_group_lists_its_shortcuts():
    """Tab completion lists the shortcuts; the group prints as sq.features."""
    assert repr(sq.features) == "sq.features"
    assert {"polynomial", "spline"} <= set(dir(sq.features))


def test_a_wide_spline_learns_fast_when_nothing_reads_it_in_the_run():
    """50 columns learn in well under 2 s: the unread basis is not built."""
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({f"c{i}": rng.normal(size=200) for i in range(50)})
    warm_up = pd.DataFrame({"w": rng.normal(size=20)})
    sq.Pipeline([sq.features.spline()]).learn(warm_up)  # DuckDB start-up, caches
    sq.store.clear()
    start = time.perf_counter()
    pipe = sq.Pipeline([sq.features.spline()]).learn(frame)
    assert time.perf_counter() - start < 2.0
    assert len(pipe.runs_) == 1
    model = sklearn_spline(frame.c7)
    got = pipe.apply(frame, out="pandas")
    expected = basis(model, frame.c7)
    assert_allclose(got[[f"c7_sp_{i}" for i in range(7)]], expected, atol=1e-13)


@pytest.mark.parametrize("knots", ["uniform", "quantile"])
def test_the_store_entry_is_the_same_whether_or_not_a_later_step_reads_it(knots):
    """Learned alone or read by a later step, the spline stores the same entry."""
    frame = data()[["a", "b"]]
    alone = sq.Pipeline([sq.features.spline(knots=knots)]).learn(frame)
    sq.store.clear()
    read = sq.Pipeline(
        [sq.features.spline(knots=knots), sq.scale.standard("a_sp_2")]
    ).learn(frame)
    first, second = alone._entries, read._entries
    assert first is not None and second is not None
    assert first[0] == second[0]
    ours, theirs = alone.apply(frame, out="pandas"), read.apply(frame, out="pandas")
    unscaled = [c for c in ours.columns if c != "a_sp_2"]
    assert ours[unscaled].equals(theirs[unscaled])

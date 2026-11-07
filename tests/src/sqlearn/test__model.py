"""Tests of models: the wrapper and copying it."""

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest
from catboost import CatBoostClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn import _feed
from sqlearn._model import Model, as_model, copy_model
from sqlearn.errors import SqlearnError

DATA_WITH_CITY = pd.DataFrame(
    {
        "x": np.arange(40.0),
        "city": ["oslo", "rome", "kyiv", "oslo"] * 10,
        "y": [0, 1, 1, 0] * 10,
    }
)
NUMERIC_DATA = pd.DataFrame(
    {"a": np.arange(30.0), "b": np.arange(30.0) % 7, "y": [0, 1, 1] * 10}
)


class Plain:
    """A model without get_params: copied whole."""

    def __init__(self) -> None:
        self.weights = [1.0, 2.0]

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return the first column."""
        return x[:, 0]


def test_model_is_exported_with_a_deterministic_repr():
    """`sq.Model` shows the estimator's own repr and the feed."""
    model = sq.Model(LogisticRegression(C=0.1))
    assert sq.Model is Model
    assert repr(model) == "Model(LogisticRegression(C=0.1))"
    assert repr(model) == repr(sq.Model(LogisticRegression(C=0.1)))


def test_the_repr_shows_only_what_differs_from_the_defaults():
    """The feed and the stream's settings appear once they are not the defaults."""
    model = LogisticRegression()
    assert repr(sq.Model(model, feed="pandas")) == (
        "Model(LogisticRegression(), feed='pandas')"
    )
    streamed = sq.Model(model, feed="stream", rows=1000, shuffle=False)
    assert repr(streamed) == (
        "Model(LogisticRegression(), feed='stream', rows=1000, shuffle=False)"
    )


def test_as_model_wraps_a_plain_estimator_and_keeps_a_model():
    """A plain estimator is wrapped; a Model is passed through as it is."""
    estimator = LogisticRegression()
    wrapped = as_model(estimator)
    assert isinstance(wrapped, Model)
    assert wrapped.estimator is estimator
    assert wrapped.feed == "numpy"
    assert as_model(wrapped) is wrapped


def test_an_object_without_fit_and_predict_is_not_a_model():
    """A model needs fit and predict; the message names what is missing."""
    with pytest.raises(sq.errors.SqlearnError, match="predict"):
        sq.Model(type("OnlyFit", (), {"fit": lambda self, x, y: self})())


def test_copy_model_keeps_settings():
    """A copy holds a new, unfitted estimator with the same settings and feed."""
    model = sq.Model(LogisticRegression(C=0.1, max_iter=55))
    model.estimator.fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
    copy = copy_model(model)
    assert copy is not model
    assert copy.estimator is not model.estimator
    assert copy.estimator.get_params() == model.estimator.get_params()
    assert copy.feed == model.feed
    assert not hasattr(copy.estimator, "coef_")
    assert repr(copy) == repr(model)
    streamed = sq.Model(LogisticRegression(), feed="stream", megabytes=8, epochs=3)
    assert repr(copy_model(streamed)) == repr(streamed)


def test_copy_model_without_get_params_deep_copies():
    """A model without get_params is copied with copy.deepcopy."""
    model = sq.Model(Plain())
    copy = copy_model(model)
    assert copy.estimator is not model.estimator
    assert copy.estimator.weights == [1.0, 2.0]
    assert copy.estimator.weights is not model.estimator.weights


class Settings:
    """A model whose get_params takes no argument, holding a nested model."""

    def __init__(self, alpha=1.0, inner=None, kind=None):
        self.alpha = alpha
        self.inner = inner
        self.kind = kind

    def get_params(self):
        """Return the settings."""
        return {"alpha": self.alpha, "inner": self.inner, "kind": self.kind}

    def fit(self, x, y):
        """Do nothing."""
        return self

    def predict(self, x):
        """Return the features themselves: two values per row."""
        return x


def test_copy_model_rebuilds_from_settings_and_copies_nested_models():
    """get_params without `deep` is called plainly; nested models are rebuilt."""
    inner = LogisticRegression(C=3.0).fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
    model = sq.Model(Settings(alpha=0.5, inner=inner, kind=LogisticRegression))
    copy = copy_model(model)
    assert copy.estimator.alpha == 0.5
    assert copy.estimator.kind is LogisticRegression
    assert copy.estimator.inner is not inner
    assert copy.estimator.inner.C == 3.0
    assert not hasattr(copy.estimator.inner, "coef_")


@pytest.mark.parametrize(
    ("feed", "kind"),
    [("pandas", pd.DataFrame), ("polars", pl.DataFrame), ("arrow", pa.Table)],
)
def test_each_form_reaches_fit(feed, kind):
    """fit gets the features in the form the feed names, text columns kept."""
    seen = {}

    class Keep:
        def fit(self, x, y):
            seen["x"] = x
            return self

        def predict(self, x):
            return np.zeros(len(x))

    pipe = sq.Pipeline([sq.scale.standard(), sq.Model(Keep(), feed=feed)])
    pipe.train(DATA_WITH_CITY, target="y")
    assert isinstance(seen["x"], kind) and "city" in list(
        seen["x"].columns if feed != "arrow" else seen["x"].column_names
    )


def test_the_target_goes_over_in_the_form_of_the_features():
    """A Series for pandas and Polars, an Arrow array for arrow."""
    seen = {}

    class Keep:
        def fit(self, x, y):
            seen[type(x)] = y
            return self

        def predict(self, x):
            return np.zeros(len(x))

    for feed in ("numpy", "pandas", "polars", "arrow"):
        sq.Pipeline([sq.Model(Keep(), feed=feed)]).train(NUMERIC_DATA, target="y")
    assert isinstance(seen[np.ndarray], np.ndarray)
    assert isinstance(seen[pd.DataFrame], pd.Series)
    assert isinstance(seen[pl.DataFrame], pl.Series)
    assert isinstance(seen[pa.Table], pa.ChunkedArray)
    assert seen[pa.Table].to_pylist() == NUMERIC_DATA["y"].tolist()


def test_histogram_boosting_takes_text_columns_through_pandas():
    """scikit-learn's boosting reads the category dtype, at train and predict.

    LightGBM, which the plan names here, needs the system's OpenMP library
    on macOS (brew install libomp), so this test uses a model that reads the
    same form without it.
    """
    model = HistGradientBoostingClassifier(
        max_iter=5, categorical_features="from_dtype"
    )
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(model, feed="pandas")])
    pipe.train(DATA_WITH_CITY, target="y")
    assert len(pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"]) == len(
        DATA_WITH_CITY
    )


def test_catboost_takes_text_columns_through_pandas():
    """CatBoost still takes cat_features= as it would without sqlearn."""
    model = CatBoostClassifier(
        iterations=5, verbose=0, cat_features=["city"], allow_writing_files=False
    )
    pipe = sq.Pipeline([sq.impute.median(), sq.Model(model, feed="pandas")])
    pipe.train(DATA_WITH_CITY, target="y")
    assert pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"].shape == (
        len(DATA_WITH_CITY),
    )


def test_one_model_gives_the_same_predictions_through_every_form():
    """The form changes how the data travels, not what the model learns."""
    got = {}
    for feed in ("numpy", "pandas", "polars", "arrow"):
        pipe = sq.Pipeline(
            [sq.scale.standard(), sq.Model(LogisticRegression(), feed=feed)]
        )
        got[feed] = pipe.train(NUMERIC_DATA, target="y").predict(
            NUMERIC_DATA, out="numpy"
        )["prediction"]
    for feed in ("pandas", "polars", "arrow"):
        np.testing.assert_array_equal(got[feed], got["numpy"])


@pytest.mark.parametrize(
    "setting",
    [{"rows": 1000}, {"megabytes": 8}, {"epochs": 2}, {"shuffle": False}, {"seed": 1}],
)
def test_settings_of_the_stream_need_the_stream(setting):
    """rows, megabytes, epochs, shuffle and seed belong to feed='stream'."""
    with pytest.raises(SqlearnError, match=f"{next(iter(setting))}="):
        sq.Model(LogisticRegression(), feed="pandas", **setting)
    sq.Model(LogisticRegression(), feed="stream", **setting)


def test_an_unknown_feed_names_the_forms():
    """A feed that is not a form is refused, naming the five."""
    with pytest.raises(SqlearnError, match=r"'parquet'.*numpy, pandas, polars"):
        sq.Model(LogisticRegression(), feed="parquet")


def test_categories_map_by_value_whatever_the_batch_holds(monkeypatch):
    """A batch's categories are its own; the model still reads them by value."""
    model = HistGradientBoostingClassifier(
        max_iter=5, categorical_features="from_dtype"
    )
    pipe = sq.Pipeline([sq.Model(model, feed="pandas")])
    pipe.train(DATA_WITH_CITY, target="y")
    whole = pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"]
    monkeypatch.setattr(_feed, "BATCH_ROWS", 1)
    one_by_one = pipe.predict(DATA_WITH_CITY, out="numpy")["prediction"]
    np.testing.assert_array_equal(one_by_one, whole)
    assert whole.tolist() == DATA_WITH_CITY["y"].tolist()


def test_training_through_the_stream_is_not_built_yet():
    """feed='stream' is a form, but partial_fit training comes later."""
    pipe = sq.Pipeline([sq.Model(LogisticRegression(), feed="stream")])
    with pytest.raises(SqlearnError, match="partial_fit"):
        pipe.train(NUMERIC_DATA, target="y")


class Codes:
    """A model that reads category codes: predict returns the city's codes."""

    def fit(self, x, y):
        """Learn nothing."""
        return self

    def predict(self, x):
        """Return each row's city code, as XGBoost before 3.1 would read it."""
        if isinstance(x, pd.DataFrame):
            return x["city"].cat.codes.to_numpy()
        if isinstance(x, pl.DataFrame):
            return x["city"].to_physical().to_numpy()
        return x.column("city").combine_chunks().indices.to_numpy()


@pytest.mark.parametrize("feed", ["pandas", "polars", "arrow"])
def test_prediction_reads_training_s_codes_batch_by_batch(feed, monkeypatch):
    """A batch lacking a training value, or holding a new one, keeps the codes."""
    train = pd.DataFrame({"city": ["rome", "oslo", "kyiv"], "y": [0, 1, 0]})
    pipe = sq.Pipeline([sq.Model(Codes(), feed=feed)]).train(train, target="y")
    monkeypatch.setattr(_feed, "BATCH_ROWS", 1)
    later = pd.DataFrame({"city": ["rome", "paris", "kyiv"]})
    assert pipe.predict(later, out="numpy")["prediction"].tolist() == [2, 3, 0]

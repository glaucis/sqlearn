"""Tests of PCA in pipelines, searches and saved files (spec §2, §5.4, §7)."""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn import decomposition
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline as SkPipeline
from sklearn.preprocessing import StandardScaler

import sqlearn as sq
from sqlearn._store import STORE
from sqlearn.errors import StepError


def labelled(rows=120, columns=5, seed=0):
    """Return `rows` rows of correlated numeric columns and a 0/1 target ``y``."""
    rng = np.random.default_rng(seed)
    mixing = rng.normal(size=(columns, columns))
    values = rng.normal(size=(rows, columns)) @ mixing + np.arange(columns)
    frame = pd.DataFrame(values, columns=[f"x{i}" for i in range(columns)])
    frame["y"] = (values[:, 0] - values[:, 1] + rng.normal(size=rows) > 0).astype(int)
    return frame


def _sales(folder: Path) -> str:
    """Write two Parquet files of 50 numeric columns, a few values missing."""
    folder.mkdir()
    frame = labelled(rows=400, columns=50).drop(columns="y")
    frame.iloc[::17, 3] = np.nan
    con = duckdb.connect()
    for part, rows in enumerate([frame.iloc[:200], frame.iloc[200:]]):
        con.register("part", rows)
        con.execute(f"COPY part TO '{folder / f'{part}.parquet'}' (FORMAT parquet)")
        con.unregister("part")
    return str(folder / "*.parquet")


def test_spec_examples_run(tmp_path):
    """Spec §2's code runs as written, on generated Parquet files."""
    sales = _sales(tmp_path / "sales")
    pipe = sq.Pipeline([sq.impute(), sq.scale(), sq.decompose.pca(n_components=3)])
    pipe.learn(sales)
    ratios = pipe["pca"].explained_variance_ratio_
    assert len(ratios) == 3 and ratios == sorted(ratios, reverse=True)
    components = pipe["pca"].components_
    assert len(components) == 3 and all(len(c) == 50 for c in components)
    out = pipe.apply(sales)
    assert out.columns == ["pca0", "pca1", "pca2"]

    assert sq.decompose.pca(n_components=0.95).n_components == 0.95
    assert sq.decompose.pca(whiten=True).whiten is True
    general = sq.decompose(method="pca", n_components=3)
    assert repr(general) == "sq.decompose.pca(n_components=3)"

    data = labelled(rows=120, columns=25)
    pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(), LogisticRegression()])
    search = sq.search(
        pipe, params={"pca__n_components": [5, 10, 20]}, metric=sq.metrics.f1
    )
    search.train(data, target="y")
    assert search.best_params_["pca__n_components"] in (5, 10, 20)


def test_train_then_predict_matches_scikit_learn():
    """scale, pca(3) and a model predict as scikit-learn's Pipeline of the same."""
    train, new = labelled(seed=0), labelled(seed=1)
    features = [c for c in train.columns if c != "y"]
    sk = SkPipeline(
        [
            ("scale", StandardScaler()),
            ("pca", decomposition.PCA(3, svd_solver="covariance_eigh")),
            ("model", LogisticRegression()),
        ]
    ).fit(train[features], train["y"])
    pipe = sq.Pipeline(
        [sq.scale(), sq.decompose.pca(n_components=3), LogisticRegression()]
    ).train(train, target="y")
    assert pipe.columns_out_ == ["pca0", "pca1", "pca2"]
    got = pipe.predict(new, out="numpy")["prediction"]
    np.testing.assert_array_equal(got, sk.predict(new[features]))
    probabilities = pipe.predict_proba(new, out="numpy")
    want = sk.predict_proba(new[features])
    for k in range(len(pipe.classes_)):
        got_k = probabilities[f"__sqlearn_proba_{k}"]
        np.testing.assert_allclose(got_k, want[:, k], atol=1e-9)


def test_a_search_over_n_components_learns_each_fold_once():
    """3 settings of `n_components` x 3 folds: 3 learns, plus 1 for the final.

    `n_components` chooses only the output (ADR 0056): the whole
    decomposition is kept, so each fold's is cut per setting.
    """
    pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(), LogisticRegression()])
    search = sq.search(
        pipe, params={"pca__n_components": [1, 2, 3]}, folds=sq.folds.kfold(3)
    )
    search.train(labelled(), target="y")
    assert dict(STORE.learns) == {"standard": 4, "pca": 4}


def test_pca_after_a_dynamic_step():
    """PCA decomposes onehot's columns; a later step sees only its outputs.

    Onehot's columns sum to 1, so the fifth component has variance 0 and
    is ill-defined (spec §7): four are kept.
    """
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "a": rng.normal(size=12),
            "b": rng.normal(size=12),
            "city": ["x", "y", "z"] * 4,
        }
    )
    pipe = sq.Pipeline(
        [sq.encode.onehot("city"), sq.decompose.pca(n_components=4), sq.scale()]
    ).learn(frame)
    names = ["pca0", "pca1", "pca2", "pca3"]
    assert pipe.columns_out_ == names
    assert list(pipe[2].center_) == names
    encoded = pd.get_dummies(frame, columns=["city"], dtype=float)
    want = decomposition.PCA(4, svd_solver="covariance_eigh").fit_transform(encoded)
    want = StandardScaler().fit_transform(want)
    got = pipe.apply(frame, out="pandas")[names].to_numpy()
    np.testing.assert_allclose(got, want, atol=1e-9)


@pytest.mark.parametrize(
    "settings", [{}, {"n_components": 2}, {"n_components": 0.9, "whiten": True}]
)
def test_save_then_load_gives_the_same_output(tmp_path, settings):
    """A saved PCA loads and applies the same rows, with no learn."""
    frame = labelled().drop(columns="y")
    pipe = sq.Pipeline([sq.scale(), sq.decompose.pca(**settings)]).learn(frame)
    want = pipe.apply(frame).fetchall()
    sq.save(pipe, tmp_path / "p.json")
    STORE.clear()
    loaded = sq.load(tmp_path / "p.json")
    assert loaded.apply(frame).fetchall() == want
    assert loaded["pca"].components_ == pipe["pca"].components_
    assert not STORE.learns


def test_a_refusal_at_apply_is_placed_on_the_step():
    """Too many components set after learning is refused on the step at apply."""
    frame = labelled().drop(columns="y")
    pipe = sq.Pipeline([sq.scale(), sq.decompose.pca()]).learn(frame)
    pipe["pca"].n_components = 6
    with pytest.raises(StepError, match=r"pca \(step 2\).*Fix:") as raised:
        pipe.apply(frame)
    assert (raised.value.step, raised.value.position) == ("pca", 2)

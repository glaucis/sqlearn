"""Tests of the bundled datasets: iris, wine and breast cancer."""

import duckdb
import pandas as pd
import pytest
from sklearn import datasets as sk

import sqlearn as sq

BUNDLED = [
    ("iris", sq.datasets.iris, sk.load_iris, 150, 4, {0, 1, 2}),
    ("wine", sq.datasets.wine, sk.load_wine, 178, 13, {0, 1, 2}),
    (
        "breast_cancer",
        sq.datasets.breast_cancer,
        sk.load_breast_cancer,
        569,
        30,
        {0, 1},
    ),
]
IDS = [b[0] for b in BUNDLED]


@pytest.mark.parametrize(
    ("name", "make", "load", "rows", "features", "classes"), BUNDLED, ids=IDS
)
def test_dataset_has_its_rows_features_and_a_target(
    name, make, load, rows, features, classes
):
    """Each dataset has scikit-learn's feature names as DOUBLE, then a BIGINT target."""
    rel = make()
    names = list(load(as_frame=True).frame.columns)
    assert rel.columns == names
    assert len(names) == features + 1
    assert [str(t) for t in rel.types] == ["DOUBLE"] * features + ["BIGINT"]
    assert rel.count("*").fetchall()[0][0] == rows
    assert {r[0] for r in rel.project('"target"').distinct().fetchall()} == classes


@pytest.mark.parametrize(("name", "make", "load"), [b[:3] for b in BUNDLED], ids=IDS)
def test_bundled_datasets_equal_scikit_learns(name, make, load):
    """Each dataset equals scikit-learn's frame value for value, in row order."""
    expected = load(as_frame=True).frame
    got = make().df()
    pd.testing.assert_frame_equal(got, expected, check_exact=True, check_dtype=False)


@pytest.mark.parametrize("make", [sq.datasets.iris, sq.datasets.blobs], ids=repr)
def test_a_dataset_lands_on_the_configured_connection_and_calls_are_independent(make):
    """A dataset is built on the set connection; two calls give separate relations."""
    other = duckdb.connect()
    sq.set_config(connection=other)
    first, second = make(), make()
    assert first is not second
    assert (
        other.sql("SELECT count(*) FROM first").fetchall()
        == first.count("*").fetchall()
    )
    assert first.fetchall() == second.fetchall()

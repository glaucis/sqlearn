"""Tests of the generators written in SQL: blobs, regression, classification."""

import threading

import numpy as np
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError

GENERATORS = [sq.datasets.blobs, sq.datasets.regression, sq.datasets.classification]


def _refused(make, **settings) -> str:
    """Return the message of the refusal `make(**settings)` raises."""
    with pytest.raises(SqlearnError) as raised:
        make(**settings)
    message = str(raised.value)
    assert "Why:" in message
    assert "Fix:" in message
    return message


def test_blobs_gives_rows_features_and_a_target():
    """Blobs has n_features DOUBLE columns x0, x1, ..., then a BIGINT target."""
    rel = sq.datasets.blobs(rows=500, n_features=3, centers=4, seed=1)
    assert rel.columns == ["x0", "x1", "x2", "target"]
    assert [str(t) for t in rel.types] == ["DOUBLE"] * 3 + ["BIGINT"]
    assert rel.count("*").fetchall()[0][0] == 500
    targets = {r[0] for r in rel.project("target").distinct().fetchall()}
    assert targets == {0, 1, 2, 3}


def test_blobs_rows_cluster_round_their_centres():
    """With a small spread, every row lies within 1 of its target's centre."""
    centres = [[0.0, 0.0], [5.0, 5.0]]
    rows = sq.datasets.blobs(
        rows=10_000, centers=centres, cluster_std=0.1, seed=3
    ).fetchall()
    assert len(rows) == 10_000
    for x0, x1, target in rows:
        c0, c1 = centres[target]
        assert abs(x0 - c0) < 1
        assert abs(x1 - c1) < 1
    assert {r[2] for r in rows} == {0, 1}


def test_blobs_centres_given_as_points_set_the_features():
    """Centres given as points set the number of features, as scikit-learn's do."""
    rel = sq.datasets.blobs(rows=10, centers=[[0, 0, 0], [1, 1, 1]])
    assert rel.columns == ["x0", "x1", "x2", "target"]


def test_blobs_take_one_spread_per_centre():
    """A spread per centre: a centre of spread 0 gives its rows exactly."""
    rows = sq.datasets.blobs(
        rows=200, centers=[[1.0, 2.0], [9.0, 9.0]], cluster_std=[0.0, 1.0], seed=2
    ).fetchall()
    assert all((x0, x1) == (1.0, 2.0) for x0, x1, t in rows if t == 0)
    assert any((x0, x1) != (9.0, 9.0) for x0, x1, t in rows if t == 1)


def test_blobs_centres_drawn_lie_in_the_box():
    """Centres drawn by count lie in center_box: with spread 0 so do the rows."""
    rows = sq.datasets.blobs(
        rows=300, centers=5, cluster_std=0.0, center_box=(2.0, 3.0), seed=4
    ).fetchall()
    assert all(2.0 <= v < 3.0 for r in rows for v in r[:2])
    assert len({r[:2] for r in rows}) == 5


def test_regression_gives_rows_features_and_a_target():
    """Regression has n_features DOUBLE columns, then a DOUBLE target."""
    rel = sq.datasets.regression(rows=50, n_features=4, n_informative=2)
    assert rel.columns == ["x0", "x1", "x2", "x3", "target"]
    assert [str(t) for t in rel.types] == ["DOUBLE"] * 5
    assert rel.count("*").fetchall()[0][0] == 50


def test_regression_target_is_the_linear_model_without_noise():
    """With noise=0, least squares recovers the target and n_informative weights."""
    data = sq.datasets.regression(
        rows=1_000, n_features=20, n_informative=5, bias=3.0, seed=6
    ).fetchnumpy()
    x = np.column_stack([data[f"x{j}"] for j in range(20)] + [np.ones(1_000)])
    y = data["target"]
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    assert np.max(np.abs(x @ coef - y)) < 1e-9
    assert np.count_nonzero(np.abs(coef[:20]) > 1e-6) == 5
    assert coef[20] == pytest.approx(3.0)
    assert all(0 <= c < 100 for c in coef[:5])


def test_regression_noise_spreads_the_target_round_the_model():
    """With noise, the residual of the least-squares fit has spread `noise`."""
    data = sq.datasets.regression(
        rows=5_000, n_features=3, n_informative=3, noise=2.0, seed=7
    ).fetchnumpy()
    x = np.column_stack([data[f"x{j}"] for j in range(3)] + [np.ones(5_000)])
    coef, *_ = np.linalg.lstsq(x, data["target"], rcond=None)
    # The sample spread's standard error is 2 / sqrt(2 * 5,000) = 0.02: 5 of them.
    assert np.std(data["target"] - x @ coef) == pytest.approx(2.0, abs=0.1)


@pytest.mark.parametrize("make", GENERATORS)
def test_one_row_is_given_and_zero_rows_are_refused(make):
    """rows=1 gives one row; rows=0 is refused, as scikit-learn refuses it."""
    assert make(rows=1).count("*").fetchall()[0][0] == 1
    assert "rows=0" in _refused(make, rows=0)


@pytest.mark.parametrize("make", GENERATORS)
@pytest.mark.parametrize("rows", [-5, 2.5, "100", True, None])
def test_rows_that_are_not_a_positive_whole_number_are_refused(make, rows):
    """rows must be an int of at least 1; a bool is not one."""
    assert f"rows={rows!r}" in _refused(make, rows=rows)


@pytest.mark.parametrize("make", GENERATORS)
@pytest.mark.parametrize("seed", [1.5, "0", True, None])
def test_a_seed_that_is_not_an_int_is_refused(make, seed):
    """The seed is an int; a float, text, a bool or None is refused."""
    assert f"seed={seed!r}" in _refused(make, seed=seed)


def test_any_int_seed_is_taken():
    """A negative or huge seed is taken, modulo 2**64."""
    assert sq.datasets.blobs(rows=2, seed=-1).fetchall() == (
        sq.datasets.blobs(rows=2, seed=2**64 - 1).fetchall()
    )


def test_the_same_seed_gives_the_same_rows_and_another_seed_others():
    """A seed fixes the rows; another seed gives other rows."""
    first = sq.datasets.regression(
        rows=20, n_features=3, n_informative=2, seed=5
    ).fetchall()
    assert (
        sq.datasets.regression(
            rows=20, n_features=3, n_informative=2, seed=5
        ).fetchall()
        == first
    )
    assert (
        sq.datasets.regression(
            rows=20, n_features=3, n_informative=2, seed=6
        ).fetchall()
        != first
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"n_features": 0},
        {"n_features": 2.0},
        {"centers": 0},
        {"centers": True},
        {"centers": []},
        {"centers": [[0, 0], [1]]},
        {"centers": [[0, "a"]]},
        {"centers": [[0, float("inf")]]},
        {"centers": "abc"},
        {"cluster_std": -0.1},
        {"cluster_std": float("nan")},
        {"cluster_std": [1.0, 2.0]},
        {"cluster_std": [1.0, -1.0, 1.0]},
        {"center_box": (1.0,)},
        {"center_box": (3.0, 1.0)},
        {"center_box": (0.0, float("inf"))},
    ],
    ids=repr,
)
def test_bad_blobs_settings_are_refused(settings):
    """Each bad blobs setting is refused in the house form, naming the setting."""
    name = next(iter(settings))
    assert name in _refused(sq.datasets.blobs, **settings)


@pytest.mark.parametrize(
    "settings",
    [
        {"n_features": 0},
        {"n_informative": -1},
        {"n_informative": 1.5},
        {"n_features": 3, "n_informative": 4},
        {"noise": -1.0},
        {"noise": float("nan")},
        {"noise": "1"},
        {"bias": float("inf")},
        {"bias": None},
    ],
    ids=repr,
)
def test_bad_regression_settings_are_refused(settings):
    """Each bad regression setting is refused in the house form, naming it."""
    name = list(settings)[-1]
    assert name in _refused(sq.datasets.regression, **settings)


def test_classification_gives_its_columns_in_order():
    """x0 to x19 (DOUBLE), then a BIGINT target holding the classes 0 to 2."""
    rel = sq.datasets.classification(rows=2_000, n_classes=3, n_informative=3, seed=1)
    assert rel.columns == [f"x{j}" for j in range(20)] + ["target"]
    assert [str(t) for t in rel.types] == ["DOUBLE"] * 20 + ["BIGINT"]
    assert rel.count("*").fetchall()[0][0] == 2_000
    targets = {r[0] for r in rel.project("target").distinct().fetchall()}
    assert targets == {0, 1, 2}


def test_classification_classes_follow_their_weights():
    """With flip_y=0, each class's share of the rows is its weight."""
    rel = sq.datasets.classification(
        rows=100_000, weights=[0.8, 0.2], flip_y=0.0, seed=2
    )
    counts = dict(rel.aggregate("target, count(*)").fetchall())
    # A share's standard error is sqrt(0.8 * 0.2 / 100,000) = 0.0013: 0.01 is 8.
    assert counts[0] / 100_000 == pytest.approx(0.8, abs=0.01)
    assert counts[1] / 100_000 == pytest.approx(0.2, abs=0.01)


def test_classification_takes_one_weight_fewer_than_classes():
    """With n_classes - 1 weights, the last class takes what they leave."""
    rel = sq.datasets.classification(
        rows=100_000,
        n_classes=3,
        n_informative=3,
        weights=[0.5, 0.1],
        flip_y=0.0,
        seed=3,
    )
    counts = dict(rel.aggregate("target, count(*)").fetchall())
    assert counts[2] / 100_000 == pytest.approx(0.4, abs=0.01)


def test_classification_weights_below_one_in_all_are_proportions():
    """n_classes weights summing below 1 give the classes in their proportion."""
    rel = sq.datasets.classification(
        rows=100_000, weights=[0.3, 0.1], flip_y=0.0, seed=3
    )
    counts = dict(rel.aggregate("target, count(*)").fetchall())
    assert counts[0] / 100_000 == pytest.approx(0.75, abs=0.01)


def test_redundant_features_are_combinations_of_the_informative_ones():
    """Least squares on the informative features gives each redundant one."""
    n_informative, n_redundant = 3, 4
    data = sq.datasets.classification(
        rows=2_000,
        n_features=9,
        n_informative=n_informative,
        n_redundant=n_redundant,
        seed=4,
    ).fetchnumpy()
    x = np.column_stack([data[f"x{j}"] for j in range(n_informative)])
    for j in range(n_informative, n_informative + n_redundant):
        coef, *_ = np.linalg.lstsq(x, data[f"x{j}"], rcond=None)
        assert np.max(np.abs(x @ coef - data[f"x{j}"])) < 1e-9
        assert np.all(np.abs(coef) <= 1)
    # The noise features are not such combinations.
    coef, *_ = np.linalg.lstsq(x, data["x8"], rcond=None)
    assert np.max(np.abs(x @ coef - data["x8"])) > 1


def test_informative_features_sit_round_hypercube_vertices():
    """Each cluster's mean lies at a distinct vertex, every coordinate ±class_sep."""
    data = sq.datasets.classification(
        rows=20_000,
        n_features=3,
        n_informative=3,
        n_redundant=0,
        n_classes=4,
        n_clusters_per_class=2,
        flip_y=0.0,
        class_sep=5.0,
        seed=5,
    ).fetchnumpy()
    x = np.column_stack([data["x0"], data["x1"], data["x2"]])
    # A cluster's spread is below 3 per coordinate (each a sum of three
    # products of a standard normal and a number in [-1, 1)), so rounding each
    # coordinate to ±5 finds the vertex of almost every row.
    vertices = {tuple(v) for v in np.where(x > 0, 5.0, -5.0)}
    assert len(vertices) == 8


def test_flip_y_flips_that_share():
    """flip_y=0.5 redraws half the labels; half of those land on the other class."""
    kept, flipped = (
        sq.datasets.classification(
            rows=100_000, n_features=4, flip_y=flip_y, seed=6
        ).fetchnumpy()
        for flip_y in (0.0, 0.5)
    )
    for j in range(4):
        assert np.array_equal(kept[f"x{j}"], flipped[f"x{j}"])
    differ = np.mean(kept["target"] != flipped["target"])
    # The standard error is sqrt(0.25 * 0.75 / 100,000) = 0.0014: 0.01 is 7.
    assert differ == pytest.approx(0.25, abs=0.01)


def test_classification_with_one_class_gives_class_zero():
    """n_classes=1 is taken, as scikit-learn takes it: every target is 0."""
    rel = sq.datasets.classification(rows=50, n_classes=1, flip_y=0.5)
    assert rel.project("target").distinct().fetchall() == [(0,)]


@pytest.mark.parametrize(
    "settings",
    [
        {"n_features": 0},
        {"n_informative": 0},
        {"n_informative": 2.0},
        {"n_redundant": -1},
        {"n_features": 3, "n_informative": 2, "n_redundant": 2},
        {"n_features": 5, "n_informative": 6, "n_redundant": 0},
        {"n_classes": 0},
        {"n_clusters_per_class": 0},
        {"n_classes": 3, "n_clusters_per_class": 2, "n_informative": 2},
        {"n_classes": 3, "n_informative": 3, "weights": [0.5, 0.2, 0.2, 0.1]},
        {"n_classes": 3, "n_informative": 3, "weights": [1.0]},
        {"weights": [0.7, 0.4]},
        {"n_classes": 3, "n_informative": 3, "weights": [0.7, 0.4]},
        {"weights": [0.5, -0.1]},
        {"weights": [0.0, 0.0]},
        {"weights": [0.5, float("nan")]},
        {"weights": [0.5, "a"]},
        {"weights": 0.5},
        {"flip_y": -0.1},
        {"flip_y": 1.5},
        {"flip_y": "0.1"},
        {"class_sep": 0.0},
        {"class_sep": -1.0},
        {"class_sep": float("inf")},
    ],
    ids=repr,
)
def test_bad_classification_settings_are_refused(settings):
    """Each bad classification setting is refused in the house form, naming it."""
    name = list(settings)[-1]
    assert name in _refused(sq.datasets.classification, **settings)


def test_classification_takes_numpy_weights():
    """Weights may be a numpy array, as a list may."""
    with_array = sq.datasets.classification(
        rows=50,
        weights=np.array([0.3, 0.7]),  # ty: ignore[invalid-argument-type]
        seed=7,
    )
    with_list = sq.datasets.classification(rows=50, weights=[0.3, 0.7], seed=7)
    assert with_array.fetchall() == with_list.fetchall()


@pytest.mark.parametrize("make", GENERATORS)
def test_a_slice_equals_the_whole(make):
    """The first 1,000 rows of 1,000,000 equal a relation of 1,000 rows."""
    whole = make(rows=1_000_000, seed=9)
    assert whole.limit(1_000).fetchall() == (make(rows=1_000, seed=9).fetchall())


def test_the_same_seed_gives_the_same_rows_on_any_thread_count():
    """One thread and eight give the same blobs, bit for bit on one machine."""
    con = connection()
    before = con.sql("SELECT current_setting('threads')").fetchall()[0][0]
    try:
        con.execute("SET threads = 1")
        one = sq.datasets.blobs(rows=100_000, seed=8).fetchall()
        con.execute("SET threads = 8")
        eight = sq.datasets.blobs(rows=100_000, seed=8).fetchall()
    finally:
        con.execute(f"SET threads = {before}")
    assert one == eight


def test_a_trillion_rows_are_created_at_once():
    """rows=10**12 builds nothing; its first rows come back without a full scan.

    A full scan would run for days, so the guard is generous (a minute) and
    only catches that. Creating the relation and reading its plan sit inside
    the guard too, so an eager build fails rather than hangs; the plan holds
    no sort or aggregate over the whole.
    """
    got: list[tuple[object, ...]] = []
    plans: list[str] = []

    def build_and_fetch() -> None:
        rel = sq.datasets.blobs(rows=10**12, seed=2)
        plans.append(rel.explain().upper())
        got.extend(rel.limit(3).fetchall())

    fetch = threading.Thread(target=build_and_fetch)
    fetch.start()
    fetch.join(timeout=60)
    if fetch.is_alive():
        connection().interrupt()
        fetch.join()
        pytest.fail("a trillion rows were built or scanned, not taken lazily")
    assert "ORDER" not in plans[0]
    assert "AGGREGATE" not in plans[0]
    assert got == sq.datasets.blobs(rows=3, seed=2).fetchall()


def test_rows_reaching_the_constants_rows_are_refused():
    """rows=2**63 is refused: data rows stay below the constants' rows."""
    message = _refused(sq.datasets.blobs, rows=2**63)
    assert "2**63" in message
    assert (
        sq.datasets.regression(rows=2**63 - 1, n_features=1, n_informative=1)
        .limit(1)
        .fetchall()
    )


def test_numpy_whole_numbers_are_taken_as_rows_and_seed():
    """numpy's integers are whole numbers: rows, seed and counts take them."""
    # The annotations say int, as scikit-learn's do; numpy's are taken at run time.
    rel = sq.datasets.blobs(
        rows=np.int64(5),  # ty: ignore[invalid-argument-type]
        n_features=np.int32(3),  # ty: ignore[invalid-argument-type]
        centers=np.int64(2),  # ty: ignore[invalid-argument-type]
        seed=np.int64(4),  # ty: ignore[invalid-argument-type]
    )
    assert (
        rel.fetchall()
        == sq.datasets.blobs(rows=5, n_features=3, centers=2, seed=4).fetchall()
    )


def test_numpy_arrays_are_taken_as_centres_spreads_and_box():
    """Centres, spreads and the box may be numpy arrays, as lists are."""
    centres = [[0.0, 1.0], [5.0, 6.0]]
    with_arrays = sq.datasets.blobs(
        rows=50,
        centers=np.array(centres),  # ty: ignore[invalid-argument-type]
        cluster_std=np.array([0.5, 1.0]),  # ty: ignore[invalid-argument-type]
        center_box=np.array([-1.0, 1.0]),  # ty: ignore[invalid-argument-type]
        seed=3,
    )
    with_lists = sq.datasets.blobs(
        rows=50, centers=centres, cluster_std=[0.5, 1.0], center_box=(-1.0, 1.0), seed=3
    )
    assert with_arrays.fetchall() == with_lists.fetchall()


def test_a_setting_of_the_wrong_type_is_refused_naming_its_type():
    """A refusal for the type names the type given, not only the value."""
    message = _refused(sq.datasets.regression, n_features="2")
    assert "n_features='2' (a str)" in message

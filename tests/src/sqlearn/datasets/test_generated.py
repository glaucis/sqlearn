"""Tests of the generators written in SQL: blobs, regression and the others."""

import threading
import warnings
from typing import Any, cast

import numpy as np
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.errors import SqlearnError, SqlearnWarning

GENERATORS = [
    sq.datasets.blobs,
    sq.datasets.regression,
    sq.datasets.classification,
    sq.datasets.customers,
]


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


def test_regression_informative_defaults_to_the_features_it_has():
    """With few features, n_informative defaults to all of them."""
    data = sq.datasets.regression(rows=500, n_features=5, seed=2).fetchnumpy()
    x = np.column_stack([data[f"x{j}"] for j in range(5)])
    coef, *_ = np.linalg.lstsq(x, data["target"], rcond=None)
    assert np.count_nonzero(np.abs(coef) > 1e-6) == 5


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


def test_regression_clips_an_explicit_n_informative_with_a_warning():
    """An n_informative above n_features is clipped, with a warning to fix it."""
    with pytest.warns(SqlearnWarning) as caught:
        clipped = sq.datasets.regression(rows=50, n_features=5, n_informative=8, seed=0)
    assert len(caught) == 1
    message = str(caught[0].message)
    assert "n_informative=8" in message
    assert "using 5" in message
    assert "Fix:" in message
    assert caught[0].filename == __file__
    exact = sq.datasets.regression(rows=50, n_features=5, n_informative=5, seed=0)
    assert clipped.fetchall() == exact.fetchall()


def test_regression_with_default_n_informative_does_not_warn():
    """The default n_informative is never warned about, even with few features."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sq.datasets.regression(n_features=5)


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


def test_classification_shares_the_rest_of_the_weights_equally():
    """Weights summing below 1 leave the rest to the classes equally, as scikit-learn.

    scikit-learn deals the rows the weights leave round-robin over every
    cluster: [0.3, 0.1] leaves 0.6, half of it to each class.
    """
    rel = sq.datasets.classification(
        rows=100_000, weights=[0.3, 0.1], flip_y=0.0, seed=3
    )
    counts = dict(rel.aggregate("target, count(*)").fetchall())
    assert counts[0] / 100_000 == pytest.approx(0.6, abs=0.01)
    assert counts[1] / 100_000 == pytest.approx(0.4, abs=0.01)


def test_classification_weights_of_zero_give_equal_classes():
    """Weights all 0 leave the whole to share, so the classes come out equal."""
    rel = sq.datasets.classification(
        rows=100_000, weights=[0.0, 0.0], flip_y=0.0, seed=3
    )
    counts = dict(rel.aggregate("target, count(*)").fetchall())
    assert counts[0] / 100_000 == pytest.approx(0.5, abs=0.01)


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
    """Each row lies near a vertex of ±class_sep, whose rows all carry one class.

    With class_sep=20 the clusters stand far apart: a coordinate's spread
    round its vertex is at most sqrt(3) (three standard normals, each times a
    number in [-1, 1)), so within 10 holds past five standard deviations.
    Each class has n_clusters_per_class vertices, each vertex one cluster.
    """
    sep, n_classes, per_class = 20.0, 4, 2
    data = sq.datasets.classification(
        rows=5_000,
        n_features=3,
        n_informative=3,
        n_redundant=0,
        n_classes=n_classes,
        n_clusters_per_class=per_class,
        flip_y=0.0,
        class_sep=sep,
        seed=5,
    ).fetchnumpy()
    x = np.column_stack([data["x0"], data["x1"], data["x2"]])
    nearest = np.where(x > 0, sep, -sep)
    assert np.max(np.abs(x - nearest)) < 10
    classes: dict[tuple[float, ...], set[int]] = {}
    for vertex, target in zip(map(tuple, nearest), data["target"], strict=True):
        classes.setdefault(vertex, set()).add(int(target))
    assert len(classes) == n_classes * per_class
    assert all(len(held) == 1 for held in classes.values())
    owners = [next(iter(held)) for held in classes.values()]
    assert sorted(owners) == sorted(list(range(n_classes)) * per_class)


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


def test_customers_has_its_columns_and_types():
    """Five columns, `target` last and the only one of that name."""
    rel = sq.datasets.customers(rows=500, seed=1)
    assert rel.columns == ["age", "income", "city", "plan", "target"]
    assert [str(t) for t in rel.types] == [
        "DOUBLE",
        "DOUBLE",
        "VARCHAR",
        "VARCHAR",
        "BIGINT",
    ]
    assert rel.count("*").fetchall()[0][0] == 500
    assert {r[0] for r in rel.project("target").distinct().fetchall()} == {0, 1}


def test_customers_have_the_promised_gaps_and_shares():
    """A tenth of age and a twentieth of income are NULL; the shares hold."""
    n = 100_000
    rel = sq.datasets.customers(rows=n, seed=3)
    row = rel.aggregate(
        "avg((age IS NULL)::DOUBLE), avg((income IS NULL)::DOUBLE),"
        " avg((plan = 'basic')::DOUBLE), avg((plan = 'plus')::DOUBLE),"
        " avg((plan = 'pro')::DOUBLE), avg((city = 'Oslo')::DOUBLE),"
        " avg((city = 'Cairo')::DOUBLE), count(city), count(plan)"
    ).fetchall()[0]
    assert row[0] == pytest.approx(0.1, abs=0.005)
    assert row[1] == pytest.approx(0.05, abs=0.005)
    for share, promised in zip(row[2:5], (0.5, 0.3, 0.2), strict=True):
        assert share == pytest.approx(promised, abs=0.01)
    assert row[5] == pytest.approx(0.25, abs=0.01)
    assert row[6] == pytest.approx(0.25, abs=0.01)
    assert row[7] == row[8] == n  # text has no gaps
    cities = {r[0] for r in rel.project("city").distinct().fetchall()}
    assert cities == {"Oslo", "Lima", "Kyoto", "Cairo"}


def test_customers_age_and_income_follow_their_distributions():
    """Age is normal (40, 12); the log of income is normal (10.5, 0.5)."""
    rel = sq.datasets.customers(rows=100_000, seed=4)
    mean, sd, lmean, lsd = rel.aggregate(
        "avg(age), stddev_samp(age), avg(ln(income)), stddev_samp(ln(income))"
    ).fetchall()[0]
    assert mean == pytest.approx(40, abs=0.3)
    assert sd == pytest.approx(12, abs=0.3)
    assert lmean == pytest.approx(10.5, abs=0.01)
    assert lsd == pytest.approx(0.5, abs=0.01)


def test_customers_target_follows_plan_city_and_income():
    """Basic plans churn more, high incomes less: the example's signal."""
    rel = sq.datasets.customers(rows=100_000, seed=5)
    by_plan = dict(rel.aggregate("plan, avg(target)").fetchall())
    assert by_plan["basic"] > by_plan["pro"] + 0.1
    high, low = (
        rel.filter(f"income {op} exp(10.5)").aggregate("avg(target)").fetchall()[0][0]
        for op in (">", "<")
    )
    assert low > high + 0.1


def test_a_pipeline_learns_customers_end_to_end():
    """Impute, one-hot, scale, then a logistic regression beats the majority."""
    from sklearn.linear_model import LogisticRegression

    train = sq.datasets.customers(rows=2_000, seed=0)
    pipe = sq.Pipeline(
        [
            sq.impute.median(),
            sq.encode.onehot(),
            sq.scale.standard(),
            sq.Model(LogisticRegression(max_iter=1_000)),
        ]
    )
    pipe.train(train, target="target")
    # Others: rows 2,000 to 3,000 of the same seed's stream.
    others = sq.datasets.customers(rows=3_000, seed=0).limit(1_000, offset=2_000)
    predicted = pipe.predict(others, out="pandas")
    truth = others.project("target").fetchnumpy()["target"]
    guessed = np.asarray(predicted).ravel()
    accuracy = float(np.mean(guessed == truth))
    majority = max(np.mean(truth), 1 - np.mean(truth))
    assert accuracy > majority + 0.02


@pytest.mark.slow
def test_a_pipeline_learns_ten_million_rows_under_64_mb():
    """Median imputing then standard scaling learn from 10**7 rows in 64 MB.

    The budget of 128 MB leaves DuckDB a memory limit of half, 64 MB. The
    exact median sorts, and on all threads 10**7 rows of two columns do not
    fit in 64 MB (docs/benchmarks/median-reach.md measures one thread): so
    the test sets one.
    """
    sq.set_config(memory="128MB")
    con = connection()
    con.execute("SET threads = 1")
    limit = con.sql("SELECT current_setting('memory_limit')").fetchall()[0][0]
    assert limit.startswith("61.0 MiB")  # 64 MB
    big = sq.datasets.customers(rows=10**7)
    pipe = sq.Pipeline([sq.impute.median(), sq.scale.standard()]).learn(big)
    assert pipe["standard"].center_ is not None


def test_ordered_rows_come_in_row_order_with_insertion_order_off():
    """ordered=True gives the rows of the row order, whatever DuckDB keeps.

    On DuckDB 2.0 no input was found that reorders the default relation with
    the setting off (200,000 to 6 million rows, 8 threads, a filter, Arrow):
    ``range()`` is read on one thread. So the equality below is a guard, not
    proof; the plan assertion carries the proof that the ordered relation
    sorts by the row number even with the setting off.
    """
    con = connection()
    setting = con.sql("SELECT current_setting('preserve_insertion_order')")
    previous = setting.fetchall()[0][0]
    threads = con.sql("SELECT current_setting('threads')").fetchall()[0][0]
    try:
        for make in GENERATORS:
            expected = make(rows=200_000, seed=0).fetchall()
            con.execute("SET preserve_insertion_order = false")
            con.execute("SET threads = 8")
            ordered = make(rows=200_000, seed=0, ordered=True)
            plan = ordered.explain().lower()
            got = ordered.fetchall()
            assert "order by" in plan, make.__name__
            assert got == expected, make.__name__
            con.execute(f"SET preserve_insertion_order = {str(previous).lower()}")
            con.execute(f"SET threads = {threads}")
    finally:
        con.execute(f"SET preserve_insertion_order = {str(previous).lower()}")
        con.execute(f"SET threads = {threads}")


def test_the_default_is_lazy_and_ordered_is_not():
    """Only ordered=True puts a sort in the plan."""
    for make in GENERATORS:
        lazy = make(rows=100).explain().lower()
        sorted_ = make(rows=100, ordered=True).explain().lower()
        assert "order by" not in lazy, make.__name__
        assert "order by" in sorted_, make.__name__


def test_ordered_is_refused_unless_a_bool():
    """A text, an int or None for ordered is refused in the house form."""
    for make in GENERATORS:
        for bad in ("yes", 1, None):
            message = _refused(make, rows=5, ordered=bad)
            assert "ordered" in message
        relation = make(rows=5, ordered=cast("Any", np.True_))
        assert relation.count("*").fetchall()[0][0] == 5

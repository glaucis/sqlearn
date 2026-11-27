"""Tests of the folds: a fold number from a hash of each row and a seed."""

import pytest
from sklearn.model_selection import TimeSeriesSplit

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn.model_selection.folds import ALIAS, Folds


def folds_of(rel, kfold):
    """Return each row's fold, in the relation's order."""
    return [k for (k,) in kfold.numbered(rel, "k").project("k").fetchall()]


def test_folds_are_balanced_and_repeatable():
    """100,000 rows: each fold within 1% of 20,000; the same row, the same fold."""
    rel = connection().sql("SELECT range AS i, range % 7 AS j FROM range(100000)")
    kfold = sq.folds.kfold(5, seed=0)
    first = folds_of(rel, kfold)
    counts = [first.count(k) for k in range(5)]
    assert all(abs(c - 20_000) <= 200 for c in counts), counts
    assert folds_of(rel, kfold) == first


def test_identical_rows_share_a_fold_and_the_seed_moves_them():
    """A row's fold depends on its values and the seed, not on its place."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (1, 'a')) t(x, y)",
    )
    folds = folds_of(rel, sq.folds.kfold(5, seed=0))
    assert folds[0] == folds[2]
    many = connection().sql("SELECT range AS i FROM range(100)")
    assert folds_of(many, sq.folds.kfold(5, seed=0)) != folds_of(
        many, sq.folds.kfold(5, seed=1)
    )


def test_the_expression_hashes_the_whole_row():
    """`expression` is ``hash(<alias>, <seed>) % <n>``, the alias quoted."""
    assert sq.folds.kfold(3, seed=7).expression("d") == 'hash("d", 7) % 3'


def test_training_and_held_out_rows_split_the_data():
    """Fold k holds out the rows numbered k and trains on the others."""
    rel = connection().sql("SELECT range AS i FROM range(1000)")
    kfold = sq.folds.kfold(4, seed=3)
    folds = dict(kfold.numbered(rel, "k").fetchall())
    for k in range(4):
        held = {i for (i,) in kfold.rows(rel, k, held=True).fetchall()}
        trained = {i for (i,) in kfold.rows(rel, k, held=False).fetchall()}
        assert held == {i for i, f in folds.items() if f == k}
        assert held | trained == set(range(1000))
        assert not held & trained


def test_kfold_refuses_bad_settings_and_shows_itself():
    """Fewer than two folds, or a seed that is not an integer, is refused."""
    with pytest.raises(sq.errors.SqlearnError, match="at least 2"):
        sq.folds.kfold(1)
    with pytest.raises(sq.errors.SqlearnError, match="seed"):
        sq.folds.kfold(5, seed=0.5)  # ty: ignore[invalid-argument-type]
    assert repr(sq.folds.kfold()) == "KFold(n=5, seed=0)"
    assert sq.folds.kfold(3, 1) == sq.folds.kfold(3, 1)
    assert len({sq.folds.kfold(3, 1), sq.folds.kfold(3, 1), sq.folds.kfold(3, 2)}) == 2
    assert sq.folds.kfold() != (5, 0)


def test_a_column_named_as_the_row_alias_is_refused():
    """The row alias must not be a column, or the hash would read the column."""
    rel = connection().sql(f'SELECT 1 AS "{ALIAS}"')
    with pytest.raises(sq.errors.SqlearnError, match=ALIAS):
        sq.folds.kfold().numbered(rel, "k")


def test_kfold_implements_the_scheme_interface():
    """KFold is a Folds: splits, a stable key, and two predicates per fold."""
    rel = connection().sql("SELECT * FROM range(20) t(i)")
    folds = sq.folds.kfold(4, seed=0)
    assert isinstance(folds, Folds) and folds.splits == 4
    assert folds.key == ("kfold", 4, 0)
    numbered = folds.numbered(rel, "f", None)
    held = [
        numbered.filter(folds.held("f", k)).count("*").fetchall()[0][0]
        for k in range(4)
    ]
    train = [
        numbered.filter(folds.training("f", k)).count("*").fetchall()[0][0]
        for k in range(4)
    ]
    assert sum(held) == 20 and all(
        h + t == 20 for h, t in zip(held, train, strict=True)
    )


def test_stratified_balances_each_class():
    """10% positives: every fold holds 20 of them in 200 rows."""
    rel = connection().sql("SELECT i, (i % 10 = 0)::INT AS y FROM range(1000) t(i)")
    numbered = sq.folds.stratified(5, seed=0).numbered(rel, "f", "y")
    per_fold = numbered.aggregate("f, sum(y) AS pos, count(*) AS n", "f").fetchall()
    assert sorted(r[1] for r in per_fold) == [20] * 5
    assert sorted(r[2] for r in per_fold) == [200] * 5


def test_stratified_needs_a_target_and_a_real_column():
    """Without a target, or with a missing one, the message says what to pass."""
    rel = connection().sql("SELECT 1 AS a")
    with pytest.raises(SqlearnError, match="target="):
        sq.folds.stratified().numbered(rel, "f", None)
    with pytest.raises(SqlearnError, match=r"columns: \['a'\]"):
        sq.folds.stratified().numbered(rel, "f", "zz")


def test_group_keeps_every_group_in_one_fold():
    """No group is spread over two folds."""
    rel = connection().sql("SELECT i, i // 7 AS customer FROM range(700) t(i)")
    numbered = sq.folds.group("customer", 5, seed=0).numbered(rel, "f", None)
    spread = numbered.aggregate("customer, count(DISTINCT f) AS k", "customer")
    assert spread.filter("k > 1").count("*").fetchall()[0][0] == 0


def test_group_names_the_columns_when_one_is_missing():
    """The message lists the columns the data has."""
    rel = connection().sql("SELECT 1 AS a, 2 AS b")
    with pytest.raises(SqlearnError, match=r"columns: \['a', 'b'\]"):
        sq.folds.group("zz").numbered(rel, "f", None)


def test_holdout_is_one_split_of_about_the_share():
    """One split, holding out about the share asked."""
    rel = connection().sql("SELECT * FROM range(10000) t(i)")
    folds = sq.folds.holdout(test=0.2, seed=0)
    held = (
        folds.numbered(rel, "f", None).filter(folds.held("f", 0)).count("*")
    ).fetchall()[0][0]
    assert folds.splits == 1 and 1900 < held < 2100


def test_holdout_rows_split_the_data():
    """The held-out and training rows are the data, apart, held about the share."""
    rel = connection().sql("SELECT * FROM range(10000) t(i)")
    folds = sq.folds.holdout(test=0.2, seed=0)
    held = {i for (i,) in folds.rows(rel, held=True).fetchall()}
    trained = {i for (i,) in folds.rows(rel, held=False).fetchall()}
    assert held | trained == set(range(10000))
    assert not held & trained
    assert 1900 < len(held) < 2100
    numbered = dict(folds.numbered(rel, "f").fetchall())
    assert held == {i for i, f in numbered.items() if f == 0}
    assert {i for (i,) in folds.rows(rel, 0, held=True).fetchall()} == held
    assert {i for (i,) in folds.rows(rel, held=True).fetchall()} == held
    assert folds.rows(rel, held=True).columns == ["i"]


def test_holdout_rows_keep_identical_rows_together():
    """A row's side is a hash of its values: copies of it fall on one side."""
    rel = connection().sql(
        "SELECT a.range AS x, a.range::VARCHAR AS y FROM range(20) a, range(50) b"
    )
    folds = sq.folds.holdout(test=0.5, seed=0)
    held = folds.rows(rel, held=True).fetchall()
    trained = folds.rows(rel, held=False).fetchall()
    assert held and trained  # both sides hold distinct rows
    assert not set(held) & set(trained)
    assert all(held.count(r) == 50 for r in set(held))
    assert all(trained.count(r) == 50 for r in set(trained))
    assert len(held) + len(trained) == 1000


@pytest.mark.parametrize(
    "folds", [sq.folds.holdout(test=0.5, seed=0), sq.folds.kfold(2, seed=0)]
)
def test_rows_keep_columns_differing_only_by_case(folds):
    """Columns a and A both come back with their own values."""
    rel = connection().sql("SELECT range AS a, range + 100 AS A FROM range(40)")
    both = folds.rows(rel, 0, held=True).fetchall() + (
        folds.rows(rel, 0, held=False).fetchall()
    )
    assert sorted(both) == [(i, i + 100) for i in range(40)]


@pytest.mark.parametrize("k", [1, -1, True, 0.0])
def test_holdout_rows_refuse_a_fold_other_than_zero(k):
    """A holdout has one split, fold 0: any other k is refused."""
    rel = connection().sql("SELECT 1 AS a")
    with pytest.raises(SqlearnError, match="only fold 0"):
        sq.folds.holdout().rows(rel, k, held=True)


def test_holdout_rows_refuse_the_row_alias():
    """A column named as the row alias is refused, as for numbered."""
    rel = connection().sql(f'SELECT 1 AS "{ALIAS}"')
    with pytest.raises(SqlearnError, match="rename"):
        sq.folds.holdout().rows(rel, held=True)


@pytest.mark.parametrize("test", [0, 1, -0.1, 1.5, True, "a"])
def test_holdout_refuses_a_share_outside_zero_and_one(test):
    """A share of 0, 1 or beyond, or not a number, is refused."""
    with pytest.raises(SqlearnError, match="test="):
        sq.folds.holdout(test=test)


def test_new_schemes_have_reprs_keys_and_equality():
    """Reprs, keys, equality and the protocol hold for each scheme."""
    assert repr(sq.folds.stratified(3, 1)) == "Stratified(n=3, seed=1)"
    assert repr(sq.folds.group("c", 3)) == "Grouped(by='c', n=3, seed=0)"
    assert repr(sq.folds.holdout(0.3)) == "Holdout(test=0.3, seed=0)"
    assert sq.folds.stratified().key == ("stratified", 5, 0)
    assert sq.folds.group("c").key == ("group", "c", 5, 0)
    assert sq.folds.holdout().key == ("holdout", 0.2, 0)
    assert sq.folds.group("c") == sq.folds.group("c", 5, 0)
    assert sq.folds.group("c") != sq.folds.group("d")
    assert hash(sq.folds.holdout()) == hash(sq.folds.holdout(0.2, 0))
    for scheme in (sq.folds.stratified(), sq.folds.group("c"), sq.folds.holdout()):
        assert isinstance(scheme, Folds)


def test_new_schemes_refuse_bad_settings():
    """Bad fold counts, seeds and group columns are refused."""
    with pytest.raises(SqlearnError, match="n=1"):
        sq.folds.stratified(1)
    with pytest.raises(SqlearnError, match="seed="):
        sq.folds.group("c", seed=1.5)  # ty: ignore[invalid-argument-type]
    with pytest.raises(SqlearnError, match="by="):
        sq.folds.group(3)  # ty: ignore[invalid-argument-type]


def test_stratified_keeps_fold_sizes_within_one_row_with_many_small_classes():
    """200 classes of 3 rows: every fold's size is within one of the others."""
    rel = connection().sql("SELECT i, i // 3 AS y FROM range(600) t(i)")
    numbered = sq.folds.stratified(5, seed=0).numbered(rel, "f", "y")
    sizes = [n for _, n in numbered.aggregate("f, count(*) AS n", "f").fetchall()]
    assert len(sizes) == 5 and max(sizes) - min(sizes) <= 1
    rel = connection().sql("SELECT i, i // 3 AS y FROM range(601) t(i)")
    numbered = sq.folds.stratified(5, seed=0).numbered(rel, "f", "y")
    sizes = [n for _, n in numbered.aggregate("f, count(*) AS n", "f").fetchall()]
    assert max(sizes) - min(sizes) <= 1
    per_class = numbered.aggregate("y, f, count(*) AS n", "y, f").aggregate(
        "y, max(n) - min(n) AS spread", "y"
    )
    assert per_class.filter("spread > 1").count("*").fetchall()[0][0] == 0


def test_time_matches_time_series_split_without_ties():
    """Shuffled rows, no ties: the same train and test rows as scikit-learn."""
    rel = connection().sql("SELECT i AS t FROM range(103) r(i) ORDER BY hash(i)")
    folds = sq.folds.time("t", 4, gap=2)
    numbered = folds.numbered(rel, "f", None)
    for k, (train, test) in enumerate(TimeSeriesSplit(4, gap=2).split(range(103))):
        got_train = sorted(
            r[0]
            for r in numbered.filter(folds.training("f", k)).project("t").fetchall()
        )
        got_test = sorted(
            r[0] for r in numbered.filter(folds.held("f", k)).project("t").fetchall()
        )
        assert got_train == list(train)
        assert got_test == list(test)


def test_time_keeps_a_tie_on_one_side():
    """Rows sharing a day are never split between learning and scoring."""
    rel = connection().sql("SELECT i // 10 AS day FROM range(100) r(i)")
    folds = sq.folds.time("day", 3)
    numbered = folds.numbered(rel, "f", None)
    for k in range(3):
        train_days = {
            r[0]
            for r in numbered.filter(folds.training("f", k)).project("day").fetchall()
        }
        test_days = {
            r[0] for r in numbered.filter(folds.held("f", k)).project("day").fetchall()
        }
        assert test_days
        assert not train_days & test_days


def test_time_names_its_settings_and_refuses_bad_ones():
    """Key, repr, equality, and refusals of bad settings and data."""
    folds = sq.folds.time("t", 4, gap=1)
    assert folds.splits == 4
    assert folds.key == ("time", "t", 4, 1)
    assert repr(folds) == "TimeSplit(by='t', n=4, gap=1)"
    assert folds == sq.folds.time("t", 4, 1)
    assert isinstance(folds, Folds)
    with pytest.raises(SqlearnError, match="n=1"):
        sq.folds.time("t", 1)
    with pytest.raises(SqlearnError, match="gap="):
        sq.folds.time("t", gap=-1)
    with pytest.raises(SqlearnError, match="by="):
        sq.folds.time(3)  # ty: ignore[invalid-argument-type]
    rel = connection().sql("SELECT i AS t FROM range(5) r(i)")
    with pytest.raises(SqlearnError, match="'u'"):
        sq.folds.time("u").numbered(rel, "f", None)
    nulls = connection().sql("SELECT NULLIF(i, 2) AS t FROM range(5) r(i)")
    with pytest.raises(SqlearnError, match="NULL in 't'"):
        sq.folds.time("t").numbered(nulls, "f", None)


def test_stratified_puts_identical_rows_in_one_fold():
    """Ten identical rows per class, among distinct ones, land in one fold each."""
    rel = connection().sql(
        "SELECT -1 AS i, c AS y FROM range(3) t(c), range(10) "
        "UNION ALL SELECT i, i % 3 AS y FROM range(90) t(i)"
    )
    numbered = sq.folds.stratified(5, seed=0).numbered(rel, "f", "y")
    spread = numbered.filter("i = -1").aggregate("y, count(DISTINCT f) AS k", "y")
    assert sorted(spread.fetchall()) == [(0, 1), (1, 1), (2, 1)]

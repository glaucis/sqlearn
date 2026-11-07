"""Tests of the folds: a fold number from a hash of each row and a seed."""

import pytest

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

"""Tests of the folds: a fold number from a hash of each row and a seed."""

import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn.model_selection.folds import ALIAS


def folds_of(rel, kfold):
    """Return each row's fold, in the relation's order."""
    return [k for (k,) in kfold.numbered(rel, "k").project("k").fetchall()]


def test_folds_are_balanced_and_repeatable():
    """100,000 rows: each fold within 1% of 20,000; the same row, the same fold."""
    rel = connection().sql("SELECT range AS i, range % 7 AS j FROM range(100000)")
    kfold = sq.KFold(5, seed=0)
    first = folds_of(rel, kfold)
    counts = [first.count(k) for k in range(5)]
    assert all(abs(c - 20_000) <= 200 for c in counts), counts
    assert folds_of(rel, kfold) == first


def test_identical_rows_share_a_fold_and_the_seed_moves_them():
    """A row's fold depends on its values and the seed, not on its place."""
    rel = connection().sql(
        "SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (1, 'a')) t(x, y)",
    )
    folds = folds_of(rel, sq.KFold(5, seed=0))
    assert folds[0] == folds[2]
    many = connection().sql("SELECT range AS i FROM range(100)")
    assert folds_of(many, sq.KFold(5, seed=0)) != folds_of(many, sq.KFold(5, seed=1))


def test_the_expression_hashes_the_whole_row():
    """`expression` is ``hash(<alias>, <seed>) % <n>``, the alias quoted."""
    assert sq.KFold(3, seed=7).expression("d") == 'hash("d", 7) % 3'


def test_training_and_held_out_rows_split_the_data():
    """Fold k holds out the rows numbered k and trains on the others."""
    rel = connection().sql("SELECT range AS i FROM range(1000)")
    kfold = sq.KFold(4, seed=3)
    folds = dict(kfold.numbered(rel, "k").fetchall())
    for k in range(4):
        held = {i for (i,) in kfold.rows(rel, k, held=True).fetchall()}
        trained = {i for (i,) in kfold.rows(rel, k, held=False).fetchall()}
        assert held == {i for i, f in folds.items() if f == k}
        assert held | trained == set(range(1000))
        assert not held & trained


def test_kfold_refuses_bad_settings_and_shows_itself():
    """Fewer than two folds, or a seed that is not an integer, is refused."""
    with pytest.raises(sq.SqlearnError, match="at least 2"):
        sq.KFold(1)
    with pytest.raises(sq.SqlearnError, match="seed"):
        sq.KFold(5, seed=0.5)  # ty: ignore[invalid-argument-type]
    assert repr(sq.KFold()) == "KFold(n=5, seed=0)"
    assert sq.KFold(3, 1) == sq.KFold(3, 1)
    assert len({sq.KFold(3, 1), sq.KFold(3, 1), sq.KFold(3, 2)}) == 2
    assert sq.KFold() != (5, 0)


def test_a_column_named_as_the_row_alias_is_refused():
    """The row alias must not be a column, or the hash would read the column."""
    rel = connection().sql(f'SELECT 1 AS "{ALIAS}"')
    with pytest.raises(sq.SqlearnError, match=ALIAS):
        sq.KFold().numbered(rel, "k")

"""Tests of the folds: a fold number from a hash of each row and a seed."""

import pytest

import sqlearn as sq
from sqlearn._config import connection
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

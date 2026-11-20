"""Tests of the Gram learn: XᵀX of the centred rows, built in numpy."""

from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
import sqlearn._pipeline
from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn._gram import batch_rows, check_fits, gram_matrix
from sqlearn._memory import allowance


def test_gram_matrix_matches_numpy_on_centred_rows():
    """XᵀX of the centred rows is numpy's covariance times n - 1."""
    rng = np.random.default_rng(0)
    data = rng.normal(size=(1_000, 3)) * [1.0, 10.0, 0.1] + [5.0, -3.0, 100.0]
    con = connection()
    frame = pd.DataFrame(data, columns=["x", "y", "z"])  # noqa: F841  (read by DuckDB)
    con.execute("CREATE OR REPLACE TEMP TABLE gram_rows AS SELECT * FROM frame")
    means = dict(zip("xyz", data.mean(axis=0).tolist(), strict=True))
    got = gram_matrix(con, "SELECT * FROM gram_rows", ["x", "y", "z"], means)
    want = np.cov(data, rowvar=False, bias=False) * (len(data) - 1)
    assert got == pytest.approx(want, rel=1e-12)


def test_gram_matrix_keeps_columns_differing_only_by_case():
    """Columns ``a`` and ``A`` are two columns, each read as itself."""
    con = connection()
    sql = 'SELECT 1.0 AS a, 10.0 AS "A" UNION ALL SELECT 3.0, 50.0'
    got = gram_matrix(con, sql, ["a", "A"], {"a": 2.0, "A": 30.0})
    assert got == pytest.approx(np.array([[2.0, 40.0], [40.0, 800.0]]))


def test_check_fits_refuses_a_matrix_over_the_allowance():
    """2,000 columns' matrix does not fit in 10 MB: refused with a Fix."""
    sq.set_config(memory="10MB")
    with pytest.raises(SqlearnError, match="Fix:"):
        check_fits(connection(), 2_000)


def test_batch_rows_fits_the_batch_to_the_allowance():
    """Three copies of a batch and the matrix's four fit in a small allowance."""
    sq.set_config(memory="400MB")
    con = connection()
    rows = batch_rows(10, con)
    assert 1 <= rows < batch_rows(10)
    assert 8 * 10 * (4 * 10 + 3 * rows) <= allowance(con)
    assert check_fits(con, 10) is None


def test_batch_rows_is_the_default_size_when_the_allowance_is_ample():
    """With room to spare a batch is the usual 100 MB of values."""
    sq.set_config(memory="8GB")
    assert batch_rows(10, connection()) == batch_rows(10)


def test_gram_matrix_learns_under_a_small_budget():
    """A 10 MB budget learns a one-column Gram, in batches of a few rows."""
    sq.set_config(memory="10MB")
    con = connection()
    check_fits(con, 1)
    sql = "SELECT range::DOUBLE AS a FROM range(10000)"
    got = gram_matrix(con, sql, ["a"], {"a": 4999.5})
    want = ((np.arange(10000) - 4999.5) ** 2).sum()
    assert got == pytest.approx(np.array([[want]]), rel=1e-12)


def test_check_fits_counts_the_copies_of_the_matrix():
    """6,000 columns' four matrices (1.15 GB) do not fit in a 1 GB allowance."""
    sq.set_config(memory="2GB")
    with pytest.raises(SqlearnError, match="6,000-by-6,000"):
        check_fits(connection(), 6_000)


def test_check_fits_accepts_what_fits():
    """100 columns and three batches (300 MB) fit in a 1 GB allowance."""
    sq.set_config(memory="2GB")
    assert check_fits(connection(), 100) is None


def test_gram_matrix_agrees_on_one_and_many_threads():
    """The sum agrees within ADR 0043's bound on one thread and on many."""
    rng = np.random.default_rng(1)
    data = rng.normal(size=(50_000, 4)) * [1.0, 10.0, 0.1, 1e3] + [
        5.0,
        -3.0,
        100.0,
        0.0,
    ]
    frame = pd.DataFrame(data, columns=list("wxyz"))  # noqa: F841  (read by DuckDB)
    con = connection()
    con.execute("CREATE OR REPLACE TEMP TABLE gram_threads AS SELECT * FROM frame")
    means = dict(zip("wxyz", data.mean(axis=0).tolist(), strict=True))
    sql = "SELECT * FROM gram_threads"
    default = con.execute("SELECT current_setting('threads')").fetchall()[0][0]
    try:
        con.execute("SET threads = 1")
        one = gram_matrix(con, sql, list("wxyz"), means)
        con.execute(f"SET threads = {default}")
        many = gram_matrix(con, sql, list("wxyz"), means)
    finally:
        con.execute(f"SET threads = {default}")
    assert one == pytest.approx(many, rel=1e-10)


@pytest.mark.filterwarnings("ignore:the DuckDB connection passed to sqlearn")
def test_a_gram_matrix_over_the_budget_is_refused_before_any_batch(monkeypatch):
    """Learning a Gram step whose matrix cannot fit is refused, nothing streamed.

    The connection is the test's own, so DuckDB keeps its own limit (above
    its share, as the ignored warning says) and only the hand-over's
    allowance, half the 4 MB budget, is small: 300 columns' matrices
    (2.9 MB) do not fit in it.
    """
    batches: list[str] = []
    real = sqlearn._pipeline.gram_matrix

    def counted(*args: Any, **kwargs: Any) -> np.ndarray:
        batches.append("streamed")
        return real(*args, **kwargs)

    monkeypatch.setattr(sqlearn._pipeline, "gram_matrix", counted)
    rng = np.random.default_rng(0)
    names = [f"x{i}" for i in range(300)]
    wide = pd.DataFrame(rng.normal(size=(3, 300)), columns=names)
    sq.set_config(connection=duckdb.connect(), memory="4MB")
    with pytest.raises(SqlearnError, match=r"300-by-300.*Fix: .*sq\.set_config"):
        sq.Pipeline([sq.decompose.pca()]).learn(wide)
    assert batches == []
    sq.set_config(memory="2GB")
    sq.Pipeline([sq.decompose.pca()]).learn(wide)
    assert batches == ["streamed"]

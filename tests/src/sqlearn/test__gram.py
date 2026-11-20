"""Tests of the Gram learn: XᵀX of the centred rows, built in numpy."""

import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._errors import SqlearnError
from sqlearn._gram import check_fits, gram_matrix


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


def test_check_fits_counts_every_copy_of_a_batch():
    """Three copies of a 100 MB batch do not fit in a 200 MB allowance."""
    sq.set_config(memory="400MB")
    with pytest.raises(SqlearnError, match="Fix:"):
        check_fits(connection(), 10)


def test_check_fits_counts_the_copies_of_the_matrix():
    """6,000 columns' four matrices (1.15 GB) do not fit in a 1 GB allowance."""
    sq.set_config(memory="2GB")
    with pytest.raises(SqlearnError, match="6,000-by-6,000"):
        check_fits(connection(), 6_000)


def test_check_fits_accepts_what_fits():
    """100 columns and three batches (300 MB) fit in a 1 GB allowance."""
    sq.set_config(memory="2GB")
    assert check_fits(connection(), 100) is None

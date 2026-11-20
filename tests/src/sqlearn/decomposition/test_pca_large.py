"""Test of PCA learning data larger than the memory limit (spec §3 rule 3, §7)."""

import duckdb
import numpy as np
import pytest

import sqlearn as sq

ROWS = 2_000_000
COLUMNS = 50
LATENT = 7
CONDITIONING_SLACK = 16


def _column(j):
    """Return the SQL of column `j`: two latent factors and its own noise."""
    a, b = j % LATENT, (3 * j + 1) % LATENT
    return (
        f"((hash(i, {a}) % 2000001)::DOUBLE - 1000000) / 1e6 * {1 + j / 10} "
        f"+ ((hash(i, {b}) % 2000001)::DOUBLE - 1000000) / 1e6 * {2 - j / 40} "
        f"+ ((hash(i, {100 + j}) % 2000001)::DOUBLE - 1000000) / 1e6 * {0.05 + j / 25} "
        f"AS c{j}"
    )


@pytest.mark.slow
def test_pca_learns_data_larger_than_the_memory_limit(tmp_path):
    """The components of 800 MB of doubles, learned within 256 MB, are exact.

    The Parquet file holds 2 million rows of 50 columns, 800 MB as doubles,
    over three times the limit. They match numpy's ``eigh`` of DuckDB's own
    ``covar_pop`` matrix, each component up to its sign.
    """
    path = tmp_path / "large.parquet"
    columns = ", ".join(_column(j) for j in range(COLUMNS))
    duckdb.execute(
        f"COPY (SELECT {columns} FROM range({ROWS}) t(i)) TO '{path}' (FORMAT parquet)"
    )
    pairs = [(i, j) for i in range(COLUMNS) for j in range(i, COLUMNS)]
    covars = ", ".join(f"covar_pop(c{i}, c{j})" for i, j in pairs)
    (flat,) = duckdb.execute(
        f"SELECT [{covars}] FROM read_parquet('{path}')"
    ).fetchall()[0]
    cov = np.zeros((COLUMNS, COLUMNS))
    for (i, j), value in zip(pairs, flat, strict=True):
        cov[i, j] = cov[j, i] = value
    values, vectors = np.linalg.eigh(cov)
    want = vectors[:, ::-1].T
    gaps = np.diff(values[::-1])
    assert (
        np.abs(gaps).min() > 1e-6 * values.max()
    )  # the gaps keep each component defined

    con = duckdb.connect()
    con.execute("SET memory_limit = '256MB'")
    con.execute("SET threads = 1")  # as the core's slow tests: buffers per thread
    con.execute(f"SET temp_directory = '{tmp_path / 'spill'}'")
    sq.set_config(connection=con)
    pca = sq.Pipeline([sq.decompose.pca()]).learn(str(path))["pca"]

    got = np.array(pca.components_)
    assert got.shape == want.shape
    signs = np.sign(np.einsum("ij,ij->i", got, want))
    # A component's entries move by up to eps * lambda_1 / gap (Davis-Kahan)
    # when the matrix does, and the reference is itself built from DuckDB sums
    # that depend on thread order (ADR 0043): bound each row by its own gap to
    # its neighbours. CONDITIONING_SLACK covers the sums' own error and the
    # two sides' errors adding up; 1e-12 is the floor for well-separated rows.
    spacing = np.abs(gaps)
    nearest = np.minimum(np.r_[np.inf, spacing], np.r_[spacing, np.inf])
    bound = CONDITIONING_SLACK * np.finfo(float).eps * values.max() / nearest
    error = np.abs(got * signs[:, None] - want)
    assert (error <= np.maximum(bound, 1e-12)[:, None]).all()
    assert pca.explained_variance_ == pytest.approx(
        values[::-1] * ROWS / (ROWS - 1), rel=1e-9
    )

"""Tests of the hand-over of results: `out=` names and file outputs."""

import importlib.util

import duckdb
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._output import Output, to_output


@pytest.fixture
def rel():
    """Return a relation of two rows, ``a`` and ``b``."""
    return connection().sql("SELECT * FROM (VALUES (1, 'x'), (2, 'y')) t(a, b)")


def test_none_is_the_relation(rel):
    """No output kind hands back the relation itself."""
    assert to_output(rel, None) is rel


def test_pandas_and_numpy(rel):
    """`"pandas"` is a frame; `"numpy"` a dict of column to array."""
    frame = to_output(rel, "pandas")
    assert isinstance(frame, pd.DataFrame)
    assert frame["a"].tolist() == [1, 2]
    arrays = to_output(rel, "numpy")
    assert isinstance(arrays, dict)
    assert list(arrays) == ["a", "b"]
    assert arrays["a"].tolist() == [1, 2]


@pytest.mark.parametrize(
    ("name", "module"), [("polars", "polars"), ("arrow", "pyarrow")]
)
def test_polars_and_arrow_need_their_library(rel, name, module):
    """Without its library installed, an output kind says what to install."""
    if importlib.util.find_spec(module) is not None:
        assert to_output(rel, name) is not None
        return
    with pytest.raises(sq.SqlearnError, match=module):
        to_output(rel, name)


def test_an_unknown_name_lists_the_names(rel):
    """An unknown output name is refused, listing the accepted ones."""
    with pytest.raises(sq.SqlearnError, match=r"pandas.*polars.*numpy.*arrow"):
        to_output(rel, "excel")


@pytest.mark.parametrize(
    ("make", "reader"),
    [
        (sq.out_parquet, "read_parquet"),
        (sq.out_csv, "read_csv"),
        (sq.out_json, "read_json"),
    ],
)
def test_files_are_written_by_duckdb(rel, tmp_path, make, reader):
    """Each file output writes the rows; the path is returned."""
    path = tmp_path / "it's here.out"
    out = make(path)
    assert isinstance(out, Output)
    assert to_output(rel, out) == str(path)
    con = duckdb.connect()
    literal = "'" + str(path).replace("'", "''") + "'"
    assert con.sql(f"SELECT * FROM {reader}({literal})").fetchall() == [
        (1, "x"),
        (2, "y"),
    ]

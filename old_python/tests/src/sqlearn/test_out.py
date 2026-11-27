"""Tests of the output group."""

import sqlearn as sq
from sqlearn import _output


def test_out_holds_the_file_builders():
    """``sq.out.csv`` and kin are the core's ``out_*`` builders."""
    assert sq.out.csv is _output.out_csv
    assert sq.out.json is _output.out_json
    assert sq.out.parquet is _output.out_parquet
    assert sq.out.parquet("x.parquet").format == "parquet"

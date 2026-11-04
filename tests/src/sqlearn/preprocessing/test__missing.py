"""Tests of the helpers shared by Impute and Scale."""

import duckdb
import pytest

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._step import Learned
from sqlearn.preprocessing._missing import (
    present,
    refuse_all_missing,
    refuse_infinite,
)

X = duckdb.ColumnExpression("c")


def test_present_nulls_nan_and_null_and_casts_to_double():
    """NaN and NULL both become NULL; the rest is DOUBLE."""
    rel = connection().sql("SELECT * FROM (VALUES (1), (NULL), (3)) t(c)")
    assert rel.select(present(X)).fetchall() == [(1.0,), (None,), (3.0,)]
    nan = connection().sql("SELECT 'NaN'::DOUBLE AS c")
    assert nan.select(present(X)).fetchall() == [(None,)]


def test_all_missing_is_judged_on_the_raw_value_not_its_text():
    """None refuses; a number or a placeholder does not."""
    with pytest.raises(sq.StepError, match="'c'"):
        refuse_all_missing(X, Learned.values({"m": None}), "m")
    refuse_all_missing(X, Learned.values({"m": 0.0}), "m")
    refuse_all_missing(X, Learned.placeholders("l01_s", {"m": "v0"}), "m")


def test_duckdb_still_returns_python_none_for_an_empty_aggregate():
    """Pins duckdb: the NULL an aggregate over no values returns is None."""
    rel = connection().sql("SELECT avg(a) FROM (SELECT NULL::DOUBLE AS a)")
    assert rel.fetchall() == [(None,)]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_infinite_values_are_refused(bad):
    """Infinity and NaN are refused, finite numbers and None are not."""
    with pytest.raises(sq.StepError, match="infinity"):
        refuse_infinite(X, Learned.values({"m": bad}), "m")
    refuse_infinite(X, Learned.values({"m": 1.0}), "m")
    refuse_infinite(X, Learned.values({"m": None}), "m")
    refuse_infinite(X, Learned.placeholders("l01_s", {"m": "v0"}), "m")

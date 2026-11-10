"""Tests of the column selectors."""

import duckdb
import pytest
from duckdb.sqltypes import BIGINT, DOUBLE, INTEGER, VARCHAR

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._selectors import to_selector

SCHEMA = [("id", INTEGER), ("age", DOUBLE), ("city", VARCHAR), ("income", BIGINT)]


def test_numeric_except_id():
    """Selectors combine as in Polars; the result keeps schema order."""
    assert (sq.cols.numeric() - sq.cols("id")).resolve(SCHEMA) == ["age", "income"]


def test_operators():
    """|, & and ~ behave as or, and, not."""
    assert (sq.cols.string() | sq.cols("id")).resolve(SCHEMA) == ["id", "city"]
    assert (~sq.cols.numeric()).resolve(SCHEMA) == ["city"]
    assert (sq.cols.numeric() & sq.cols("age", "city")).resolve(SCHEMA) == ["age"]


def test_may_match_by_type():
    """Planning asks whether a selector could match a not-yet-named column."""
    assert sq.cols.numeric().may_match(INTEGER) and not sq.cols.string().may_match(
        INTEGER
    )
    assert sq.cols.string().may_match(VARCHAR)
    assert (~sq.cols.numeric()).may_match(VARCHAR)
    assert not (~sq.cols.numeric()).may_match(DOUBLE)
    assert sq.cols("a").may_match(INTEGER)
    assert (sq.cols.numeric() - sq.cols("id")).may_match(INTEGER)
    assert not (sq.cols.numeric() & sq.cols.string()).may_match(INTEGER)


def test_missing_name_resolves_to_nothing():
    """A name absent from the schema is not an error here."""
    assert sq.cols("nope", "age").resolve(SCHEMA) == ["age"]
    assert sq.cols("nope").resolve(SCHEMA) == []


def test_numeric_kinds():
    """Every integer width, unsigned, float and decimal counts as numeric."""
    rel = duckdb.sql(
        "SELECT 1::TINYINT a, 1::SMALLINT b, 1::HUGEINT c, 1::UTINYINT d,"
        " 1::UBIGINT e, 1::UHUGEINT f, 1::FLOAT g, 1::DECIMAL(2,1) h,"
        " 1::DECIMAL(38,10) i, 'x' j, true k, [1]::INTEGER[] l,"
        " [1.5]::DECIMAL(2,1)[] m"
    )
    assert rel is not None
    schema = list(zip("abcdefghijklm", rel.types, strict=True))
    assert sq.cols.numeric().resolve(schema) == list("abcdefghi")
    assert sq.cols.string().resolve(schema) == ["j"]


def test_to_selector():
    """Names, one name or a selector all become a selector."""
    assert to_selector(["a"]) == sq.cols("a")
    assert to_selector("a") == sq.cols("a")
    assert to_selector(sq.cols.numeric()) is not None
    s = sq.cols.numeric()
    assert to_selector(s) is s


def test_value_equality_and_repr():
    """Selectors compare by value and print deterministically."""
    assert sq.cols.numeric() == sq.cols.numeric()
    assert sq.cols.numeric() != sq.cols.string()
    assert sq.cols.numeric() - sq.cols("id") == sq.cols.numeric() - sq.cols("id")
    assert hash(sq.cols("a")) == hash(sq.cols("a"))
    assert repr(sq.cols("a", "b")) == "cols('a', 'b')"
    assert repr(sq.cols.numeric() - sq.cols("id")) == "(numeric() - cols('id'))"
    assert repr(~sq.cols.string() | sq.cols.numeric()) == "((~string()) | numeric())"


def test_may_match_through_every_combinator():
    """Planning stays sound through nested |, &, - and ~."""
    num, text, name = sq.cols.numeric(), sq.cols.string(), sq.cols("id")
    assert (num | text).may_match(VARCHAR)
    assert not (~(num | text)).may_match(VARCHAR)
    assert not (~(num & ~text)).may_match(INTEGER)
    assert (~(num & text)).may_match(INTEGER)
    assert not (num - ~text).may_match(INTEGER)
    assert not (~(num - text)).may_match(INTEGER)
    assert (~(num - name)).may_match(INTEGER)
    assert not (num - num).may_match(INTEGER)
    assert (~~num).may_match(INTEGER)
    assert (~(name & num)).may_match(INTEGER)
    assert repr(num & text) == "(numeric() & string())"


def test_non_selector_operands_are_refused():
    """Combining a selector with anything else is a TypeError."""
    for op in (
        lambda a: a | 1,
        lambda a: a & 1,
        lambda a: a - 1,
    ):
        with pytest.raises(TypeError):
            op(sq.cols.numeric())


def test_cols_is_a_callable_group():
    """``sq.cols`` is called with names and has the kinds as methods."""
    assert sq.cols("a").resolve([("a", INTEGER), ("b", INTEGER)]) == ["a"]
    assert sq.cols.numeric().resolve([("a", INTEGER), ("b", VARCHAR)]) == ["a"]
    assert sq.cols.string().resolve([("a", INTEGER), ("b", VARCHAR)]) == ["b"]
    sel = sq.cols.numeric() - sq.cols("id")
    assert sel.resolve([("id", INTEGER), ("x", DOUBLE)]) == ["x"]
    assert repr(sq.cols) == "sq.cols"


def test_string_selects_enum_columns():
    """An ENUM column is text: string() chooses it beside VARCHAR, not INTEGER."""
    rel = connection().sql("SELECT 'a'::ENUM('a', 'b', 'c') AS e, 'x' AS v, 1 AS n")
    schema = list(zip(rel.columns, rel.types, strict=True))
    assert sq.cols.string().resolve(schema) == ["e", "v"]
    assert not sq.cols.string().may_match(INTEGER)
    assert sq.cols.string().may_match(rel.types[0])

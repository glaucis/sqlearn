"""Tests of the column selectors."""

import duckdb
import pytest
from duckdb.sqltypes import BIGINT, DOUBLE, INTEGER, VARCHAR

import sqlearn as sq
from sqlearn._selectors import to_selector

SCHEMA = [("id", INTEGER), ("age", DOUBLE), ("city", VARCHAR), ("income", BIGINT)]


def test_numeric_except_id():
    """Selectors combine as in Polars; the result keeps schema order."""
    assert (sq.numeric() - sq.cols("id")).resolve(SCHEMA) == ["age", "income"]


def test_operators():
    """|, & and ~ behave as or, and, not."""
    assert (sq.string() | sq.cols("id")).resolve(SCHEMA) == ["id", "city"]
    assert (~sq.numeric()).resolve(SCHEMA) == ["city"]
    assert (sq.numeric() & sq.cols("age", "city")).resolve(SCHEMA) == ["age"]


def test_may_match_by_type():
    """Planning asks whether a selector could match a not-yet-named column."""
    assert sq.numeric().may_match(INTEGER) and not sq.string().may_match(INTEGER)
    assert sq.string().may_match(VARCHAR)
    assert (~sq.numeric()).may_match(VARCHAR)
    assert not (~sq.numeric()).may_match(DOUBLE)
    assert sq.cols("a").may_match(INTEGER)
    assert (sq.numeric() - sq.cols("id")).may_match(INTEGER)
    assert not (sq.numeric() & sq.string()).may_match(INTEGER)


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
    assert sq.numeric().resolve(schema) == list("abcdefghi")
    assert sq.string().resolve(schema) == ["j"]


def test_to_selector():
    """Names, one name or a selector all become a selector."""
    assert to_selector(["a"]) == sq.cols("a")
    assert to_selector("a") == sq.cols("a")
    assert to_selector(sq.numeric()) is not None
    s = sq.numeric()
    assert to_selector(s) is s


def test_value_equality_and_repr():
    """Selectors compare by value and print deterministically."""
    assert sq.numeric() == sq.numeric()
    assert sq.numeric() != sq.string()
    assert sq.numeric() - sq.cols("id") == sq.numeric() - sq.cols("id")
    assert hash(sq.cols("a")) == hash(sq.cols("a"))
    assert repr(sq.cols("a", "b")) == "cols('a', 'b')"
    assert repr(sq.numeric() - sq.cols("id")) == "(numeric() - cols('id'))"
    assert repr(~sq.string() | sq.numeric()) == "((~string()) | numeric())"


def test_may_match_through_every_combinator():
    """Planning stays sound through nested |, &, - and ~."""
    num, text, name = sq.numeric(), sq.string(), sq.cols("id")
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
            op(sq.numeric())

"""Values written as JSON and read back."""

import json
import math
import struct
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

import sqlearn as sq
from sqlearn._errors import SqlearnError
from sqlearn._saving.codec import class_paths, decode, encode

_ZONE = timezone(timedelta(hours=2))


def _resolve(path: str) -> type:
    module, _, name = path.partition(":")
    import importlib

    found: object = importlib.import_module(module)
    for part in name.split("."):
        found = getattr(found, part)
    assert isinstance(found, type)
    return found


def _round_trip(value: object) -> object:
    text = json.dumps(encode(value, "test"), allow_nan=False)
    return decode(json.loads(text), "test", _resolve)


def _same(a: object, b: object) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        assert isinstance(b, float)
        if math.isnan(a):
            return math.isnan(b)
        return struct.pack("<d", a) == struct.pack("<d", b)
    if isinstance(a, list | tuple):
        assert isinstance(b, list | tuple)
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict):
        assert isinstance(b, dict)
        return len(a) == len(b) and all(
            _same(k1, k2) and _same(v1, v2)
            for (k1, v1), (k2, v2) in zip(a.items(), b.items(), strict=True)
        )
    if isinstance(a, Decimal):
        return repr(a) == repr(b)
    return bool(a == b)


_hashable = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-(2**127), 2**127),
    st.floats(),
    st.text(),
    st.dates(),
    st.uuids(),
    st.binary(),
)
_leaves = st.one_of(
    _hashable,
    st.decimals(allow_nan=False, allow_infinity=False),
    st.datetimes(),
    st.datetimes(timezones=st.just(_ZONE)),
    st.times(),
    st.times(timezones=st.just(_ZONE)),
    st.timedeltas(),
)
_values = st.recursive(
    _leaves,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.lists(inner, max_size=4).map(tuple),
        st.dictionaries(
            st.one_of(st.text(), st.integers(), st.dates()), inner, max_size=4
        ),
    ),
    max_leaves=12,
)


@given(_values)
def test_a_value_comes_back_equal_and_of_its_type(value: object) -> None:
    """Any nested value reads back equal and of the same type at every level."""
    assert _same(_round_trip(value), value)


def test_every_kind_of_value_appears_in_the_strategy_check() -> None:
    """One of each dated, identified and binary kind reads back exactly."""
    sample = [
        UUID(int=5),
        date(2020, 1, 2),
        time(1, 2, 3, 4, tzinfo=UTC),
        datetime(2020, 1, 2, 3, tzinfo=_ZONE),
        timedelta(days=-3, seconds=5, microseconds=7),
        b"\x00\xff",
        Decimal("12.50"),
    ]
    assert _same(_round_trip(sample), sample)


@pytest.mark.parametrize(
    "value", [5e-324, 1.7976931348623157e308, -0.0, 0.1 + 0.2, 2.0**-1074 * 3]
)
def test_floats_that_are_hard_to_round_come_back_exactly(value: float) -> None:
    """Subnormals, extremes and signed zero keep every bit."""
    back = _round_trip(value)
    assert isinstance(back, float)
    assert struct.pack("<d", back) == struct.pack("<d", value)


def test_equal_values_give_the_same_bytes() -> None:
    """Equal values give equal text, and a dict keeps its insertion order."""
    one = {"b": (1, 2.5), "a": [Decimal("1.0"), date(2020, 1, 1)]}
    two = {"b": (1, 2.5), "a": [Decimal("1.0"), date(2020, 1, 1)]}
    assert json.dumps(encode(one, "t")) == json.dumps(encode(two, "t"))
    back = _round_trip({"b": 1, "a": 2})
    assert isinstance(back, dict)
    assert list(back) == ["b", "a"]


def test_the_tag_comes_first() -> None:
    """A tagged object lists its "$" key first."""
    tagged = encode(Decimal("1.5"), "t")
    assert isinstance(tagged, dict)
    assert list(tagged) == ["$", "value"]


def test_selectors_come_back_as_they_were() -> None:
    """A selector, combined or not, reads back equal with the same repr."""
    for selector in (
        sq.cols("a", "b"),
        sq.cols.numeric(),
        (sq.cols.numeric() - sq.cols("id")) | ~sq.cols.string(),
        sq.cols.numeric() & sq.cols("x"),
    ):
        assert repr(_round_trip(selector)) == repr(selector)
        assert _round_trip(selector) == selector


def test_a_function_is_refused_naming_where_it_was() -> None:
    """A function is refused, naming the place, the type and a fix."""
    with pytest.raises(SqlearnError) as raised:
        encode(lambda x: x, "custom (step 2), setting 'learn'")
    text = str(raised.value)
    for part in ("custom (step 2)", "'learn'", "function", "Fix:", "Why:"):
        assert part in text


def test_an_object_with_the_default_repr_is_refused() -> None:
    """An object of a foreign class with no encoding is refused by type."""

    class Odd:
        pass

    with pytest.raises(SqlearnError, match="Odd"):
        encode(Odd(), "step 1")


def test_a_sqlearn_object_comes_back_from_its_settings() -> None:
    """A fold scheme is written by class path and settings and rebuilt."""
    scheme = sq.folds.kfold(3, seed=1)
    data = encode(scheme, "search")
    assert isinstance(data, dict)
    assert data["$"] == "object"
    assert data["class"].startswith("sqlearn")
    assert _round_trip(scheme) == scheme


def test_an_unknown_tag_is_refused() -> None:
    """An unknown tag or a malformed value is refused naming the place."""
    for bad in (
        {"$": "complex", "value": "1j"},
        {"$": "decimal", "value": "1.2.3"},
        {"$": "float", "value": "huge"},
        {"$": "date", "value": "not a date"},
        {"$": "bytes", "base64": "***"},
        {"no": "tag"},
    ):
        with pytest.raises(SqlearnError, match="step 1"):
            decode(bad, "step 1", _resolve)


def test_class_paths_finds_nested_classes() -> None:
    """Every class in tagged objects and estimators is found, nested."""
    data = encode(
        [{"x": 1}],
        "t",
    )
    assert class_paths(data) == set()
    tagged = {
        "$": "estimator",
        "class": "a:B",
        "params": {
            "estimator": {"$": "estimator", "class": "c:D", "params": {}},
            "more": [{"$": "object", "class": "e:F", "settings": {}}],
        },
    }
    assert class_paths(tagged) == {"a:B", "c:D", "e:F"}

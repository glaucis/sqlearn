"""Tests of the helpers every group shares."""

import pytest

import sqlearn as sq
from sqlearn._group import Group, column_names, columns_arg
from sqlearn.errors import SqlearnError


def test_columns_arg_forms():
    """Names, a list, a tuple or nothing each give the documented value."""
    assert columns_arg((), None, allow_dict=False) is None
    assert columns_arg(("a",), None, allow_dict=False) == "a"
    assert columns_arg(("a", "b"), None, allow_dict=False) == ["a", "b"]
    assert columns_arg((["a", "b"],), None, allow_dict=False) == ["a", "b"]
    assert columns_arg((("a", "b"),), None, allow_dict=False) == ["a", "b"]


def test_columns_arg_takes_cols_keyword_alone():
    """``cols=`` alone is passed through; with nothing at all it is None."""
    assert columns_arg((), ["b"], allow_dict=False) == ["b"]
    assert columns_arg((), None, allow_dict=True) is None


def test_columns_arg_refuses_names_and_cols_together():
    """Names and ``cols=`` together are refused, naming both."""
    with pytest.raises(SqlearnError, match=r"'a'.*cols="):
        columns_arg(("a",), ["b"], allow_dict=False)


def test_columns_arg_dict():
    """A dict is returned when allowed and refused otherwise."""
    assert columns_arg(({"a": 1},), None, allow_dict=True) == {"a": 1}
    with pytest.raises(SqlearnError, match="dict"):
        columns_arg(({"a": 1},), None, allow_dict=False)


def test_group_repr_and_dir():
    """A group prints as ``sq.<name>`` and lists its shortcuts."""

    class Scale(Group):
        def standard(self):
            """A shortcut."""

    group = Scale("scale")
    assert repr(group) == "sq.scale"
    assert "standard" in dir(group)
    assert not any(n.startswith("_") for n in dir(group))


def test_column_names():
    """Names and sequences of names read as a list; anything else as None."""
    assert column_names("a") == ["a"]
    assert column_names(["a", "b"]) == ["a", "b"]
    assert column_names(("a",)) == ["a"]
    assert column_names(sq.cols.numeric()) is None
    assert column_names([1, 2]) is None

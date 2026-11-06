"""Tests of ``sq.encode`` and its shortcuts."""

import pandas as pd
import pytest

import sqlearn as sq
from sqlearn.preprocessing.onehot import OneHot
from sqlearn.preprocessing.ordinal import Ordinal


@pytest.mark.parametrize(("method", "cls"), [("onehot", OneHot), ("ordinal", Ordinal)])
def test_shortcut_equals_general_form(method, cls):
    """Each shortcut builds the step the general form builds."""
    short = getattr(sq.encode, method)("a", keep=True)
    general = sq.encode("a", method=method, keep=True)
    assert type(short) is cls
    assert short.settings() == general.settings() == cls(cols="a", keep=True).settings()
    assert short.default_name() == method


def test_default_method_and_columns():
    """The general form is one-hot over the text columns."""
    step = sq.encode()
    assert isinstance(step, OneHot)
    assert step.cols == sq.cols.string()
    assert sq.encode.ordinal().cols == sq.cols.string()


def test_columns_by_name_list_or_selector():
    """Columns come as names, one list, or cols=."""
    assert sq.encode.onehot("a", "b").cols == ["a", "b"]
    assert sq.encode.onehot(["a", "b"]).cols == ["a", "b"]
    assert sq.encode.ordinal(cols=sq.cols.numeric()).cols == sq.cols.numeric()
    with pytest.raises(sq.errors.SqlearnError, match="twice"):
        sq.encode.onehot("a", cols="b")


@pytest.mark.parametrize("make", [sq.encode.onehot, sq.encode.ordinal, sq.encode])
def test_suffix_is_refused(make):
    """Encoders take no suffix (ADR 0035 rule 4)."""
    with pytest.raises(TypeError, match="suffix"):
        make(suffix="x")


@pytest.mark.parametrize("cls", [OneHot, Ordinal])
def test_classes_take_no_suffix(cls):
    """The classes have no suffix setting either."""
    with pytest.raises(TypeError, match="suffix"):
        cls(suffix="x")
    assert "suffix" not in cls().settings()


def test_a_dict_is_refused():
    """An encoder has no setting per column."""
    with pytest.raises(sq.errors.SqlearnError, match="dict"):
        sq.encode({"a": "onehot"})
    with pytest.raises(sq.errors.SqlearnError, match="dict"):
        sq.encode.ordinal({"a": 1})


def test_unknown_method_is_refused_with_the_methods():
    """The message names the methods (ADR 0019)."""
    with pytest.raises(sq.errors.SqlearnError, match=r"'target'.*'onehot', 'ordinal'"):
        sq.encode("a", method="target")


@pytest.mark.parametrize(
    "step",
    [
        sq.encode.onehot(),
        sq.encode.onehot("a", keep=True),
        sq.encode.ordinal(["a", "b"]),
    ],
)
def test_repr_rebuilds_the_step(step):
    """The repr is the shortest call and evaluates to an equal step."""
    rebuilt = eval(repr(step), {"sq": sq})
    assert type(rebuilt) is type(step)
    assert rebuilt.settings() == step.settings()


def test_repr_is_shortest_form():
    """Defaults are left out."""
    assert repr(sq.encode.onehot()) == "sq.encode.onehot()"
    assert repr(sq.encode.ordinal(cols=sq.cols.numeric())) == (
        "sq.encode.ordinal(cols=numeric())"
    )
    assert repr(sq.encode.ordinal("a", keep=True)) == (
        "sq.encode.ordinal(cols='a', keep=True)"
    )


def test_group_lists_its_shortcuts():
    """dir() names the shortcuts."""
    assert {"onehot", "ordinal"} <= set(dir(sq.encode))
    assert repr(sq.encode) == "sq.encode"


def test_in_a_pipeline_named_after_the_method():
    """An unnamed step in a pipeline is named by its method."""
    data = pd.DataFrame({"city": ["a", "b"], "size": ["s", "l"]})
    pipe = sq.Pipeline([sq.encode.onehot("city"), sq.encode.ordinal("size")])
    pipe.learn(data)
    assert list(pipe.apply(data, out="pandas").columns) == ["city_a", "city_b", "size"]
    assert {"onehot", "ordinal"} <= {name for name, _ in pipe.steps}

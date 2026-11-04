"""Tests of the step contract and its classification."""

import copy
import pickle

import duckdb
import pytest
from duckdb.sqltypes import DOUBLE, INTEGER, VARCHAR
from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._step import Learned, Step, classify, output_names

SCHEMA = [("age", DOUBLE), ("city", VARCHAR), ("n", INTEGER)]


def test_an_undeclared_scale_is_static():
    """A step whose apply gives one expression is static."""
    assert classify(MyScale(), SCHEMA) == "static"


def test_an_undeclared_encoder_is_dynamic():
    """A step that loops over a learned list is dynamic."""
    assert classify(MyEncoder(), SCHEMA) == "dynamic"


def test_a_declaration_is_trusted_without_inspection():
    """A declared class is used as it stands; apply is never called."""

    class Declared(MyScale):
        """A scale declared dynamic."""

        static = False

        def apply(self, x, learned):
            """Fail if called."""
            raise AssertionError("must not be called")

    assert classify(Declared(), SCHEMA) == "dynamic"


def test_the_answer_is_cached_per_settings():
    """Equal settings share one inspection; different settings do not."""
    calls = []

    class Counting(MyScale):
        """A scale that counts its inspections."""

        def apply(self, x, learned):
            """Count, then scale."""
            calls.append(1)
            return super().apply(x, learned)

    assert classify(Counting(), SCHEMA) == "static"
    assert classify(Counting(), SCHEMA) == "static"
    assert len(calls) == 1
    classify(Counting(keep=True), SCHEMA)
    assert len(calls) == 2


def test_an_apply_that_raises_is_dynamic():
    """Any exception while inspecting means dynamic."""

    class Broken(MyScale):
        """A scale whose apply fails."""

        def apply(self, x, learned):
            """Fail."""
            raise ValueError("boom")

    assert classify(Broken(), SCHEMA) == "dynamic"


def test_a_step_without_inputs_still_classifies():
    """With no input column, a stand-in column is used."""
    assert classify(MyScale(cols=sq.cols("zzz")), SCHEMA) == "static"


def test_settings_come_from_init():
    """Settings are the __init__ parameters, read from attributes."""
    assert MyScale().settings() == {"cols": sq.numeric(), "keep": False, "suffix": None}
    assert MyEncoder(keep=True).settings()["keep"] is True


def test_inputs_resolve_cols():
    """Inputs follow cols; None means every column."""
    assert MyScale().inputs(SCHEMA) == ["age", "n"]
    assert MyEncoder().inputs(SCHEMA) == ["city"]
    assert Step().inputs(SCHEMA) == ["age", "city", "n"]
    assert Step(cols="age").inputs(SCHEMA) == ["age"]


def test_the_default_learn_is_empty():
    """A step that learns nothing returns an empty mapping."""
    assert Step().learn(duckdb.ColumnExpression("a")) == {}


def test_learned_attributes_come_from_the_last_learn():
    """name_ gives the learned values by column."""
    step = MyScale()
    step._set_learned({"age": {"mean": 1.0}})
    assert step.mean_ == {"age": 1.0}


def test_missing_attributes_still_raise_attribute_error():
    """Unknown names and unlearned values both raise AttributeError."""
    step = MyScale()
    with pytest.raises(AttributeError):
        step.nonsense  # noqa: B018
    with pytest.raises(AttributeError, match="learn"):
        step.mean_  # noqa: B018


def test_a_name_the_step_did_not_learn_raises_attribute_error():
    """A misspelt learned name raises, naming what was learned."""
    step = MyScale()
    step._set_learned({"age": {"mean": 1.0, "sd": 2.0}})
    with pytest.raises(AttributeError, match=r"'maen'.*mean_, sd_"):
        step.maen_  # noqa: B018
    assert not hasattr(step, "maen_")
    assert hasattr(step, "mean_")


def test_steps_copy_and_pickle():
    """Copying and pickling do not recurse through __getattr__."""
    step = MyEncoder()
    step._set_learned({"city": {"cities": ["a"]}})
    assert copy.deepcopy(step).cities_ == {"city": ["a"]}
    assert pickle.loads(pickle.dumps(step)).cities_ == {"city": ["a"]}


def test_placeholders_print_as_stage_references():
    """Placeholders are references into the learn stage."""
    learned = Learned.placeholders("l03_scale", {"mean": "v0", "scale": "v1"})
    assert (
        str(MyScale().apply(duckdb.ColumnExpression("age"), learned))
        == '(("age" - "l03_scale"."v0") / "l03_scale"."v1")'
    )
    assert learned.accessed == ["mean", "scale"]


def test_learned_values():
    """Scalars become constants, lists stay lists; reads are recorded."""
    learned = Learned.values({"mean": 2.0, "cities": ["a", "b"]})
    assert str(learned.mean) == "2.0::DOUBLE"
    assert learned.cities == ["a", "b"]
    assert learned.accessed == ["mean", "cities"]
    with pytest.raises(AttributeError):
        learned.other  # noqa: B018


def test_output_names():
    """One expression keeps or suffixes the column; a mapping names itself."""
    e = duckdb.ColumnExpression("a")
    assert list(output_names("scale", "a", e, False, None)) == ["a"]
    assert list(output_names("scale", "a", e, True, None)) == ["a_scale"]
    assert list(output_names("scale", "a", e, True, "z")) == ["a_z"]
    assert list(output_names("onehot", "a", {"x": e, "y": e}, True, "z")) == ["x", "y"]


def test_a_declared_dynamic_step_is_trusted_without_calling_apply():
    """``dynamic = True`` is believed as ``static = True`` is: no inspection."""
    calls = []

    class Declared(sq.Step):
        dynamic = True

        def apply(self, x, learned):
            calls.append(1)
            return x

    assert classify(Declared(), [("a", INTEGER)]) == "dynamic"
    assert calls == []

"""Tests of failure feedback: each broken step gets the message written for it."""

import platform

import duckdb
import pytest
from broken_steps import (
    BadSql,
    DeclaredStaticNeedsValues,
    FailsWhileRunning,
    FakeBuiltin,
    MissingColumn,
    RaisesInApply,
)

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._diagnose import diagnose


@pytest.fixture
def people():
    """Return a relation of two people: an age and a city each."""
    return connection().sql(
        "SELECT * FROM (VALUES (10.0, 'b'), (20.0, 'a')) t(age, city)",
    )


def test_declared_static_but_needs_values(people):
    """A step declared static that loops over learned values says so (ADR 0019)."""
    pipe = sq.Pipeline(
        [
            ("one", sq.Step()),
            ("two", sq.Step()),
            ("MyEncoder", DeclaredStaticNeedsValues(cols="city")),
        ]
    )
    with pytest.raises(sq.errors.StepError) as err:
        pipe.learn(people)
    assert err.value.step == "MyEncoder"
    assert err.value.position == 3
    assert str(err.value) == (
        "MyEncoder (step 3) is declared static, but its apply() loops over "
        "learned.cities, which is only known after learning. A step that "
        "needs learned values to write its SQL is dynamic.\n"
        "Fix: remove static=True (sqlearn will then detect it), or set "
        "dynamic=True."
    )


def test_bad_sql_in_apply_names_the_step(people):
    """A function DuckDB lacks is traced to the step that called it."""
    pipe = sq.Pipeline([("one", sq.Step()), ("bad", BadSql(cols="age"))])
    with pytest.raises(sq.errors.StepError) as err:
        pipe.learn(people)
    assert (err.value.step, err.value.position) == ("bad", 2)
    first, fix = str(err.value).split("\n", 1)
    assert first.startswith("bad (step 2) builds SQL that DuckDB refuses: ")
    assert "no_such_function" in first
    assert fix.endswith(
        "\nFix: check that the step's learn and apply suit the columns it is given."
    )
    assert isinstance(err.value.__cause__, duckdb.Error)


def test_a_missing_column_names_column_and_step(people):
    """A column the data lacks is named, with the step that reads it."""
    pipe = sq.Pipeline([("gap", MissingColumn(cols="age"))])
    with pytest.raises(sq.errors.StepError) as err:
        pipe.learn(people)
    assert (err.value.step, err.value.position) == ("gap", 1)
    assert (
        str(err.value)
        .split("\n")[0]
        .startswith(
            "gap (step 1) reads column 'no_such_column', which is not in the data "
            "reaching it. DuckDB says: "
        )
    )
    assert str(err.value).endswith(
        "Fix: read only columns that reach the step, or add an earlier step "
        "that makes the column."
    )
    assert isinstance(err.value.__cause__, duckdb.Error)


def test_a_python_error_in_apply_names_the_step(people):
    """A plain Python error is a StepError naming the step and the method."""
    pipe = sq.Pipeline([("oops", RaisesInApply(cols="age"))])
    with pytest.raises(sq.errors.StepError) as err:
        pipe.learn(people)
    assert (err.value.step, err.value.position) == ("oops", 1)
    assert str(err.value) == (
        "oops (step 1) failed in its apply() with ValueError: cannot do this.\n"
        "Fix: correct the step's code; sqlearn calls it with SQL expressions, "
        "not numbers."
    )
    assert isinstance(err.value.__cause__, ValueError)


def test_a_failure_while_running_is_traced_by_its_stage_name():
    """A DuckDB error raised while running names the step in its stage name."""
    words = connection().sql("SELECT * FROM (VALUES ('1'), ('abc')) t(a)")
    pipe = sq.Pipeline([("copy", sq.Step()), ("total", FailsWhileRunning())])
    with pytest.raises(sq.errors.StepError) as err:
        pipe.learn(words)
    assert (err.value.step, err.value.position) == ("total", 2)
    text = str(err.value)
    assert text.startswith("total (step 2) fails while running: ")
    assert "Could not convert string 'abc'" in text
    assert text.endswith(
        "\nFix: check that the step's learn and apply suit the values in the data."
    )
    assert isinstance(err.value.__cause__, duckdb.Error)


def test_a_builtin_failure_is_an_internal_error(people):
    """A failure in a built-in step is sqlearn's bug, with what to report.

    The step is a test class whose module is set to a sqlearn module; no
    built-in step exists yet to break.
    """
    pipe = sq.Pipeline([("fake", FakeBuiltin(cols="age"))])
    with pytest.raises(sq.errors.InternalError) as err:
        pipe.learn(people)
    lines = str(err.value).split("\n")
    assert lines[0] == (
        "fake (step 1) is a built-in step (sqlearn.preprocessing.fake."
        "FakeBuiltin) and it failed: boom"
    )
    assert lines[1] == (
        "This is sqlearn's bug, not a mistake in your pipeline. Please report "
        "it at https://github.com/glaucis/sqlearn/issues with the SQL and "
        "versions below."
    )
    assert lines[2] == "SQL:"
    assert lines[3] == "(not composed: the step failed first)"
    assert lines[4] == (
        f"Versions: sqlearn {sq.__version__}, duckdb {duckdb.__version__}, "
        f"Python {platform.python_version()}"
    )
    assert len(lines) == 5


def test_a_builtin_sql_refusal_reports_the_sql(people):
    """When DuckDB refuses a built-in step's SQL, the statement is in the report."""
    refused = type(
        "Refused",
        (sq.Step,),
        {
            "apply": lambda self, x, learned: duckdb.FunctionExpression("nope", x),
            "__module__": "sqlearn.preprocessing.fake",
        },
    )
    with pytest.raises(sq.errors.InternalError) as err:
        sq.Pipeline([("fake", refused(cols="age"))]).learn(people)
    assert "sqlearn's bug" in str(err.value)
    assert "SELECT" in str(err.value)
    assert "nope" in str(err.value)


def test_diagnose_rechecks_the_declaration_when_duckdb_fails():
    """A DuckDB failure in a step declared static is re-checked by inspection."""
    steps = [("MyEncoder", DeclaredStaticNeedsValues(cols="city"))]
    err = diagnose(duckdb.Error("boom"), steps, lambda message: 1)
    assert isinstance(err, sq.errors.StepError)
    assert "MyEncoder (step 1) is declared static, but its apply() loops over" in str(
        err
    )


def test_diagnose_leaves_sqlearn_errors_alone():
    """An error sqlearn already explained is returned as it is."""
    given = sq.errors.SqlearnError("already explained")
    assert diagnose(given, [], lambda message: None) is given


def test_diagnose_without_a_step_still_explains():
    """A DuckDB error that names no stage is reported, not hidden."""
    err = diagnose(duckdb.Error("odd"), [("a", sq.Step())], lambda message: None)
    assert isinstance(err, sq.errors.SqlearnError)
    assert "odd" in str(err)


def test_a_builtin_failing_while_running_is_an_internal_error():
    """A built-in step's run-time DuckDB error is sqlearn's bug, SQL attached."""
    words = connection().sql("SELECT * FROM (VALUES ('1'), ('abc')) t(a)")
    builtin = type(
        "RunsBadly",
        (FailsWhileRunning,),
        {"__module__": "sqlearn.preprocessing.fake"},
    )
    with pytest.raises(sq.errors.InternalError) as err:
        sq.Pipeline([("fake", builtin())]).learn(words)
    text = str(err.value)
    assert text.startswith("fake (step 1) is a built-in step (")
    assert "sqlearn's bug" in text
    assert "WITH" in text
    assert "Could not convert string 'abc'" in text
    assert isinstance(err.value.__cause__, duckdb.Error)

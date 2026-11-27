"""Tests of the exception and warning types."""

from sqlearn._errors import (
    DefaultsUsedWarning,
    InternalError,
    SqlearnError,
    SqlearnWarning,
    StepError,
)


def test_defaults_used_warning_is_a_user_warning():
    """`DefaultsUsedWarning` is a `UserWarning`, through `SqlearnWarning`."""
    assert issubclass(DefaultsUsedWarning, SqlearnWarning)
    assert issubclass(DefaultsUsedWarning, UserWarning)


def test_step_error_keeps_step_and_position():
    """`StepError` carries the step name and its position."""
    err = StepError("m", step="scale", position=3)
    assert err.step == "scale"
    assert err.position == 3
    assert str(err) == "m"
    assert isinstance(err, SqlearnError)


def test_internal_error_is_a_sqlearn_error():
    """`InternalError` is a `SqlearnError`."""
    assert issubclass(InternalError, SqlearnError)

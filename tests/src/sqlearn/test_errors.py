"""Tests of the errors group."""

import sqlearn as sq
from sqlearn import _errors


def test_errors_holds_the_exceptions_and_warnings():
    """The group names the same classes the package raises."""
    for name in [
        "SqlearnError",
        "StepError",
        "InternalError",
        "SqlearnWarning",
        "DefaultsUsedWarning",
    ]:
        assert getattr(sq.errors, name) is getattr(_errors, name)
    assert issubclass(sq.errors.StepError, sq.errors.SqlearnError)

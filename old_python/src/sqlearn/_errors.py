"""The exceptions and warnings sqlearn raises."""

from pathlib import Path

PACKAGE_FILES = (str(Path(__file__).parent),)
"""sqlearn's own files: a warning is placed at the first frame outside them
(``warnings.warn(..., skip_file_prefixes=PACKAGE_FILES)``)."""


class SqlearnError(Exception):
    """Base class of every exception sqlearn raises on purpose.

    Examples
    --------
    >>> from sqlearn.errors import SqlearnError, StepError
    >>> issubclass(StepError, SqlearnError)
    True
    """


class StepError(SqlearnError):
    """A step failed, named by its name and its position in the pipeline.

    Parameters
    ----------
    message : str
        What went wrong, why, and the fix.
    step : str
        The name of the step.
    position : int
        The step's position in the pipeline, counting from 1.

    Examples
    --------
    >>> from sqlearn.errors import StepError
    >>> err = StepError("m", step="scale", position=3)
    >>> err.step, err.position
    ('scale', 3)
    """

    def __init__(self, message: str, *, step: str, position: int) -> None:
        super().__init__(message)
        self.step = step
        self.position = position


class InternalError(SqlearnError):
    """A condition that should be impossible: a bug in sqlearn.

    Examples
    --------
    >>> from sqlearn.errors import InternalError, SqlearnError
    >>> issubclass(InternalError, SqlearnError)
    True
    """


class SqlearnWarning(UserWarning):
    """Base class of every warning sqlearn issues.

    Examples
    --------
    >>> from sqlearn.errors import SqlearnWarning
    >>> issubclass(SqlearnWarning, UserWarning)
    True
    """


class DefaultsUsedWarning(SqlearnWarning):
    """A default was used where the user might have expected a choice.

    Examples
    --------
    >>> from sqlearn.errors import DefaultsUsedWarning, SqlearnWarning
    >>> issubclass(DefaultsUsedWarning, SqlearnWarning)
    True
    """


class UndefinedMetricWarning(SqlearnWarning):
    """A score divided by zero and took ``zero_division``'s value.

    Raised by precision, recall, f1 and fbeta under ``zero_division="warn"``,
    and by average_precision when no row is of the class it scores (its
    score is then 0.0), as scikit-learn raises its own
    ``UndefinedMetricWarning``.

    Examples
    --------
    >>> from sqlearn.errors import SqlearnWarning, UndefinedMetricWarning
    >>> issubclass(UndefinedMetricWarning, SqlearnWarning)
    True
    """

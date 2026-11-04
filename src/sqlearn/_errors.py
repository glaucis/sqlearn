"""The exceptions and warnings sqlearn raises."""


class SqlearnError(Exception):
    """Base class of every exception sqlearn raises on purpose."""


class StepError(SqlearnError):
    """A step failed, named by its name and its position in the pipeline.

    Parameters
    ----------
    message : str
        What went wrong, why, and the fix.
    step : str
        The name of the step.
    position : int
        The step's position in the pipeline, counting from zero.
    """

    def __init__(self, message: str, *, step: str, position: int) -> None:
        super().__init__(message)
        self.step = step
        self.position = position


class InternalError(SqlearnError):
    """A condition that should be impossible: a bug in sqlearn."""


class SqlearnWarning(UserWarning):
    """Base class of every warning sqlearn issues."""


class DefaultsUsedWarning(SqlearnWarning):
    """A default was used where the user might have expected a choice."""

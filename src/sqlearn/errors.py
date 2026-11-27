"""The exceptions sqlearn raises."""


class SqlearnError(Exception):
    """Base class of every exception sqlearn raises on purpose.

    Examples
    --------
    >>> from sqlearn.errors import InternalError, SqlearnError
    >>> issubclass(InternalError, SqlearnError)
    True
    """


class InternalError(SqlearnError):
    """A condition that should be impossible: a bug in sqlearn.

    The engine raises it when one of its preconditions fails
    (``SQ_EXPECTS``), with what went wrong, why and the fix.

    Examples
    --------
    >>> from sqlearn.errors import InternalError, SqlearnError
    >>> issubclass(InternalError, SqlearnError)
    True
    """

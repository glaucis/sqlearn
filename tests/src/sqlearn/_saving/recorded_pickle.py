"""A pickle that records its own loading, so a test can tell it was never opened.

Importing this module records nothing: only unpickling a `Recorded` calls
`_record`.
"""

import sys


def _record() -> None:
    vars(sys)["modules"]["sqlearn_test_unpickled"] = True


class Recorded:
    """An object whose loading from a pickle calls `_record`."""

    def __reduce__(self) -> tuple[object, tuple[()]]:
        """Make loading call `_record`."""
        return (_record, ())

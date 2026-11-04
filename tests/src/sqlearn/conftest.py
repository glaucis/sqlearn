"""Fixtures shared by every test of the package."""

from collections.abc import Iterator

import pytest

from sqlearn import _config, _step


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset the package's global state after each test.

    Later tasks add their own resets (the result store) here.
    """
    yield
    _config._reset()
    _step.KINDS.clear()

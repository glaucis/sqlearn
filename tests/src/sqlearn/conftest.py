"""Fixtures shared by every test of the package."""

from collections.abc import Iterator

import pytest

from sqlearn import _config


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset the package's global state after each test.

    Later tasks add their own resets (the result store, the step kinds) here.
    """
    yield
    _config._reset()

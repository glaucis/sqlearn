"""Fixtures shared by every test of the package."""

from collections.abc import Iterator

import pytest

from sqlearn import _config, _inputs, _memory, _step, _store


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset the package's global state after each test.

    Later tasks add their own resets here.
    """
    yield
    _config._reset()
    _memory._reset()
    _step.KINDS.clear()
    _store.STORE.clear()
    _inputs._last_blocks.clear()

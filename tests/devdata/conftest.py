"""Fixtures shared by every test of the development datasets."""

from collections.abc import Iterator

import pytest

from sqlearn import _config, _inputs, _memory, _step, _store
from sqlearn.preprocessing import _lookup


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset sqlearn's global state after each test, as the package's tests do."""
    yield
    _config._reset()
    _memory._reset()
    _step.KINDS.clear()
    _store.STORE.clear()
    _inputs._last_blocks.clear()
    _lookup._warned.clear()

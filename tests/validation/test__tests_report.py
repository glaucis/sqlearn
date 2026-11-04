"""The pytest plugin that writes tests.json: each test's area."""

import pytest

from validation._tests_report import area


@pytest.mark.parametrize(
    ("nodeid", "expected"),
    [
        (
            "tests/src/sqlearn/preprocessing/test_scale.py::test_x[a]",
            "sqlearn/preprocessing/scale",
        ),
        ("tests/src/sqlearn/test__compose.py::test_y", "sqlearn/_compose"),
        ("tests/validation/test__cases.py::test_z", "validation/_cases"),
        ("tests/test_environment.py::test_w", "environment"),
    ],
)
def test_area_is_the_mirrored_module(nodeid, expected):
    """A test's area is the module its file mirrors, without tests/ and src/."""
    assert area(nodeid) == expected

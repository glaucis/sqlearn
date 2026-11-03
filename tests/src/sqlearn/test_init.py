"""Tests of the package's top-level module."""

from importlib.metadata import version
from importlib.resources import files


def test_the_package_imports():
    """`sqlearn` imports from the environment uv built."""
    import sqlearn

    assert sqlearn.__name__ == "sqlearn"


def test_the_version_is_a_string():
    """`__version__` is the non-empty version hatch-vcs wrote from git."""
    import sqlearn

    assert isinstance(sqlearn.__version__, str)
    assert sqlearn.__version__
    assert sqlearn.__version__ == version("sqlearn")


def test_the_package_ships_py_typed():
    """`py.typed` is in the package, so users' type checkers read it."""
    assert files("sqlearn").joinpath("py.typed").is_file()

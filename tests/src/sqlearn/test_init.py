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


def test_the_top_level_holds_only_the_builders():
    """The top level is exactly ADR 0034's map, and nothing else."""
    import sqlearn as sq

    builders = {"Pipeline", "Step", "Search", "set_config", "get_config"}
    groups = {"impute", "scale", "encode", "transform", "bin", "features", "agg"}
    others = {"cols", "fn", "out", "metrics", "errors", "store"}
    kept = {"Learned", "Output", "Grid", "KFold", "range", "Model", "__version__"}
    allowed = builders | groups | others | kept
    assert set(sq.__all__) == allowed
    # Python also sets each imported subpackage on the package.
    packages = {"model_selection", "preprocessing"}
    public = {n for n in dir(sq) if not n.startswith("_")} | {"__version__"}
    assert public == allowed | packages

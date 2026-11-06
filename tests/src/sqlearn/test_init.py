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
    """Names that moved into groups are gone from the top level."""
    import sqlearn as sq

    public = {n for n in dir(sq) if not n.startswith("_")}
    for gone in [
        "make_pipeline",
        "numeric",
        "string",
        "const",
        "is_missing",
        "out_csv",
        "out_json",
        "out_parquet",
        "Metric",
        "accuracy",
        "SqlearnError",
        "StepError",
        "InternalError",
        "SqlearnWarning",
        "DefaultsUsedWarning",
        "avg",
        "median",
        "stddev_pop",
        "count",
        "distinct_values",
        "Impute",
        "Scale",
        "OneHot",
        "Ordinal",
    ]:
        assert gone not in public  # moved names (the step ones go later)
    assert {"Pipeline", "Step", "Search", "set_config", "get_config"} <= public
    assert {
        "cols",
        "fn",
        "out",
        "errors",
        "store",
        "metrics",
        "agg",
        "impute",
        "scale",
        "encode",
    } <= public

"""Tests of the package's top-level module."""

from importlib.metadata import version
from importlib.resources import files
from pathlib import Path


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

    builders = {"Pipeline", "Step", "set_config", "get_config"}
    groups = {
        "impute",
        "scale",
        "encode",
        "transform",
        "bin",
        "features",
        "agg",
        "search",
        "folds",
        "select",
        "decompose",
    }
    others = {
        "cols",
        "fn",
        "out",
        "metrics",
        "errors",
        "store",
        "save",
        "load",
    }
    kept = {"Learned", "Output", "Model", "__version__"}
    allowed = builders | groups | others | kept
    assert set(sq.__all__) == allowed
    # Python also sets each imported subpackage on the package.
    packages = {
        "decomposition",
        "feature_selection",
        "model_selection",
        "preprocessing",
    }
    public = {n for n in dir(sq) if not n.startswith("_")} | {"__version__"}
    assert public == allowed | packages


def test_every_fold_class_is_importable_for_annotations():
    """The fold schemes' classes stay importable from model_selection (ADR 0039)."""
    import sqlearn as sq
    from sqlearn import model_selection

    made = {
        "KFold": sq.folds.kfold(),
        "Stratified": sq.folds.stratified(),
        "Grouped": sq.folds.group("g"),
        "Holdout": sq.folds.holdout(),
        "TimeSplit": sq.folds.time("t"),
    }
    for name, scheme in made.items():
        assert name in model_selection.__all__
        assert isinstance(scheme, getattr(model_selection, name))


def test_the_package_holds_no_datasets() -> None:
    """Datasets stay outside the package: no folder, no data file, no import."""
    import sqlearn as sq

    package = Path(sq.__file__).parent
    assert not (package / "datasets").exists()
    assert not list(package.rglob("*.csv"))
    sources = package.rglob("*.py")
    assert not [p for p in sources if "devdata" in p.read_text()]

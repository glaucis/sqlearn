"""Steps and models as records, and the check of what a file may import."""

import json
import sys
from collections.abc import Callable

import numpy as np
import pytest
from sklearn.ensemble import BaggingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

import sqlearn as sq
from sqlearn._errors import SqlearnError
from sqlearn._saving.recipe import (
    build_model,
    build_step,
    check_allowed,
    class_path,
    import_class,
    model_record,
    step_record,
)
from sqlearn._step import Step

GROUPS = {
    "impute": sq.impute,
    "scale": sq.scale,
    "encode": sq.encode,
    "bin": sq.bin,
    "features": sq.features,
    "transform": sq.transform,
}

# Shortcuts that need an argument before they build.
NEEDS_ARGS: dict[str, Callable[[], Step]] = {
    "impute.constant": lambda: sq.impute.constant(0),
    "transform.clip": lambda: sq.transform.clip(lower=0),
}


def _default_cases() -> list[tuple[str, Callable[[], Step]]]:
    cases: list[tuple[str, Callable[[], Step]]] = []
    for group_name, group in GROUPS.items():
        for name in dir(group):
            if name.startswith("_") or not callable(getattr(group, name)):
                continue
            key = f"{group_name}.{name}"
            make: Callable[[], Step] = NEEDS_ARGS.get(key) or getattr(group, name)
            cases.append((key, make))
    return cases


# One entry per documented non-default setting value of each step.
DOCUMENTED_CHOICES: list[tuple[str, Callable[[], Step]]] = [
    ("impute value=median approx", lambda: sq.impute.median(approx=True)),
    ("impute value=quantile", lambda: sq.impute(value=sq.agg.quantile(q=0.9))),
    ("impute value=name", lambda: sq.impute("a", value="mode")),
    ("impute value=const text", lambda: sq.impute("a", value=sq.fn.const("median"))),
    ("impute value=number", lambda: sq.impute("a", value=0.5)),
    ("impute value=None", lambda: sq.impute("a", value=None)),
    ("impute value=dict", lambda: sq.impute({"a": sq.agg.median, "b": "unknown"})),
    ("impute indicator", lambda: sq.impute("a", indicator=True, keep=True)),
    ("impute suffix", lambda: sq.impute("a", keep=True, suffix="_f")),
    ("impute cols selector", lambda: sq.impute(sq.cols.numeric() | sq.cols("z"))),
    ("scale minmax range", lambda: sq.scale.minmax(feature_range=(-1, 1))),
    ("scale minmax no range", lambda: sq.scale.minmax(feature_range=None)),
    ("scale robust range", lambda: sq.scale.robust(quantile_range=(10.0, 90.0))),
    (
        "scale center and spread",
        lambda: sq.scale("a", center=sq.agg.median, spread=sq.agg.iqr(q=(0.1, 0.9))),
    ),
    ("scale center none", lambda: sq.scale("a", center=None, spread=sq.agg.std)),
    ("scale center name", lambda: sq.scale("a", center="mean", spread="max")),
    ("scale normalize l1", lambda: sq.scale.normalize(norm="l1")),
    ("scale normalize max", lambda: sq.scale.normalize(norm="max")),
    ("encode ordinal hash", lambda: sq.encode.ordinal(lookup="hash")),
    ("encode target settings", lambda: sq.encode.target(smooth=2.5, cv=3, seed=7)),
    (
        "encode target type",
        lambda: sq.encode.target(target_type="binary", lookup="hash"),
    ),
    ("bin uniform n", lambda: sq.bin.uniform(n=3)),
    ("bin quantile n", lambda: sq.bin.quantile(n=10, keep=True)),
    ("bin binarize threshold", lambda: sq.bin.binarize(threshold=2.5)),
    (
        "features polynomial",
        lambda: sq.features.polynomial(
            degree=3, interaction_only=True, include_bias=True
        ),
    ),
    (
        "features spline",
        lambda: sq.features.spline(n_knots=4, degree=2, knots="quantile"),
    ),
    ("transform clip both", lambda: sq.transform.clip(lower=-1.5, upper=2)),
    ("transform clip upper", lambda: sq.transform.clip(upper=1)),
]


def _same_step(original: Step, rebuilt: Step) -> None:
    assert type(rebuilt) is type(original)
    assert repr(rebuilt) == repr(original)
    assert rebuilt.settings() == original.settings()


@pytest.mark.parametrize(
    "make", [m for _, m in _default_cases()], ids=[k for k, _ in _default_cases()]
)
def test_every_public_step_round_trips_as_a_record(
    make: Callable[[], Step],
) -> None:
    """Every public step round trips as a record."""
    step = make()
    record = step_record("s", step, 1)
    rebuilt = build_step(json.loads(json.dumps(record)), "s")
    _same_step(step, rebuilt)


@pytest.mark.parametrize(
    "make", [m for _, m in DOCUMENTED_CHOICES], ids=[k for k, _ in DOCUMENTED_CHOICES]
)
def test_every_documented_choice_round_trips_as_a_record(
    make: Callable[[], Step],
) -> None:
    """Every documented choice round trips as a record."""
    step = make()
    rebuilt = build_step(json.loads(json.dumps(step_record("s", step, 1))), "s")
    _same_step(step, rebuilt)


def test_every_shortcut_has_a_default_case() -> None:
    """A group that gains a shortcut with no case fails here."""
    for group_name, group in GROUPS.items():
        for name in dir(group):
            if name.startswith("_"):
                continue
            key = f"{group_name}.{name}"
            attribute = getattr(group, name)
            if not callable(attribute):
                continue
            step = NEEDS_ARGS.get(key, attribute)()
            assert isinstance(step, Step), key


def test_a_step_record_has_its_name_class_version_and_every_setting() -> None:
    """A step record has its name class version and every setting."""
    record = step_record("impute", sq.impute.median(), 1)
    assert list(record) == ["name", "class", "state_version", "settings"]
    assert record["name"] == "impute"
    assert record["class"] == "sqlearn.preprocessing.impute:Impute"
    assert record["state_version"] == 1
    settings = record["settings"]
    assert isinstance(settings, dict)
    assert list(settings) == list(sq.impute.median().settings())


def test_an_aggregate_built_by_hand_is_refused() -> None:
    """An aggregate built by hand is refused."""
    mine = sq.agg.Aggregate("mean", lambda x: x)
    with pytest.raises(SqlearnError, match=r"(?s)step 2.*value.*Fix:"):
        step_record("impute", sq.impute("a", value=mine), 2)


def test_a_model_and_its_nested_estimators_round_trip() -> None:
    """A model and its nested estimators round trip."""
    estimator = BaggingClassifier(LogisticRegression(C=np.float64(0.5)))
    model = sq.Model(estimator, feed="pandas")
    record = json.loads(json.dumps(model_record(model, 4)))
    assert list(record) == ["name", "class", "settings", "estimator"]
    assert record["class"] == "sqlearn._model:Model"
    rebuilt = build_model(record, "model")
    assert isinstance(rebuilt, sq.Model)
    deep = {k: repr(v) for k, v in rebuilt.estimator.get_params(deep=True).items()}
    plain = BaggingClassifier(LogisticRegression(C=0.5))
    assert deep == {k: repr(v) for k, v in plain.get_params(deep=True).items()}
    inner = rebuilt.estimator.get_params(deep=False)["estimator"]
    assert type(inner.C) is float
    assert inner.C == 0.5
    for field in ("feed", "rows", "megabytes", "epochs", "shuffle", "seed"):
        assert getattr(rebuilt, field) == getattr(model, field)


def test_a_model_with_estimators_in_a_list_round_trips() -> None:
    """A model with estimators in a list round trips."""
    estimator = Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression())])
    record = json.loads(json.dumps(model_record(sq.Model(estimator), 1)))
    rebuilt = build_model(record, "model")
    assert [name for name, _ in rebuilt.estimator.steps] == ["scale", "clf"]
    assert isinstance(rebuilt.estimator.steps[0][1], StandardScaler)


def test_a_callable_parameter_is_refused() -> None:
    """A callable parameter is refused."""
    model = sq.Model(SVC(kernel=lambda a, b: a @ b.T))
    with pytest.raises(SqlearnError, match=r"(?s)kernel.*Fix:"):
        model_record(model, 1)


def test_a_package_not_allowed_is_refused_before_any_import() -> None:
    """A package not allowed is refused before any import."""
    sys.modules.pop("sqlearn_test_imported", None)
    paths = {"tests.src.sqlearn._saving.recorded_import:X", "os:system"}
    with pytest.raises(SqlearnError) as raised:
        check_allowed(paths, ())
    message = str(raised.value)
    assert "'os'" in message
    assert "'tests'" in message
    assert "allow=['os', 'tests']" in message
    assert "sqlearn_test_imported" not in sys.modules


def test_sqlearn_and_the_allowed_packages_pass() -> None:
    """Sqlearn and the allowed packages pass."""
    check_allowed(
        {"sqlearn.preprocessing.impute:Impute", "sklearn.svm:SVC"}, ["sklearn"]
    )


def test_a_step_class_from_main_is_refused() -> None:
    """A step class from main is refused."""

    class Mine(Step):
        pass

    Mine.__module__ = "__main__"
    with pytest.raises(SqlearnError, match=r"(?s)__main__.*Fix:"):
        class_path(Mine, "mine")


def test_a_class_defined_in_a_function_is_refused() -> None:
    """A class defined in a function is refused."""

    class Local(Step):
        pass

    with pytest.raises(SqlearnError, match=r"(?s)function.*Fix:"):
        class_path(Local, "local")


def test_a_class_of_the_wrong_kind_is_refused() -> None:
    """A class of the wrong kind is refused."""
    with pytest.raises(SqlearnError, match=r"(?s)OrderedDict.*Step.*Fix:"):
        import_class("collections:OrderedDict", "step", "s")
    with pytest.raises(SqlearnError, match=r"fit.*predict"):
        import_class("collections:OrderedDict", "model", "s")


def test_a_missing_module_or_class_is_refused() -> None:
    """A missing module or class is refused."""
    with pytest.raises(SqlearnError, match=r"(?s)no_such_module.*Fix:.*install"):
        import_class("no_such_module:X", "object", "s")
    with pytest.raises(SqlearnError, match=r"(?s)NoSuch.*Fix:"):
        import_class("collections:NoSuch", "object", "s")
    with pytest.raises(SqlearnError, match="Fix:"):
        import_class("nocolon", "object", "s")


def test_a_bad_setting_in_a_record_names_the_place() -> None:
    """A bad setting in a record names the place."""
    record = step_record("impute", sq.impute.median(), 3)
    settings = record["settings"]
    assert isinstance(settings, dict)
    settings["bogus"] = 1
    with pytest.raises(SqlearnError, match=r"^impute \(step 3\): .*bogus"):
        build_step(record, "impute (step 3)")


def test_a_streaming_models_settings_round_trip() -> None:
    """A streaming models settings round trip."""
    model = sq.Model(
        LogisticRegression(), feed="stream", rows=50, epochs=2, shuffle=False, seed=3
    )
    rebuilt = build_model(json.loads(json.dumps(model_record(model, 1))), "model")
    for field in ("feed", "rows", "megabytes", "epochs", "shuffle", "seed"):
        assert getattr(rebuilt, field) == getattr(model, field)

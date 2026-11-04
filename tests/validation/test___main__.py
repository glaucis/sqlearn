"""The validation's entry point: runs every runner, writes, and gates."""

import types

from validation import __main__ as entry


def fake_runner(tmp_path, name, result):
    """A runner module whose one case has the given result."""
    module = types.ModuleType(name)
    module.__file__ = str(tmp_path / f"validate_{name}.py")
    case = {"step": name, "reference": "sqlearn", "result": result}
    module.cases = lambda: [case]  # ty: ignore[unresolved-attribute]
    return module


def test_a_failing_runner_makes_it_exit_one(tmp_path):
    """One sqlearn case outside its bound fails the whole validation."""
    runners = [
        fake_runner(tmp_path, "good", "pass"),
        fake_runner(tmp_path, "bad", "fail"),
    ]
    assert entry.main(runners, tmp_path) == 1
    assert (tmp_path / "bad.results.json").is_file()
    assert (tmp_path / "environment.json").is_file()


def test_passing_runners_exit_zero_and_write_their_results(tmp_path):
    """Every case passing, or an anomaly in a reference, exits 0."""
    runners = [
        fake_runner(tmp_path, "good", "pass"),
        fake_runner(tmp_path, "odd", "anomaly"),
    ]
    assert entry.main(runners, tmp_path) == 0
    assert '"result": "anomaly"' in (tmp_path / "odd.results.json").read_text()


def test_results_path_mirrors_the_runner():
    """validate_scale.py writes scale.results.json beside it."""
    module = types.ModuleType("x")
    module.__file__ = "/a/b/validate_scale.py"
    assert str(entry.results_path(module)) == "/a/b/scale.results.json"

"""A group's C++ tests run when its program changed (spec §6 step 2).

On a scratch engine of two stand-in groups (``engine_scratch``, the tests'
conftest), built by the real ``cmake`` and ``ninja``.
"""

from validation import _checks, _ctest


def test_a_change_to_one_groups_file_runs_that_group_only(engine_scratch, capsys):
    """An edited ``raw`` source rebuilds and runs ``test_raw`` alone."""
    scratch = engine_scratch
    assert _ctest.run("dev", scratch.root) == 0
    assert sorted(scratch.runs()) == ["core", "raw"]
    capsys.readouterr()
    scratch.program("raw", text="raw, edited")
    assert _ctest.run("dev", scratch.root) == 0
    assert scratch.runs() == ["raw, edited"]
    out = capsys.readouterr().out
    assert "core: unchanged since a passed run" in out
    assert "must_not_compile: unchanged since a passed run" in out
    assert "raw: unchanged" not in out


def test_a_run_records_the_groups_that_passed_never_the_failed_one(
    engine_scratch, capsys
):
    """A failing ``raw`` runs again next time; ``core``, which passed, does not."""
    scratch = engine_scratch
    scratch.program("raw", code=1)
    assert _ctest.run("dev", scratch.root) != 0
    assert sorted(scratch.runs()) == ["core", "raw"]
    capsys.readouterr()
    assert _ctest.run("dev", scratch.root) != 0
    assert scratch.runs() == ["raw"]
    assert "core: unchanged since a passed run" in capsys.readouterr().out


def test_everything_runs_every_group(engine_scratch, capsys):
    """``everything`` runs a group that passed unchanged, and every other."""
    scratch = engine_scratch
    assert _ctest.run("dev", scratch.root) == 0
    scratch.runs()
    capsys.readouterr()
    assert _ctest.run("dev", scratch.root, everything=True) == 0
    assert sorted(scratch.runs()) == ["core", "raw"]
    assert "unchanged" not in capsys.readouterr().out


def test_a_change_to_a_core_object_raw_does_not_use_leaves_raw_alone(
    engine_scratch, capsys
):
    """An edited ``core`` object ``test_raw`` does not pull in reruns ``core`` alone."""
    scratch = engine_scratch
    assert _ctest.run("dev", scratch.root) == 0
    scratch.runs()
    capsys.readouterr()
    alone = scratch.root / "engine" / "src" / "core" / "alone.cpp"
    alone.write_text(
        "static volatile int three = 3;\nint core_alone() { return three - 3; }\n"
    )
    assert _ctest.run("dev", scratch.root) == 0
    assert scratch.runs() == ["core"]
    assert "raw: unchanged since a passed run" in capsys.readouterr().out


def test_due_names_the_label_a_change_reruns(engine_scratch):
    """An edited ``raw`` source gives ``raw`` a reason, ``core`` none; no test runs."""
    scratch = engine_scratch
    assert _ctest.run("dev", scratch.root) == 0
    scratch.runs()
    (scratch.root / "engine" / "src" / "raw" / "lib.cpp").write_text(
        "int core_used();\nint raw_lib() { return core_used() * 2; }\n"
    )
    directory = _checks.record_dir(scratch.root)
    before = {p.name: p.read_bytes() for p in directory.glob("*")}
    due = _ctest.due("dev", scratch.root)
    assert due["raw"] == ["its test program, data or command changed"]
    assert due["core"] == []
    assert due["must_not_compile"] == []
    assert scratch.runs() == []
    assert {p.name: p.read_bytes() for p in directory.glob("*")} == before

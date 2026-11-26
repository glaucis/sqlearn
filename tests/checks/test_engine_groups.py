"""A group's C++ tests run when its program changed (spec §6 step 2).

On a scratch engine of two stand-in groups (``engine_scratch``, the tests'
conftest), built by the real ``cmake`` and ``ninja``.
"""

from validation import _ctest


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

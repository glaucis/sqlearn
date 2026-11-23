"""The C++ tests' records: what a group's identity is, and what reruns it.

On the scratch engine of the tests' conftest (``engine_scratch``).
"""

import os

from validation import _checks, _ctest


def _passes(scratch):
    """Run the scratch engine's tests and return the programs that ran."""
    assert _ctest.run("dev", scratch.root) == 0
    return sorted(scratch.runs())


def test_a_relinked_program_of_the_same_objects_is_not_rerun(engine_scratch):
    """A touched source relinks its program with the same bytes: no rerun.

    Built with debug information, whose map on Apple's linker would hold
    each object's modification time but for ``sq_stable_link``.
    """
    scratch = engine_scratch
    _passes(scratch)
    source = scratch.root / "engine" / "src" / "core.cpp"
    later = source.stat().st_mtime + 10
    os.utime(source, (later, later))
    assert _passes(scratch) == []


def test_a_must_not_compile_test_reruns_when_a_header_changes(engine_scratch, capsys):
    """A header under its include path reruns it; a group's source does not."""
    scratch = engine_scratch
    _passes(scratch)
    capsys.readouterr()
    scratch.program("core", text="core, edited")
    _passes(scratch)
    assert "must_not_compile: unchanged" in capsys.readouterr().out
    header = scratch.root / "engine" / "src" / "common.hpp"
    header.write_text("#define SQ_FINE 0 // edited\n")
    assert _passes(scratch) == []
    out = capsys.readouterr().out
    assert "must_not_compile: unchanged" not in out
    assert "core: unchanged since a passed run" in out


def test_an_unreadable_record_counts_as_absent(engine_scratch):
    """A record file that does not parse reruns every group, never crashes."""
    scratch = engine_scratch
    _passes(scratch)
    record = _checks.record_dir(scratch.root) / "ctest-dev.json"
    assert record.exists()
    record.write_text("{not json")
    assert _passes(scratch) == ["core", "raw"]


def test_another_compiler_reruns_every_group(engine_scratch, monkeypatch):
    """The compiler's id and version are part of the place every record names."""
    scratch = engine_scratch
    _passes(scratch)
    real = _ctest.compiler

    def other(build):
        return real(build) + " (another)"

    monkeypatch.setattr(_ctest, "compiler", other)
    assert _passes(scratch) == ["core", "raw"]


def test_a_test_without_a_label_is_refused_with_a_fix(engine_scratch, capsys):
    """A test no group label selects would never run: the checks refuse it."""
    scratch = engine_scratch
    lists = scratch.root / "engine" / "CMakeLists.txt"
    lists.write_text(lists.read_text() + "add_test(NAME loose COMMAND test_core)\n")
    assert _ctest.run("dev", scratch.root) != 0
    out = capsys.readouterr().out
    assert "loose" in out
    assert "Fix:" in out
    assert scratch.runs() == []


def test_a_build_failure_runs_and_records_nothing(engine_scratch):
    """A group that does not compile: no program runs, nothing is recorded."""
    scratch = engine_scratch
    (scratch.root / "engine" / "src" / "raw.cpp").write_text("int main( {\n")
    assert _ctest.run("dev", scratch.root) != 0
    assert scratch.runs() == []
    assert not (_checks.record_dir(scratch.root) / "ctest-dev.json").exists()


def test_the_command_line_takes_the_preset_and_all(engine_scratch, monkeypatch):
    """``python -m validation._ctest dev --all`` runs every group."""
    scratch = engine_scratch
    _passes(scratch)
    monkeypatch.chdir(scratch.root)
    assert _ctest.cli(["dev"]) == 0
    assert scratch.runs() == []
    assert _ctest.cli(["dev", "--all"]) == 0
    assert sorted(scratch.runs()) == ["core", "raw"]

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
    engine = scratch.root / "engine"
    # Found in the source's own directory, then through -isystem: no -I.
    for header in (
        engine / "src" / "common.hpp",
        engine / "include" / "sys_common.hpp",
    ):
        header.write_text(header.read_text() + "// edited\n")
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


def test_a_test_without_a_timeout_is_refused_with_a_fix(engine_scratch, capsys):
    """A test with no TIMEOUT could hang a run for hours: the checks refuse it
    and run nothing."""
    scratch = engine_scratch
    lists = scratch.root / "engine" / "CMakeLists.txt"
    lists.write_text(
        lists.read_text()
        + "add_test(NAME endless COMMAND test_core)\n"
        + "set_tests_properties(endless PROPERTIES LABELS core)\n"
    )
    assert _ctest.run("dev", scratch.root) != 0
    out = capsys.readouterr().out
    assert "endless" in out
    assert "TIMEOUT" in out
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


def test_a_compiler_updated_in_place_reruns_every_group(engine_scratch, capsys):
    """The same compiler path with new bytes: a fresh configure, every group."""
    scratch = engine_scratch
    _passes(scratch)
    capsys.readouterr()
    scratch.compiler.write_text(scratch.compiler.read_text() + "# updated\n")
    assert _passes(scratch) == ["core", "raw"]
    out = capsys.readouterr().out
    assert "must_not_compile: unchanged" not in out
    assert "configuring afresh" in out


def test_a_changed_shared_library_reruns_the_group_that_loads_it(
    engine_scratch, capsys
):
    """``core`` loads ``extra``: a new ``extra`` reruns ``core``, not ``raw``."""
    scratch = engine_scratch
    _passes(scratch)
    capsys.readouterr()
    library = scratch.root / "engine" / "src" / "extra.cpp"
    library.write_text(
        "static volatile int three = 3;\n"
        '__attribute__((visibility("default"))) int extra() { return three - 3; }\n'
    )
    assert _passes(scratch) == ["core"]
    assert "raw: unchanged since a passed run" in capsys.readouterr().out


def test_the_sanitizers_options_rerun_every_group(engine_scratch, monkeypatch):
    """``ASAN_OPTIONS`` changes what a test checks with the same program."""
    scratch = engine_scratch
    _passes(scratch)
    monkeypatch.setenv("ASAN_OPTIONS", "detect_stack_use_after_return=1")
    assert _passes(scratch) == ["core", "raw"]


def test_a_groups_data_file_reruns_that_group(engine_scratch, capsys):
    """A file ``sq_test_data`` names for ``raw`` reruns ``raw`` alone."""
    scratch = engine_scratch
    _passes(scratch)
    capsys.readouterr()
    (scratch.root / "engine" / "data" / "raw.txt").write_text("other data\n")
    assert _passes(scratch) == ["raw"]
    assert "core: unchanged since a passed run" in capsys.readouterr().out


def test_a_failure_cancels_a_pass_of_the_same_identity(engine_scratch):
    """Failed under ``--all`` with the same programs: next time they run again."""
    scratch = engine_scratch
    _passes(scratch)
    fail = scratch.log.with_name(scratch.log.name + ".fail")
    fail.touch()
    assert _ctest.run("dev", scratch.root, everything=True) != 0
    scratch.runs()
    fail.unlink()
    assert _passes(scratch) == ["core", "raw"]


def test_a_nested_rpath_library_is_found_through_the_programs_run_paths(tmp_path):
    """``a`` names ``@rpath/libb`` and has no run path; the program's finds it.

    dyld searches the run paths of the whole chain that loaded a library,
    the program's included: so ``libb``, which only the program's run path
    reaches, is loaded, and a new ``libb`` must rerun the program's group.
    """
    import shutil
    import subprocess
    import sys

    import pytest

    if sys.platform != "darwin" or shutil.which("c++") is None:
        pytest.skip("Mach-O run paths: macOS with a compiler")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    def build(*argv):
        subprocess.run(["c++", *argv], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "b.cpp").write_text("int fb() { return 0; }\n")
    (tmp_path / "a.cpp").write_text("int fb();\nint fa() { return fb(); }\n")
    (tmp_path / "main.cpp").write_text("int fa();\nint main() { return fa(); }\n")
    build(
        "-dynamiclib",
        "b.cpp",
        "-install_name",
        "@rpath/libb.dylib",
        "-o",
        "b/libb.dylib",
    )
    build(
        "-dynamiclib",
        "a.cpp",
        "-install_name",
        "@rpath/liba.dylib",
        "b/libb.dylib",
        "-o",
        "a/liba.dylib",
    )
    build(
        "main.cpp",
        "a/liba.dylib",
        "-Wl,-rpath,@executable_path/a",
        "-Wl,-rpath,@executable_path/b",
        "-o",
        "program",
    )
    program = tmp_path / "program"
    assert subprocess.run([program], check=False).returncode == 0
    found = _ctest._libraries(program)
    assert [x.split("\0")[0] for x in found] == sorted(
        [str((a / "liba.dylib").resolve()), str((b / "libb.dylib").resolve())]
    )


def test_corrupt_ctest_output_is_refused_with_a_fix(
    engine_scratch, capsys, monkeypatch
):
    """A test listing or compile_commands.json that does not parse stops the
    run with a Fix line, never a traceback."""
    scratch = engine_scratch
    real = _ctest.subprocess.run

    def garbled(argv, *args, **kwargs):
        done = real(argv, *args, **kwargs)
        if "--show-only=json-v1" in argv:
            done.stdout = "{not json"
        return done

    monkeypatch.setattr(_ctest.subprocess, "run", garbled)
    assert _ctest.run("dev", scratch.root) != 0
    out = capsys.readouterr().out
    assert "Fix:" in out
    assert scratch.runs() == []
    monkeypatch.undo()
    # The build step would write the file afresh: leave it out.
    monkeypatch.setattr(_ctest, "_build", lambda *a, **k: (0, "compiler"))
    commands = scratch.root / "engine" / "build" / "dev" / "compile_commands.json"
    commands.write_text("[{broken")
    assert _ctest.run("dev", scratch.root) != 0
    assert "Fix:" in capsys.readouterr().out

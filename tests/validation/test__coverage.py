"""The coverage gate of our C++: the programs it measures, the totals it
reads from llvm-cov, the sources no program compiles, and the floor."""

from pathlib import Path

from validation import _coverage


def _export(files: dict[str, tuple[int, int]], totals: dict[str, tuple[int, int]]):
    """Return an llvm-cov export: covered and count of each file's lines, and
    of the totals' lines, regions and branches."""

    def summary(covered: int, count: int) -> dict[str, float]:
        percent = 100.0 * covered / count if count else 0.0
        return {"count": count, "covered": covered, "percent": percent}

    return {
        "type": "llvm.coverage.json.export",
        "data": [
            {
                "files": [
                    {"filename": name, "summary": {"lines": summary(*lines)}}
                    for name, lines in files.items()
                ],
                "totals": {kind: summary(*pair) for kind, pair in totals.items()},
            }
        ],
    }


def test_the_programs_are_the_tests_that_run_a_program_of_the_build(tmp_path):
    """Each test whose command runs a program of the build, once; never a
    must-not-compile test, whose command is cmake."""
    build = tmp_path / "build"
    (build / "fuzz").mkdir(parents=True)
    for name in ("test_core", "test_raw", "fuzz/replay"):
        (build / name).write_text("")
    listing = {
        "tests": [
            {"name": "test_core", "command": [str(build / "test_core")]},
            {"name": "test_raw", "command": [str(build / "test_raw")]},
            {"name": "replay", "command": [str(build / "fuzz/replay"), "/corpus/a"]},
            {"name": "again", "command": [str(build / "test_core"), "--order", "rand"]},
            {"name": "must_not_compile.x", "command": ["/bin/cmake", "--build", "."]},
            {"name": "disabled"},
        ]
    }
    assert _coverage.programs(listing, build) == [
        build / "fuzz/replay",
        build / "test_core",
        build / "test_raw",
    ]


def test_the_totals_are_lines_regions_and_branches():
    """Each kind's covered and count, as llvm-cov counts them."""
    export = _export(
        {"/e/src/core/a.cpp": (9, 10)},
        {"lines": (9, 10), "regions": (3, 4), "branches": (1, 2), "functions": (1, 1)},
    )
    assert _coverage.totals(export) == {
        "lines": (9, 10),
        "regions": (3, 4),
        "branches": (1, 2),
    }


def test_a_source_no_program_compiles_is_unmeasured(tmp_path):
    """A .cpp of engine/src outside bindings/ that is in no program would be
    left out of the totals unseen, so it is named."""
    src = tmp_path / "engine" / "src"
    for name in (
        "core/a.cpp",
        "core/a.hpp",
        "raw/b.cpp",
        "bindings/m.cpp",
        "new/c.cpp",
    ):
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text("")
    export = _export(
        {str(src / "core/a.cpp"): (1, 1), str(src / "raw/b.cpp"): (1, 1)},
        {"lines": (2, 2)},
    )
    assert _coverage.unmeasured(src, export) == [src / "new/c.cpp"]


def test_the_gate_fails_below_the_floor_of_lines():
    """95 % of lines passes, a line fewer fails; the regions and branches are
    printed, never gated."""
    assert _coverage.passes(
        {"lines": (95, 100), "regions": (0, 10), "branches": (0, 4)}
    )
    assert not _coverage.passes({"lines": (94, 100), "regions": (10, 10)})
    assert not _coverage.passes({"lines": (0, 0)})


def test_the_report_leaves_out_the_bindings_tests_and_libraries():
    """The report reads engine/src alone (so no test, fuzz, bench or
    third-party file), and its regex drops the bindings."""
    arguments = _coverage.report_arguments(
        Path("/e"), Path("/e/build/coverage/x.profdata"), [Path("/p/a"), Path("/p/b")]
    )
    assert arguments == [
        "-instr-profile=/e/build/coverage/x.profdata",
        "-ignore-filename-regex=/src/bindings/",
        "/p/a",
        "-object",
        "/p/b",
        "/e/src",
    ]

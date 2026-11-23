"""The tidy task's compile database: each source from the build that compiles
it, with commands the tools can run outside that build."""

from pathlib import Path

from validation import _tidy


def test_each_source_comes_from_the_build_that_compiles_it():
    """The bindings and extension from the wheel's build, the benchmarks from
    release, the groups and their tests from llvm-dev."""
    assert _tidy._build("engine/src/bindings/module.cpp") == "wheel"
    assert _tidy._build("engine/extension/src/sqlearn_extension.cpp") == "wheel"
    assert _tidy._build("engine/bench/bench_buffer.cpp") == "release"
    assert _tidy._build("engine/src/core/error.cpp") == "llvm-dev"
    assert _tidy._build("engine/tests/raw/test_buffer.cpp") == "llvm-dev"


def test_a_command_runs_outside_its_build(monkeypatch, tmp_path):
    """A nanobind include from a build environment that is gone becomes this
    one's, a module map is dropped, and the SDK is named when missing."""
    monkeypatch.setattr(_tidy, "_nanobind_include", lambda: "/here/nanobind/include")
    gone = str(tmp_path / "gone" / "nanobind" / "include")
    kept = str(tmp_path)
    command = ["c++", "-isystem", gone, "-isystem", kept, "@x.o.modmap", "-c", "a.cpp"]
    assert _tidy._fixed(command, ["-isysroot", "/sdk"]) == [
        "c++",
        "-isysroot",
        "/sdk",
        "-isystem",
        "/here/nanobind/include",
        "-isystem",
        kept,
        "-c",
        "a.cpp",
    ]
    named = ["c++", "-isysroot", "/other", "-c", "a.cpp"]
    assert _tidy._fixed(named, ["-isysroot", "/sdk"]) == named


def test_the_sources_are_ours_alone():
    """Never a must-not-compile or must-not-pass-tidy case, never a header."""
    root = Path(__file__).resolve().parents[2]
    names = _tidy.sources(root)
    assert "engine/src/core/error.cpp" in names
    assert "engine/bench/bench_buffer.cpp" in names
    assert not [n for n in names if "/must_not_" in n or not n.endswith(".cpp")]
    assert not [
        n
        for n in names
        if n.startswith(("engine/duckdb-python/", "engine/third_party/"))
    ]

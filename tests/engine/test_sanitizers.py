"""The sanitizer presets, their canaries, and the build rules beside them.

Each sanitizer has a preset whose canary, a program with the one fault that
sanitizer finds, must be stopped by it with its report (`just sanitize` runs
them). Beside them: ccache asks the compiler behind a shim for its version,
and a test's data is files, never a directory.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
CMAKE = ENGINE / "cmake"
EXPECT = ENGINE / "tests" / "canary" / "expect_finding.cmake"
SANITIZERS = {"tsan": False, "lsan": True, "tysan": True}
"""Each sanitizer preset beside dev, and whether it needs Homebrew LLVM."""

needs_cmake = pytest.mark.skipif(shutil.which("cmake") is None, reason="no cmake")


def _presets() -> dict[str, dict[str, Any]]:
    """Return the configure presets, by name."""
    data = json.loads((ENGINE / "CMakePresets.json").read_text())
    return {p["name"]: p for p in data["configurePresets"]}


def _resolved(name: str, key: str, presets: dict[str, dict[str, Any]]) -> Any:
    """Return `key` of preset `name`, following its `inherits` chain."""
    preset = presets[name]
    if key in preset:
        return preset[key]
    parents = preset.get("inherits", [])
    for parent in [parents] if isinstance(parents, str) else parents:
        found = _resolved(parent, key, presets)
        if found is not None:
            return found
    return None


def _variable(name: str, variable: str, presets: dict[str, dict[str, Any]]) -> Any:
    """Return cache variable `variable` of preset `name`, inherited or its own."""
    own = presets[name].get("cacheVariables", {})
    if variable in own:
        return own[variable]
    parents = presets[name].get("inherits", [])
    for parent in [parents] if isinstance(parents, str) else parents:
        found = _variable(parent, variable, presets)
        if found is not None:
            return found
    return None


def test_each_sanitizer_has_a_preset_of_its_flavour() -> None:
    """tsan, lsan and tysan build our groups alone, with their flavour;
    lsan and tysan with Homebrew LLVM, which alone has them on Apple silicon."""
    presets = _presets()
    for name, llvm in SANITIZERS.items():
        assert name in presets
        assert _variable(name, "SQ_FLAVOR", presets) == name
        assert _variable(name, "SQ_ENGINE_ONLY", presets) == "ON"
        toolchain = _resolved(name, "toolchainFile", presets) or ""
        assert toolchain.endswith("toolchain-llvm.cmake") == llvm, name
    data = json.loads((ENGINE / "CMakePresets.json").read_text())
    for kind in ("buildPresets", "testPresets"):
        assert set(SANITIZERS) <= {p["name"] for p in data[kind]}, kind


def test_just_sanitize_runs_every_sanitizer_preset() -> None:
    """The recipe runs dev (ASan, UBSan) and each sanitizer preset, every group."""
    justfile = (REPO / "justfile").read_text()
    recipe = justfile.split("\nsanitize:\n", 1)[1].split("\n\n", 1)[0]
    assert "for preset in dev tsan lsan tysan" in recipe
    assert "validation._ctest" in recipe
    assert "--all" in recipe


def _expect(tmp_path: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run the canary check on a shell program `script`, its report regex fixed."""
    program = tmp_path / "canary.sh"
    program.write_text(f"#!/bin/sh\n{script}\n")
    program.chmod(0o755)
    return subprocess.run(
        [
            "cmake",
            "-DREPORT=ERROR: AddressSanitizer: heap-buffer-overflow",
            "-P",
            str(EXPECT),
            str(program),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@needs_cmake
def test_a_canary_passes_only_when_its_sanitizer_stopped_it(tmp_path: Path) -> None:
    """Stopped (a non-zero exit) with the sanitizer's report: the canary passes.
    A report the program survived, or a stop for another reason, fails it."""
    report = "echo '==1==ERROR: AddressSanitizer: heap-buffer-overflow' >&2"
    assert _expect(tmp_path, f"{report}\nexit 1").returncode == 0
    survived = _expect(tmp_path, f"{report}\nexit 0")
    assert survived.returncode != 0
    assert "Fix:" in survived.stderr
    other = _expect(tmp_path, "echo 'Segmentation fault' >&2\nexit 139")
    assert other.returncode != 0
    assert "Fix:" in other.stderr


def _listed(preset: str) -> dict[str, dict[str, Any]]:
    """Return the CTest tests of a configured preset, by name; skip without it."""
    build = ENGINE / "build" / preset
    if not (build / "CTestTestfile.cmake").exists():
        pytest.skip(f"{preset} is not built here: just sanitize")
    listing = subprocess.run(
        ["ctest", "--test-dir", str(build), "--show-only=json-v1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {t["name"]: t for t in json.loads(listing)["tests"]}


@pytest.mark.parametrize(
    ("preset", "canaries"),
    [
        ("dev", {"canary.asan", "canary.ubsan"}),
        ("tsan", {"canary.tsan"}),
        ("lsan", {"canary.lsan"}),
        ("tysan", {"canary.tysan"}),
    ],
)
def test_each_sanitizer_preset_has_its_canaries_alone(
    preset: str, canaries: set[str]
) -> None:
    """A preset registers its sanitizer's canaries, no other's, and every group."""
    tests = _listed(preset)
    assert {n for n in tests if n.startswith("canary.")} == canaries
    assert {"test_core", "test_raw"} <= set(tests)


def _group_programs(tests: dict[str, dict[str, Any]]) -> set[str]:
    """Return the groups' test programs among `tests` (test_<group>)."""
    return {n for n in tests if n.startswith("test_")}


def test_only_the_crash_group_is_left_out_of_tysan() -> None:
    """TypeSanitizer cannot see the kernel's writes of siginfo and ucontext,
    which every crash case reads, so the tysan preset leaves out test_crash:
    every other group's program runs under it, as under dev."""
    assert _group_programs(_listed("tysan")) == _group_programs(_listed("dev")) - {
        "test_crash"
    }
    assert "test_crash" in _listed("dev")


@needs_cmake
def test_a_tests_data_directory_is_refused_with_a_fix(tmp_path: Path) -> None:
    """``sq_test_data`` takes files: a directory would hash as nothing."""
    (tmp_path / "data").mkdir()
    script = tmp_path / "run.cmake"
    script.write_text(
        f'include("{(CMAKE / "groups.cmake").as_posix()}")\n'
        f'sq_test_data(test_x "{(tmp_path / "data").as_posix()}")\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode != 0
    text = " ".join(done.stderr.split())
    assert "is a directory" in text
    assert "Fix: name each file it reads" in text


def _launcher(tmp_path: Path, before: str) -> str:
    """Return the C++ launcher ``sq_ccache`` sets, from `before`, ccache faked."""
    fake = tmp_path / "bin" / "ccache"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    script = tmp_path / "run.cmake"
    script.write_text(
        f'include("{(CMAKE / "ccache.cmake").as_posix()}")\n'
        f"{before}\n"
        f'sq_ccache("{fake.parent.as_posix()}")\n'
        'message(STATUS "CXX=${CMAKE_CXX_COMPILER_LAUNCHER}")\n'
        'message(STATUS "C=${CMAKE_C_COMPILER_LAUNCHER}")\n'
    )
    done = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=True
    )
    return done.stdout


@needs_cmake
def test_ccache_asks_the_compiler_behind_a_shim_for_its_version(
    tmp_path: Path,
) -> None:
    """ccache's default check is the compiler's file and time: /usr/bin/c++, the
    xcrun shim, stays the same through an Xcode update, so old objects would
    serve the new compiler. ``sq_ccache`` sets the check to its --version."""
    fake = (tmp_path / "bin" / "ccache").as_posix()
    check = "CCACHE_COMPILERCHECK=%compiler% --version"
    for before in ("", f'set(CMAKE_CXX_COMPILER_LAUNCHER "{fake}")'):
        out = _launcher(tmp_path, before)
        for language in ("CXX", "C"):
            line = next(x for x in out.splitlines() if f"-- {language}=" in x)
            assert check in line, (before, line)
            assert line.endswith(fake), line
    other = _launcher(tmp_path, 'set(CMAKE_CXX_COMPILER_LAUNCHER "/bin/distcc")')
    assert "-- CXX=/bin/distcc" in other


def test_every_build_reads_sq_ccache_before_duckdb() -> None:
    """The presets' builds and the wheel's take the launcher from engine/
    CMakeLists.txt, set before duckdb-python would pick a bare ccache."""
    lists = (ENGINE / "CMakeLists.txt").read_text()
    assert lists.index("sq_ccache(") < lists.index("add_subdirectory(duckdb-python)")
    presets = (ENGINE / "CMakePresets.json").read_text()
    assert "COMPILER_LAUNCHER" not in presets


def _launchers(cache: Path) -> dict[str, str]:
    """Return the C and C++ launchers a configured build's cache holds."""
    lines = cache.read_text().splitlines()
    return {
        language: next(
            x for x in lines if x.startswith(f"CMAKE_{language}_COMPILER_LAUNCHER:")
        )
        for language in ("CXX", "C")
    }


@needs_cmake
@pytest.mark.skipif(shutil.which("ccache") is None, reason="no ccache")
@pytest.mark.parametrize("preset", ["release", "lsan"])
def test_a_presets_build_checks_the_compiler_by_version(
    preset: str, tmp_path: Path
) -> None:
    """A preset configured afresh (Apple clang's, Homebrew LLVM's) launches
    ccache with the compiler check."""
    subprocess.run(
        ["cmake", "--preset", preset, "-B", str(tmp_path / "build")],
        cwd=ENGINE,
        capture_output=True,
        check=True,
    )
    for language, launcher in _launchers(tmp_path / "build" / "CMakeCache.txt").items():
        assert "CCACHE_COMPILERCHECK=%compiler% --version" in launcher, language


def test_the_wheels_build_checks_the_compiler_by_version() -> None:
    """The wheel's build, as configured here, launches ccache the same way."""
    caches = sorted((REPO / "build").glob("*/CMakeCache.txt"))
    if not caches:
        pytest.skip("no wheel build here yet: uv sync makes one")
    for cache in caches:
        for language, launcher in _launchers(cache).items():
            assert "CCACHE_COMPILERCHECK=%compiler% --version" in launcher, (
                cache,
                language,
            )


@pytest.mark.parametrize(
    ("preset", "ours"),
    [
        ("tsan", {"TSAN_OPTIONS": "halt_on_error=1"}),
        ("tysan", {"TYSAN_OPTIONS": "halt_on_error=1"}),
        ("llvm-dev", {"ASAN_OPTIONS": "detect_leaks=1"}),
    ],
)
def test_a_flavours_options_go_before_the_users(
    preset: str, ours: dict[str, str]
) -> None:
    """Each group's test and canary prepend the flavour's options to the user's
    own (ENVIRONMENT_MODIFICATION), never replace them: the sanitizers read
    left to right, so an option the user exported wins, and the checks hash
    the test's property and the user's variable both."""
    tests = _listed(preset)
    for name in (
        "test_core",
        "test_raw",
        *[n for n in tests if n.startswith("canary.")],
    ):
        props = {p["name"]: p["value"] for p in tests[name].get("properties", [])}
        assert "ENVIRONMENT" not in props, name
        wanted = {f"{k}=string_prepend:{v}:" for k, v in ours.items()}
        assert wanted <= set(props.get("ENVIRONMENT_MODIFICATION", [])), name


def test_a_users_option_wins_over_the_flavours() -> None:
    """With TYSAN_OPTIONS=halt_on_error=0 exported, TypeSanitizer lets the
    canary run to its end, and the canary's test fails, as it should."""
    _listed("tysan")
    build = ENGINE / "build" / "tysan"

    def run(options: str | None) -> int:
        env = {k: v for k, v in os.environ.items() if k != "TYSAN_OPTIONS"}
        if options is not None:
            env["TYSAN_OPTIONS"] = options
        return subprocess.run(
            ["ctest", "--test-dir", str(build), "-R", "^canary\\.tysan$"],
            capture_output=True,
            env=env,
            check=False,
        ).returncode

    assert run(None) == 0
    assert run("halt_on_error=0") != 0


def test_only_the_crash_group_is_left_out_of_leaks_engine() -> None:
    """just leaks-engine runs every group's program under leaks --atExit but
    test_crash, whose forked children hang under it."""
    justfile = (ENGINE.parent / "justfile").read_text()
    recipe = justfile[justfile.index("\nleaks-engine:") :]
    recipe = recipe[: recipe.index("\n\n")]
    assert re.findall(r"^\s*skip=\((.*)\)$", recipe, re.MULTILINE) == ["test_crash"]

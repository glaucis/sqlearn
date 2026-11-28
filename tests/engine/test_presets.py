"""The CMake presets name the builds spec §3.9 lists, and none of them, nor
the flag files they read, turns on fast math."""

import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
PRESETS = ENGINE / "CMakePresets.json"

# Flags that let the compiler change a floating-point result (ADR 0063).
FAST_MATH = re.compile(
    r"-ffast-math|-Ofast|-funsafe-math-optimizations|-fassociative-math"
    r"|-freciprocal-math|-ffinite-math-only|-fno-signed-zeros"
)


def _configure_presets() -> dict[str, dict[str, Any]]:
    """Return the configure presets of CMakePresets.json, by name."""
    data = json.loads(PRESETS.read_text())
    return {p["name"]: p for p in data["configurePresets"]}


def test_every_preset_named_in_the_spec_exists() -> None:
    """Spec §3.9's presets, and llvm-dev, are in CMakePresets.json."""
    assert {"dev", "debug", "release", "profile", "llvm-dev"} <= set(
        _configure_presets()
    )


def test_every_preset_builds_in_its_own_directory() -> None:
    """Each preset builds in engine/build/<preset>."""
    presets = _configure_presets()
    for name, preset in presets.items():
        if preset.get("hidden"):
            continue
        binary_dir = preset.get("binaryDir")
        parent = preset
        while binary_dir is None and "inherits" in parent:
            inherits = parent["inherits"]
            parent = presets[inherits if isinstance(inherits, str) else inherits[0]]
            binary_dir = parent.get("binaryDir")
        assert binary_dir == "${sourceDir}/build/${presetName}", name


def _our_cmake_files() -> list[Path]:
    """Every CMake file of ours under engine/: git lists only the files this
    repository tracks, so no submodule's (DuckDB, nanobind, the test libraries)
    is among them."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "engine"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    return sorted(
        REPO / name
        for name in listed
        if name and name.endswith((".cmake", "CMakeLists.txt"))
    )


def _code(text: str) -> str:
    """Return `text` without its # comments."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _wheel_defines() -> str:
    """Return pyproject.toml's [tool.scikit-build.cmake.define] table, as text."""
    text = (REPO / "pyproject.toml").read_text()
    start = text.index("[tool.scikit-build.cmake.define]")
    end = text.find("\n[", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_no_preset_sets_fast_math() -> None:
    """No preset, no CMake file of ours and no define of the wheel's build has a
    flag that changes floating-point results."""
    files = _our_cmake_files()
    assert ENGINE / "extension" / "CMakeLists.txt" in files
    assert ENGINE / "extension" / "sqlearn_config.cmake" in files
    assert ENGINE / "tests" / "CMakeLists.txt" in files
    texts = [PRESETS.read_text(), _wheel_defines()]
    texts += [p.read_text() for p in files]
    for text in texts:
        assert not FAST_MATH.search(_code(text))


def test_our_sources_never_contract_to_fma() -> None:
    """Our sources compile with FMA contraction off (spec §3.9): warnings.cmake
    sets it in code, not in a comment, and gives it to every target."""
    code = _code((ENGINE / "cmake" / "warnings.cmake").read_text())
    assert re.search(r"set\(\s*SQ_FP_OPTIONS\s+-ffp-contract=off\s*\)", code)
    function = code[code.index("function(sq_target_warnings") :]
    assert "${SQ_FP_OPTIONS}" in function.split("endfunction()")[0]


def _sq_warnings() -> list[str]:
    """Return the flags of SQ_WARNINGS in warnings.cmake, the Clang additions
    too."""
    code = _code((ENGINE / "cmake" / "warnings.cmake").read_text())
    flags = re.search(r"set\(\s*SQ_WARNINGS\s+(.*?)\)", code, re.S)
    assert flags
    found: list[str] = flags.group(1).split()
    for added in re.findall(r"list\(APPEND SQ_WARNINGS ([^)]*)\)", code):
        found += added.split()
    assert "-Wconversion" in found and "-Werror" in found
    return found


def test_the_wheel_compiles_our_sources_with_the_strict_flags() -> None:
    """The wheel's build gives the groups, bindings and extension the strict flags,
    with -Wunsafe-buffer-usage off in the raw layer alone (ADR 0065)."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    commands = json.loads(builds[0].read_text())
    ours = [
        c
        for c in commands
        if c["file"].startswith(str(ENGINE / "src"))
        or c["file"].startswith(str(ENGINE / "extension"))
    ]
    files = {Path(c["file"]).name for c in ours}
    assert {
        "error.cpp",
        "parse_version.cpp",
        "version.cpp",
        "buffer.cpp",
        "module.cpp",
        "connection.cpp",
        "sqlearn_extension.cpp",
    } <= files
    raw = str(ENGINE / "src" / "raw")
    warnings = _sq_warnings()
    for command in ours:
        flags = command["command"].split()
        for flag in (*warnings, "-ffp-contract=off"):
            assert flag in flags, (command["file"], flag)
        in_raw = command["file"].startswith(raw)
        assert ("-Wunsafe-buffer-usage" in flags) != in_raw, command["file"]
        assert "-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST" in flags, command[
            "file"
        ]


def test_the_wheel_compiles_our_sources_with_the_release_hardening() -> None:
    """The wheel's build gives our sources OpenSSF's release hardening: fortified
    libc calls, the stack protector, and on arm64 branch protection."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    wanted = ["-U_FORTIFY_SOURCE", "-D_FORTIFY_SOURCE=3", "-fstack-protector-strong"]
    if platform.machine() in {"arm64", "aarch64"}:
        wanted.append("-mbranch-protection=standard")
    for build in builds:
        commands = json.loads(build.read_text())
        ours = [c for c in commands if c["file"].startswith(str(ENGINE / "src"))]
        assert ours, build
        for command in ours:
            flags = command["command"].split()
            for flag in wanted:
                assert flag in flags, (build, command["file"], flag)
            fortify = flags.index("-D_FORTIFY_SOURCE=3")
            assert flags.index("-U_FORTIFY_SOURCE") < fortify, (build, command["file"])


TEST_ONLY = re.compile(
    r"-fsanitize\S*|-DSQ_CRASH_TEST_HOOKS\S*"
    r"|\S*third_party/(?:catch2|rapidcheck|nanobench)\S*"
)
"""What only a test build has: a sanitizer, the crash group's test hooks, and
the include paths of the test-only libraries (Catch2, RapidCheck, nanobench)."""


OURS = ("src", "extension", "tests", "fuzz", "bench")
"""The directories of engine/ that hold our sources."""

DEBUG_LEVEL = re.compile(r"-g(?:[0-3]|line-tables-only|line-directives-only)?")
"""A flag that sets the level of debug information (not -grecord-command-line,
which says what to record)."""


def _builds() -> list[tuple[Path, str, list[dict[str, Any]]]]:
    """Each build here with a compile database: its directory, its CMake build
    type and its commands on our sources."""
    found = []
    for database in sorted(
        [
            *(ENGINE / "build").glob("*/compile_commands.json"),
            *(REPO / "build").glob("*/compile_commands.json"),
        ]
    ):
        cache = database.parent / "CMakeCache.txt"
        if not cache.exists():
            continue
        match = re.search(r"^CMAKE_BUILD_TYPE:\w+=(.*)$", cache.read_text(), re.M)
        build_type = match.group(1) if match else ""
        ours = [
            c
            for c in json.loads(database.read_text())
            if any(c["file"].startswith(str(ENGINE / d) + "/") for d in OURS)
        ]
        if ours:
            found.append((database.parent, build_type, ours))
    if not found:
        pytest.skip("no build here yet: uv sync or just build-engine makes one")
    return found


def test_our_compile_lines_carry_one_optimisation_level() -> None:
    """Our sources get the flavour's optimisation and debug levels alone, not
    CMake's build-type defaults beside them: one -O and at most one debug
    level on each line."""
    for build, _, ours in _builds():
        for command in ours:
            flags = command["command"].split()
            levels = [f for f in flags if f.startswith("-O")]
            debug = [f for f in flags if DEBUG_LEVEL.fullmatch(f)]
            assert len(levels) == 1, (build.name, command["file"], levels)
            assert len(debug) <= 1, (build.name, command["file"], debug)


def test_assert_is_off_exactly_where_the_build_type_turns_it_off() -> None:
    """-DNDEBUG reaches our sources where CMake's build type gives it to
    DuckDB's (every type but Debug), so the inline functions of DuckDB's
    headers compile alike in our objects and in DuckDB's."""
    for build, build_type, ours in _builds():
        wanted = build_type not in ("", "Debug")
        for command in ours:
            has = "-DNDEBUG" in command["command"].split()
            assert has == wanted, (build.name, build_type, command["file"])


def test_the_wheel_build_has_nothing_of_the_test_builds() -> None:
    """No compile command of the wheel's build sanitizes, turns on the crash
    group's test hooks, or reads a test-only library's headers: those never
    ship."""
    builds = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not builds:
        pytest.skip("no wheel build here yet: uv sync makes one")
    for build in builds:
        commands = json.loads(build.read_text())
        assert commands, build
        found = [
            (c["file"], m.group(0))
            for c in commands
            for m in TEST_ONLY.finditer(c["command"])
        ]
        assert found == [], (build, found[:5])


def test_the_optimised_flavours_alone_carry_the_release_hardening() -> None:
    """release and profile take the hardening; _FORTIFY_SOURCE needs optimisation,
    so the dev, debug and sanitizer flavours go without it."""
    text = (ENGINE / "cmake" / "hardening.cmake").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    branches = re.split(r'\n(?:else)?if\(SQ_FLAVOR STREQUAL "', code)
    flavours = {b.split('"', 1)[0]: b for b in branches[1:]}
    assert set(flavours) >= {
        "dev",
        "debug",
        "release",
        "profile",
        "tsan",
        "lsan",
        "tysan",
    }
    for name, body in flavours.items():
        assert ("${SQ_RELEASE_HARDENING}" in body) == (name in {"release", "profile"})


def _stack_clash_probe(tmp_path: Path, compiler: str) -> tuple[bool, str]:
    """Configure a scratch project reading hardening.cmake with `compiler`;
    return the stack clash probe's result and the release hardening."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.29)\n"
        "project(probe LANGUAGES CXX)\n"
        f'include("{(ENGINE / "cmake" / "hardening.cmake").as_posix()}")\n'
        'message(STATUS "PROBE=${SQ_TAKES_STACK_CLASH_PROTECTION}")\n'
        'message(STATUS "HARDENING=${SQ_RELEASE_HARDENING}")\n'
    )
    done = subprocess.run(
        [
            "cmake",
            "-S",
            str(project),
            "-B",
            str(tmp_path / "build"),
            "-G",
            "Ninja",
            f"-DCMAKE_CXX_COMPILER={compiler}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = done.stdout.splitlines()
    probe = next(x for x in lines if "-- PROBE=" in x).split("=", 1)[1]
    hardening = next(x for x in lines if "-- HARDENING=" in x).split("=", 1)[1]
    return probe in {"1", "ON", "TRUE"}, hardening


@pytest.mark.skipif(
    shutil.which("cmake") is None or shutil.which("ninja") is None,
    reason="cmake and ninja: just doctor",
)
@pytest.mark.parametrize(
    ("compiler", "takes"),
    [
        # Apple clang ignores it on arm64 macOS, and says so as a warning.
        ("c++", False),
        # GCC takes it: the probe must not ask GCC for a Clang-only option.
        ("g++-16", True),
    ],
)
def test_the_stack_clash_probe_asks_each_compiler_its_own_way(
    tmp_path: Path, compiler: str, takes: bool
) -> None:
    """The probe passes Clang's -Werror for an unused argument to Clang alone;
    GCC refuses that option, which made the probe false on GCC every time."""
    if shutil.which(compiler) is None:
        pytest.skip(f"no {compiler} here")
    if compiler == "c++" and not (
        sys.platform == "darwin" and platform.machine() == "arm64"
    ):
        pytest.skip("Apple clang on arm64 macOS")
    found, hardening = _stack_clash_probe(tmp_path, shutil.which(compiler) or "")
    assert found == takes
    assert ("-fstack-clash-protection" in hardening) == takes


BINDINGS_DEFINES = re.compile(
    r"-D(?:DUCKDB_STATIC_BUILD|NB_DOMAIN=\S+|Py_LIMITED_API=\S+)"
)
"""The definitions the bindings' headers are compiled with: DuckDB's static
build, nanobind's domain and Python's stable ABI."""


def _bindings_units(database: Path) -> dict[str, list[str]]:
    """Each headers-alone unit of the bindings in `database`, with its
    arguments."""
    if not database.exists():
        return {}
    return {
        Path(c["file"]).name: shlex.split(c["command"])
        for c in json.loads(database.read_text())
        if "/headers_alone/bindings/" in c["file"]
    }


def _what_a_unit_sees(arguments: list[str]) -> tuple[set[str], set[str]]:
    """A unit's system include directories and its bindings' definitions."""
    systems = {arguments[i + 1] for i, a in enumerate(arguments) if a == "-isystem"}
    return systems, {a for a in arguments if BINDINGS_DEFINES.fullmatch(a)}


def test_headers_alone_builds_the_bindings_headers() -> None:
    """llvm-dev, the build `just headers-alone` uses, has a unit for each header
    under engine/src/bindings/, so they build alone with Homebrew LLVM too, not
    only in the wheel's build with Apple clang."""
    database = ENGINE / "build" / "llvm-dev" / "compile_commands.json"
    if not database.exists():
        pytest.skip("no llvm-dev build here yet: just headers-alone makes one")
    headers = sorted(p.stem for p in (ENGINE / "src" / "bindings").glob("*.hpp"))
    assert headers
    units = sorted(Path(name).stem for name in _bindings_units(database))
    assert units == headers


def test_the_bindings_headers_alone_see_what_the_wheel_gives_them() -> None:
    """Each bindings unit of llvm-dev sees the system include directories and
    the definitions the wheel's build gives the same unit, so the two cannot
    drift apart."""
    llvm = _bindings_units(ENGINE / "build" / "llvm-dev" / "compile_commands.json")
    wheels = sorted((REPO / "build").glob("*/compile_commands.json"))
    if not llvm or not wheels:
        pytest.skip("needs an llvm-dev build and a wheel build here")
    wheel = _bindings_units(wheels[0])
    assert wheel
    for name, arguments in wheel.items():
        assert name in llvm, name
        assert _what_a_unit_sees(llvm[name]) == _what_a_unit_sees(arguments), name


def test_clangd_reads_the_llvm_dev_compile_database() -> None:
    """The root .clangd points clangd at llvm-dev's compile_commands.json, the
    build of Homebrew LLVM, whose clangd it is (spec §3.8)."""
    assert "llvm-dev" in _configure_presets()
    text = (REPO / ".clangd").read_text()
    found = re.search(r"^\s*CompilationDatabase:\s*(\S+)\s*$", text, re.MULTILINE)
    assert found is not None
    assert found.group(1) == "engine/build/llvm-dev"


def test_link_options_go_only_on_targets_that_link(tmp_path: Path) -> None:
    """sq_target_flavor gives link options to a program, a shared library and a
    module, and to no static or object library: a PRIVATE link option does
    nothing on those (the guard is by type, so an interface library gets none)."""
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("no cmake here")
    (tmp_path / "CMakeLists.txt").write_text(
        f"""cmake_minimum_required(VERSION 3.25)
project(probe CXX)
set(SQ_FLAVOR dev CACHE STRING "")
include({(ENGINE / "cmake" / "hardening.cmake").as_posix()})
file(WRITE ${{CMAKE_BINARY_DIR}}/main.cpp "int main() {{ return 0; }}")
file(WRITE ${{CMAKE_BINARY_DIR}}/lib.cpp "int f() {{ return 0; }}")
add_executable(t_exe ${{CMAKE_BINARY_DIR}}/main.cpp)
add_library(t_shared SHARED ${{CMAKE_BINARY_DIR}}/lib.cpp)
add_library(t_module MODULE ${{CMAKE_BINARY_DIR}}/lib.cpp)
add_library(t_static STATIC ${{CMAKE_BINARY_DIR}}/lib.cpp)
add_library(t_object OBJECT ${{CMAKE_BINARY_DIR}}/lib.cpp)
foreach(t t_exe t_shared t_module t_static t_object)
  sq_target_flavor(${{t}})
  get_target_property(opts ${{t}} LINK_OPTIONS)
  get_target_property(iopts ${{t}} INTERFACE_LINK_OPTIONS)
  message(STATUS "PROBE ${{t}} link=[${{opts}}] interface=[${{iopts}}]")
endforeach()
"""
    )
    done = subprocess.run(
        [cmake, "-S", str(tmp_path), "-B", str(tmp_path / "b")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    probes = dict(
        re.findall(r"PROBE (\w+) (link=\[.*?\] interface=\[.*?\])", done.stdout)
    )
    assert set(probes) == {
        "t_exe",
        "t_shared",
        "t_module",
        "t_static",
        "t_object",
    }
    for linked in ("t_exe", "t_shared", "t_module"):
        assert "-fsanitize=address" in probes[linked], probes[linked]
    for unlinked in ("t_static", "t_object"):
        assert "-fsanitize" not in probes[unlinked], probes[unlinked]

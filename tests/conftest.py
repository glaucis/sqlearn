"""A scratch engine for the tests of the C++ checks (``validation._ctest``).

A minimal CMake project of two stand-in groups, ``core`` and ``raw``, made by
the engine's ``sq_add_group`` with its options stubbed, each tested by a
program that logs its run, and one must-not-compile test: a real ``cmake``
and ``ninja`` build it, in a scratch git repository, fast enough for the
parallel pass. The real engine is not built.

``core`` has two sources, ``core/used.cpp``, which ``raw`` calls, and
``core/alone.cpp``, which only ``core``'s program calls; ``raw`` depends on
``core``. ``core`` loads a shared library of the build, ``extra``; ``raw``
reads a data file, ``data/raw.txt`` (``sq_test_data``); the must-not-compile
test's
source includes a header of its own directory and one through ``-isystem``.
The compiler is a wrapper script around the real one, so a test can update it
in place. A program fails while the file ``<log>.fail`` exists.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

PRESETS = """{
  "version": 6,
  "configurePresets": [
    {"name": "dev", "generator": "Ninja",
     "binaryDir": "${sourceDir}/build/${presetName}",
     "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug",
                        "CMAKE_CXX_COMPILER": "@COMPILER@"}}
  ],
  "buildPresets": [{"name": "dev", "configurePreset": "dev"}]
}
"""

LISTS = f"""cmake_minimum_required(VERSION 3.29)
project(scratch LANGUAGES CXX)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
include("{REPO.as_posix()}/engine/cmake/groups.cmake")
set(SQ_ENGINE_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}")
set(SQ_CXX_STANDARD 17)
set(SQ_BUILD_TESTS ON)
function(sq_target_warnings target)
endfunction()
function(sq_target_flavor target)
endfunction()
function(sq_test_environment test)
endfunction()
add_library(Catch2::Catch2WithMain INTERFACE IMPORTED)
add_library(sq_rapidcheck_catch INTERFACE)
enable_testing()
add_library(extra SHARED src/extra.cpp)
sq_add_group(core SOURCES src/core/used.cpp src/core/alone.cpp TESTS src/core.cpp)
sq_add_group(
  raw SOURCES src/raw/lib.cpp DEPENDS core TESTS src/raw.cpp DATA data/raw.txt
)
target_link_libraries(test_core PRIVATE extra)
add_library(bad OBJECT EXCLUDE_FROM_ALL src/bad.cpp)
target_include_directories(bad SYSTEM PRIVATE include)
add_test(NAME must_not_compile.bad
         COMMAND "${{CMAKE_COMMAND}}" --build "${{CMAKE_BINARY_DIR}}" --target bad)
set_tests_properties(must_not_compile.bad PROPERTIES WILL_FAIL TRUE
                     LABELS must_not_compile TIMEOUT 300)
"""

PROGRAM = """#include <cstdio>
#include <cstdlib>
#include <string>
{declare}
int main() {{
    const char *path = std::getenv("RUNS");
    if (path == nullptr) {{
        return 2;
    }}
    if (std::FILE *log = std::fopen(path, "a")) {{
        std::fputs("{text}\\n", log);
        std::fclose(log);
    }}
    if (std::FILE *fail = std::fopen((std::string(path) + ".fail").c_str(), "r")) {{
        std::fclose(fail);
        return 1;
    }}
    return {code}{call};
}}
"""

COMPILER = """#!/bin/sh
exec {real} "$@"
"""


@dataclass(frozen=True)
class EngineScratch:
    """A scratch repository holding a two-group ``engine/``."""

    root: Path
    log: Path
    compiler: Path

    def program(self, group, text=None, code=0):
        """Write `group`'s program: it logs `text` (its name) and exits `code`."""
        source = self.root / "engine" / "src" / f"{group}.cpp"
        calls = ["extra", "core_alone"] if group == "core" else ["raw_lib"]
        source.write_text(
            PROGRAM.format(
                text=text or group,
                code=code,
                declare="".join(f"int {name}();\n" for name in calls),
                call="".join(f" + {name}()" for name in calls),
            )
        )

    def runs(self):
        """Return and forget the programs' runs since the last look."""
        if not self.log.exists():
            return []
        lines = self.log.read_text().splitlines()
        self.log.unlink()
        return lines


@pytest.fixture
def engine_scratch(tmp_path, monkeypatch):
    """A committed scratch repository with a two-group engine; its log."""
    real = shutil.which("c++")
    if shutil.which("cmake") is None or shutil.which("ninja") is None or not real:
        pytest.skip("cmake, ninja and c++ are needed: just doctor")
    compiler = tmp_path / "bin" / "c++"
    compiler.parent.mkdir()
    compiler.write_text(COMPILER.format(real=real))
    compiler.chmod(0o755)
    root = tmp_path / "repo"
    engine = root / "engine"
    src = engine / "src"
    src.mkdir(parents=True)
    (engine / "include").mkdir()
    (engine / "data").mkdir()
    (root / ".gitignore").write_text("/engine/build/\n")
    presets = PRESETS.replace("@COMPILER@", compiler.as_posix())
    (engine / "CMakePresets.json").write_text(presets)
    (engine / "CMakeLists.txt").write_text(LISTS)
    (src / "extra.cpp").write_text(
        '__attribute__((visibility("default"))) int extra() { return 0; }\n'
    )
    (src / "core").mkdir()
    (src / "core" / "used.cpp").write_text("int core_used() { return 0; }\n")
    (src / "core" / "alone.cpp").write_text("int core_alone() { return 0; }\n")
    (src / "raw").mkdir()
    (src / "raw" / "lib.cpp").write_text(
        "int core_used();\nint raw_lib() { return core_used(); }\n"
    )
    (src / "common.hpp").write_text("#define SQ_FINE 0\n")
    (engine / "include" / "sys_common.hpp").write_text("#define SQ_SYS 0\n")
    (src / "bad.cpp").write_text(
        '#include "common.hpp"\n#include <sys_common.hpp>\n'
        "static_assert(SQ_FINE + SQ_SYS);\n"
    )
    (engine / "data" / "raw.txt").write_text("data\n")
    scratch = EngineScratch(root=root, log=tmp_path / "runs.log", compiler=compiler)
    scratch.program("core")
    scratch.program("raw")
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("RUNS", str(scratch.log))
    for args in (
        ["init", "--quiet"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return scratch

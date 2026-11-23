"""A scratch engine for the tests of the C++ checks (``validation._ctest``).

A minimal CMake project of two stand-in groups, ``core`` and ``raw``, each a
program that logs its run, and one must-not-compile test: a real ``cmake``
and ``ninja`` build it, in a scratch git repository, fast enough for the
parallel pass. The real engine is not built.
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
     "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug"}}
  ],
  "buildPresets": [{"name": "dev", "configurePreset": "dev"}]
}
"""

LISTS = f"""cmake_minimum_required(VERSION 3.29)
project(scratch LANGUAGES CXX)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
include("{REPO.as_posix()}/engine/cmake/groups.cmake")
enable_testing()
foreach(group IN ITEMS core raw)
  add_executable(test_${{group}} src/${{group}}.cpp)
  sq_stable_link(test_${{group}})
  add_test(NAME test_${{group}} COMMAND test_${{group}})
  set_tests_properties(test_${{group}} PROPERTIES LABELS ${{group}})
endforeach()
add_library(bad OBJECT EXCLUDE_FROM_ALL src/bad.cpp)
target_include_directories(bad PRIVATE src)
add_test(NAME must_not_compile.bad
         COMMAND "${{CMAKE_COMMAND}}" --build "${{CMAKE_BINARY_DIR}}" --target bad)
set_tests_properties(must_not_compile.bad PROPERTIES WILL_FAIL TRUE
                     LABELS must_not_compile)
"""

PROGRAM = """#include <cstdio>
#include <cstdlib>
int main() {{
    if (const char *path = std::getenv("RUNS")) {{
        if (std::FILE *log = std::fopen(path, "a")) {{
            std::fputs("{text}\\n", log);
            std::fclose(log);
        }}
    }}
    return {code};
}}
"""


@dataclass(frozen=True)
class EngineScratch:
    """A scratch repository holding a two-group ``engine/``."""

    root: Path
    log: Path

    def program(self, group, text=None, code=0):
        """Write `group`'s program: it logs `text` (its name) and exits `code`."""
        source = self.root / "engine" / "src" / f"{group}.cpp"
        source.write_text(PROGRAM.format(text=text or group, code=code))

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
    if shutil.which("cmake") is None or shutil.which("ninja") is None:
        pytest.skip("cmake and ninja are needed: just doctor")
    root = tmp_path / "repo"
    src = root / "engine" / "src"
    src.mkdir(parents=True)
    (root / ".gitignore").write_text("/engine/build/\n")
    (root / "engine" / "CMakePresets.json").write_text(PRESETS)
    (root / "engine" / "CMakeLists.txt").write_text(LISTS)
    (src / "common.hpp").write_text("#define SQ_FINE 0\n")
    (src / "bad.cpp").write_text('#include "common.hpp"\nstatic_assert(SQ_FINE);\n')
    scratch = EngineScratch(root=root, log=tmp_path / "runs.log")
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

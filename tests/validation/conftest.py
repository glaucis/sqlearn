"""Shared fixtures of the validation tests: a scratch repository of two C++ groups.

``a`` and ``b`` (built on it), with a hand-written manifest and
``compile_commands.json`` naming real files, the real compiler and the real
clang. ``ninja`` is a script printing the build's ``link.txt``, the module's
link command.
"""

import json
import os
import shlex
import shutil
import subprocess

import pytest

from validation import _groups

NINJA = """#!/bin/sh
# Called as: ninja -C <build> -t commands _duckdb, -t deps <object>, or
# -n <target> (a dry run: work to do when <build>/stale exists).
if [ "$3" = -n ]; then
    if [ -f "$2/stale" ]; then
        echo "[1/1] Linking CXX executable bench/$4"
    else
        echo "ninja: no work to do."
    fi
    exit 0
fi
if [ "$4" = deps ]; then
    [ -f "$2/deps.txt" ] || exit 1
    cat "$2/deps.txt"
    exit 0
fi
printf 'echo first\\n'
cat "$2/link.txt"
"""

PYPROJECT = """[project]
name = "scratch"

[build-system]
requires = ["scikit-build-core==1.1.2"]

[tool.scikit-build]
cmake.source-dir = "engine"
"""


class Scratch:
    """A scratch repository with groups ``a`` and ``b``, and its build."""

    def __init__(self, root, compiler):
        self.root = root
        self.build = root / _groups.WHEEL_BUILD
        self.src = root / "engine" / "src"
        self.compiler = compiler
        self.flags = {"a/one.cpp": [], "b/two.cpp": [], "bindings/module.cpp": []}

    def write(self, relative, text):
        """Write `text` to `relative`, a path under ``engine/src``."""
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def entries(self):
        """Write ``compile_commands.json`` for the sources of ``self.flags``.

        A source is under ``engine/src``, or absolute (a generated one).
        """
        entries = []
        for source, extra in self.flags.items():
            path = self.src / source
            argv = [
                self.compiler,
                "-std=c++23",
                f"-I{self.src}",
                f"-I{self.root / 'engine' / 'include'}",
                *extra,
                "-o",
                f"CMakeFiles/sq.dir/{path.name}.o",
                "-c",
                str(path),
            ]
            entries.append(
                {
                    "directory": str(self.build),
                    "command": shlex.join(argv),
                    "file": str(path),
                    "output": str(self.build / f"CMakeFiles/sq.dir/{path.name}.o"),
                }
            )
        (self.build / "compile_commands.json").write_text(json.dumps(entries))

    def link(self, text):
        """Write the module's link command that ``ninja -t commands`` prints."""
        (self.build / "link.txt").write_text(text + "\n")

    def prints(self):
        """Return the scratch repository's fingerprints."""
        return _groups.fingerprints(self.root, self.build)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """The scratch repository, ``ninja`` faked on ``PATH``."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("c++ is needed: just doctor")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ninja = bin_dir / "ninja"
    ninja.write_text(NINJA)
    ninja.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    made = Scratch(root, compiler)
    made.build.mkdir(parents=True)
    made.write("a/one.hpp", "#pragma once\nint one();\n")
    made.write("a/one.cpp", '#include "a/one.hpp"\n// x\nint one() { return 1; }\n')
    made.write("b/two.cpp", '#include "a/one.hpp"\nint two() { return one(); }\n')
    made.write("bindings/module.cpp", "int module() { return 0; }\n")
    (root / "engine" / "extension").mkdir()
    (root / "engine" / "extension" / "CMakeLists.txt").write_text("# none\n")
    manifest = {
        "groups": [
            {
                "name": "a",
                "dir": "engine/src/a",
                "depends": [],
                "python_tests": [],
                "validation": [],
                "bench": [],
            },
            {
                "name": "b",
                "dir": "engine/src/b",
                "depends": ["a"],
                "python_tests": ["tests/test_b.py"],
                "validation": [],
                "bench": [],
            },
        ],
        "shared": ["engine/src/bindings", "engine/extension"],
    }
    (made.build / "sq_groups.json").write_text(json.dumps(manifest))
    made.entries()
    made.link(f"{compiler} -bundle -o _duckdb.abi3.so one.o two.o")
    return made

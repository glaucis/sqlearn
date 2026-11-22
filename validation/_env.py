"""Print the digest of the module-level code `just test-env` adds to its hash.

testmon traces a test's lines from the test's start, so code that runs at
import (constants, imports, class bases, decorators, signatures, `__all__`)
is seen by no test. This digest stands in for it: every `.py` file under the
directories named on the command line, its function and method bodies
emptied, so an edit at module level reruns every test and an edit inside a
function leaves testmon's selection to testmon. The sorted paths are hashed
too, so a new or deleted module counts, and every file's path under `src/`,
since a test may glob the package for any kind of file. A file that does not
parse counts by its bytes. Run as a script from the project's root, it
imports nothing but the standard library.
"""

import ast
import hashlib
import os
import sys
from pathlib import Path

# The body every function and method is given; any fixed statement would do.
PLACEHOLDER = [ast.Expr(ast.Constant(Ellipsis))]
SKIPPED_DIRS = {"__pycache__", "node_modules"}
# Every file under it counts by its path, not only Python.
EVERY_PATH = "src"


class _EmptyBodies(ast.NodeTransformer):
    """Replace each function's body, keeping its decorators and signature."""

    def visit_FunctionDef(self, node):
        """Empty a function's body."""
        node.body = PLACEHOLDER
        return node

    def visit_AsyncFunctionDef(self, node):
        """Empty a coroutine's body."""
        node.body = PLACEHOLDER
        return node


def module_level(source):
    """Return the bytes standing for a module's import-time code."""
    try:
        tree = _EmptyBodies().visit(ast.parse(source))
        return b"ast\0" + ast.dump(tree).encode()
    except Exception:  # noqa: BLE001 (a file that does not parse counts by its bytes)
        return b"raw\0" + source


def files(directory):
    """Yield every file under directory, hidden and cache folders left out."""
    for parent, dirs, names in os.walk(directory):
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and d not in SKIPPED_DIRS
        )
        for name in sorted(names):
            yield Path(parent, name).as_posix()


def digest(directories):
    """Return the SHA-256 of the paths and module-level code under directories."""
    found = sorted({f for d in directories for f in files(d)})
    sha = hashlib.sha256()
    for path in found:
        is_python = path.endswith(".py")
        if not is_python and path.split("/", 1)[0] != EVERY_PATH:
            continue
        sha.update(path.encode() + b"\0")
        if is_python:
            try:
                source = Path(path).read_bytes()
            except OSError as error:
                source = f"unreadable: {error.strerror}".encode()
            sha.update(module_level(source) + b"\0")
    return sha.hexdigest()


if __name__ == "__main__":
    print(digest(sys.argv[1:]))  # noqa: T201

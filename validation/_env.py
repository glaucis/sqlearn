"""Print the digest of the module-level code `just test-env` adds to its hash.

testmon traces a test's lines from the test's start, so code that runs at
import (constants, imports, class bases, decorators, signatures, `__all__`)
is seen by no test. This digest stands in for it: every `.py` file under the
directories named on the command line, its function and method bodies
emptied, so an edit at module level reruns every test and an edit inside a
function leaves testmon's selection to testmon. A body that may run at import
is kept instead: a dunder Python calls at construction or class creation, and
every function or method of a class whose name a statement run at module or
class level calls or applies as a decorator, in any of the files (a match by
name, which over-selects on purpose). The sorted paths are hashed too, so a
new or deleted module counts, and every file's path under `src/`, since a
test may glob the package for any kind of file. A file that does not parse
counts by its bytes. Run as a script from the project's root, it imports
nothing but the standard library.
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
# The methods Python runs when an instance or a class is made: a module-level
# instance or class runs them at import.
AT_CONSTRUCTION = frozenset(
    {
        "__init__",
        "__new__",
        "__post_init__",
        "__init_subclass__",
        "__set_name__",
        "__class_getitem__",
    }
)


def _called_name(node):
    """Return the name a call or decorator refers to, or None."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _ImportTimeCalls(ast.NodeVisitor):
    """Collect the names called or applied as decorators outside function bodies."""

    def __init__(self, names):
        self.names = names

    def _decorators(self, node):
        for decorator in node.decorator_list:
            self.names.add(_called_name(decorator))
            self.visit(decorator)

    def visit_FunctionDef(self, node):
        """Visit what runs at definition, not the body, which runs later."""
        self._decorators(node)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_AsyncFunctionDef(self, node):
        """Visit what runs at a coroutine's definition."""
        self.visit_FunctionDef(node)

    def visit_Lambda(self, node):
        """Visit a lambda's defaults, not its body, which runs when called."""
        self.visit(node.args)

    def visit_ClassDef(self, node):
        """Visit a class's decorators, bases and body, all run at definition."""
        self._decorators(node)
        for part in (*node.bases, *node.keywords, *node.body):
            self.visit(part)

    def visit_Call(self, node):
        """Record a call's name and visit its parts."""
        self.names.add(_called_name(node))
        self.generic_visit(node)


class _EmptyBodies(ast.NodeTransformer):
    """Replace each function's body that runs later, keeping its signature."""

    def __init__(self, at_import):
        self.at_import = at_import
        self.classes = []

    def visit_ClassDef(self, node):
        """Visit a class's methods, knowing their class."""
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()
        return node

    def visit_FunctionDef(self, node):
        """Empty a function's body unless it may run at import."""
        runs_at_import = (
            node.name in AT_CONSTRUCTION
            or node.name in self.at_import
            or (self.classes and self.classes[-1] in self.at_import)
        )
        if not runs_at_import:
            node.body = PLACEHOLDER
        return node

    def visit_AsyncFunctionDef(self, node):
        """Empty a coroutine's body unless it may run at import."""
        return self.visit_FunctionDef(node)


def module_level(source, at_import=frozenset()):
    """Return the bytes standing for a module's import-time code."""
    try:
        tree = _EmptyBodies(at_import).visit(ast.parse(source))
        return b"ast\0" + ast.dump(tree).encode()
    except Exception:  # noqa: BLE001 (a file that does not parse counts by its bytes)
        return b"raw\0" + source


def import_time_names(sources):
    """Return every name called or used as a decorator at module or class level."""
    names = set()
    for source in sources:
        try:
            tree = ast.parse(source)
        except Exception:  # noqa: BLE001 (module_level counts it by its bytes)
            continue
        _ImportTimeCalls(names).visit(tree)
    names.discard(None)
    return frozenset(names)


def files(directory):
    """Yield every file under directory, hidden and cache folders left out."""
    for parent, dirs, names in os.walk(directory):
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and d not in SKIPPED_DIRS
        )
        for name in sorted(names):
            yield Path(parent, name).as_posix()


def _read(path):
    """Return a file's bytes, or bytes naming why it could not be read."""
    try:
        return Path(path).read_bytes()
    except OSError as error:
        return f"unreadable: {error.strerror}".encode()


def digest(directories):
    """Return the SHA-256 of the paths and module-level code under directories."""
    found = sorted({f for d in directories for f in files(d)})
    found = [f for f in found if f.endswith(".py") or f.split("/", 1)[0] == EVERY_PATH]
    sources = {f: _read(f) for f in found if f.endswith(".py")}
    at_import = import_time_names(sources.values())
    sha = hashlib.sha256()
    for path in found:
        sha.update(path.encode() + b"\0")
        if path in sources:
            sha.update(module_level(sources[path], at_import) + b"\0")
    return sha.hexdigest()


if __name__ == "__main__":
    print(digest(sys.argv[1:]))  # noqa: T201

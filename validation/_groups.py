"""The module's fingerprints: one per C++ group, and a shared part.

The wheel's binary holds every C++ group, so what a Python test or runner
reads of it is the groups it uses and what every group runs with. A
**group's fingerprint** is the SHA-256 of, sorted:

- the compile entry of each of its sources (``compile_commands.json`` of the
  wheel's build), its argv with the checkout's place taken out, so a flag
  that changes reruns it and a CMake comment does not;
- ``stripped()`` of every C++ file under its directory, of every file of
  any suffix under it that any compile entry reads, and of every file its
  own entries read in the tree outside every group's directory and every
  submodule (a header of ``engine/include``, a generated one of the build
  directory such as ``build_identity.hpp``): its code without comments but
  with its line numbers, since a line reaches users (a ``PreconditionError``
  names its file and line), so a comment that adds a line reruns it and one
  edited within its lines does not;
- the fingerprints of the groups it depends on: those the manifest names,
  and any whose file its sources read. A file under another group's
  directory counts for that group, and reaches this one through it.

The **shared part** is the SHA-256 of:

- every compile entry of no group, its argv normalised: DuckDB's,
  cpptrace's, nanobind's, the bindings', the extension's, so every compile
  flag that is not a group's counts (spec §5.1);
- the text of each generated source and header of the build directory (a
  unity file, say), its places taken out;
- ``stripped()`` of every C++ file under the shared directories (the
  bindings, the extension) and of every file their entries read in the tree
  outside the groups' directories and the submodules;
- the fingerprints of the closure of every group whose file a shared entry
  reads: the bindings read ``core`` and ``crash`` and run
  ``crash::install`` when the module loads, and start-up code is shared
  (spec §5.2), so such a group's change reruns everything;
- the submodules' pins under ``engine/``, which stand for their files;
- ``pyproject.toml``'s ``[build-system]`` and ``[tool.scikit-build]``
  tables, which pin uv's build environment;
- the compiler as it is now (``_ctest.compiler``);
- the module's link command.

CMake files are never read: what they say reaches the fingerprint only
through what they make the build do.

Whatever cannot be read (no manifest, no ``compile_commands.json``, no link
command, a listed file missing, a source no compile entry builds, no clang)
raises ``Unreadable``, whose message is printed as the reason everything
reruns.
"""

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from validation import _checks, _ctest

WHEEL_BUILD = Path("build") / sys.implementation.cache_tag
"""The wheel's build directory, relative to the repository's root: this
Python's, as pyproject's ``build-dir = "build/{cache_tag}"`` names it."""

AUDIT_ENV = "SQLEARN_AUDIT_COVERAGE"
"""The variable that selects the coverage wheel's override of ``pyproject.toml``
(``just audit-groups``): an override taken only under it is no setting of the
normal wheel, so ``_build_tables`` leaves it out."""

MANIFEST = "sq_groups.json"
"""The manifest CMake writes in a build directory: the groups and their claims."""

MODULE = "_duckdb"
"""The Ninja target of the module, whose link command is part of the shared part."""

LLVM_CLANG = Path("/opt/homebrew/opt/llvm/bin/clang")
"""Homebrew LLVM's clang, preferred to strip comments (keg-only, off PATH)."""

CPP_SUFFIXES = frozenset(
    {".c", ".cc", ".cpp", ".cxx", ".mm", ".h", ".hh", ".hpp", ".hxx", ".inc", ".ipp"}
)
"""The suffixes of the C++ files under a directory, sources and headers."""

SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx", ".mm"})
"""The suffixes of the files a compile entry must list."""

_BUILD_ENVIRONMENT = re.compile(r"[^\s:=@]*/builds-v0/\.tmp[^/\s]+")
"""uv's isolated build environment, at a new random path each build.

What it holds is pinned by ``[build-system]``, which the shared part hashes.
"""

_TOKEN = (
    r"^(\w+) +'(.*?)'[\t ]+(?:\[.*?\][\t ]*)*"
    r"Loc=<{name}:(\d+):\d+>(?=[\t ]*(?:\[|$))"
)
"""One token of clang's ``-dump-raw-tokens``: its kind, its text and its line.

Homebrew LLVM prints the flags after the location and escapes a newline in
a token's text; Apple's clang prints them before it, the newline as it is.
The location names the file lexed, ``{name}``, so a token's text holding
something like a location is read whole.
"""

_SPACE = re.compile(r"(?:\s|\\[ntrvf])*")
"""The text of a whitespace token, escaped or not."""

_GAP = re.compile(r"(?:\s+|\[UnClean='.*?'\]|\[\w+\])*", re.DOTALL)
"""What may lie between two tokens of the dump: the flags after a location.

``UnClean`` holds a token's spelling before a backslash-newline is removed.
"""


_SCM_VERSION = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)*(?:\.post\d+)?"
    r"(?:\.dev\d+(?:\+[A-Za-z0-9.]+)?|\+(?:g[0-9a-f]{7,}(?:\.d\d{8})?|d\d{8}))"
)
"""A version setuptools-scm gives between releases: ``0.1.dev5+g….d2026….``

sqlearn's reaches the build as ``build_identity.hpp``'s
``SQ_SQLEARN_VERSION``, the extension's ``-DEXT_VERSION_SQLEARN`` and
DuckDB's generated ``sqlearn_describe.c``; cut to its release part
(``release``) wherever the build directory or a compile entry holds it, so a
new commit alone changes no fingerprint, while a new release does.
"""


def _versionless(text: str) -> str:
    """Return `text` with each setuptools-scm version cut to its release."""
    return _SCM_VERSION.sub(lambda m: release(m[0]), text)


def release(version: str) -> str:
    """Return the release part of a version: ``0.1`` of ``0.1.dev5+g….d2026``.

    sqlearn's version comes from git and changes with every commit (its dev,
    local and date parts); its release part changes only with a release.

    Parameters
    ----------
    version : str
        A version as setuptools-scm gives it.

    Returns
    -------
    str
        The version up to ``.dev`` or ``+``.
    """
    return version.split(".dev")[0].split("+")[0]


class Unreadable(Exception):  # noqa: N818  (the name Tasks 3 to 7 use)
    """What the fingerprints need could not be read; its message says what."""


@dataclass(frozen=True)
class Group:
    """One C++ group of the manifest, and the Python it claims.

    Attributes
    ----------
    name : str
        The group's name, as ``sq_add_group`` has it.
    dir : str
        Its directory, relative to the root (``engine/src/<name>``).
    depends : tuple of str
        The groups it is built on.
    python_tests, validation, bench : tuple of str
        The Python tests, validation runners and benchmarks that use it.
    """

    name: str
    dir: str
    depends: tuple[str, ...]
    python_tests: tuple[str, ...]
    validation: tuple[str, ...]
    bench: tuple[str, ...]


@dataclass(frozen=True)
class Fingerprints:
    """The module's fingerprints.

    Attributes
    ----------
    shared : str
        The SHA-256 of what every group runs with.
    groups : dict of str to str
        Each group's name with its fingerprint.
    shared_groups : frozenset of str
        The groups in the shared part: the closure of those whose files the
        shared entries read (the bindings, the extension).
    manifest : dict of str to Group
        The manifest these were made from, so a caller loads it only once.
    """

    shared: str
    groups: dict[str, str]
    shared_groups: frozenset[str] = frozenset()
    manifest: dict[str, Group] = field(default_factory=dict)


def _strings(value: Any, what: str) -> tuple[str, ...]:
    """Return `value` as strings, raising ``Unreadable`` when it is not a list."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise Unreadable(f"{what} is not a list of strings")
    return tuple(value)


def load(build: Path) -> tuple[dict[str, Group], tuple[str, ...]]:
    """Return the groups of `build`'s manifest and its shared directories.

    Parameters
    ----------
    build : Path
        A configured build directory, holding ``MANIFEST``.

    Returns
    -------
    tuple
        Each group by its name, and the shared directories relative to the
        root.

    Raises
    ------
    Unreadable
        The manifest is missing, is not JSON, or does not hold groups whose
        ``depends`` name groups of it.
    """
    path = build / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unreadable(f"{path} could not be read: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise Unreadable(f"{path} holds no list of groups")
    groups: dict[str, Group] = {}
    for item in data["groups"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise Unreadable(f"{path}: a group with no name")
        name = item["name"]
        if not isinstance(item.get("dir"), str):
            raise Unreadable(f"{path}: group {name} has no directory")
        if name in groups:
            raise Unreadable(f"{path}: group {name} appears twice")
        groups[name] = Group(
            name=name,
            dir=item["dir"],
            **{
                key: _strings(item.get(key), f"{path}: group {name}'s {key}")
                for key in ("depends", "python_tests", "validation", "bench")
            },
        )
    for group in groups.values():
        unknown = sorted(set(group.depends) - set(groups))
        if unknown:
            raise Unreadable(
                f"{path}: group {group.name} depends on unknown {', '.join(unknown)}"
            )
    return groups, _strings(data.get("shared"), f"{path}'s shared directories")


def _clang() -> list[str]:
    """Return the argv of the clang that strips comments."""
    if LLVM_CLANG.is_file():
        return [str(LLVM_CLANG)]
    if sys.platform == "darwin" and shutil.which("xcrun"):
        return ["xcrun", "clang"]
    found = shutil.which("clang")
    if found is None:
        raise Unreadable("no clang to strip the C++ files' comments: just doctor")
    return [found]


def stripped(path: Path) -> str:
    """Return the C++ file `path` without its comments, its line numbers kept.

    Through clang's raw lexer (``-dump-raw-tokens``: no macro expanded, no
    include followed), one line per token: its line, its kind and its text.
    A comment counts as whitespace, and a run of whitespace as one space, so
    a comment edited within its lines leaves the result as it was, while one
    that adds or removes a line moves the tokens after it. Never given a
    CMake file.

    Parameters
    ----------
    path : Path
        A C++ source or header.

    Returns
    -------
    str
        The tokens, each as ``<line> <kind> <text>``, and ``space`` where
        whitespace or a comment separates two of them.

    Raises
    ------
    Unreadable
        The file is missing, or clang is absent or cannot lex it.
    """
    if not path.is_file():
        raise Unreadable(f"{path} is missing")
    argv = [*_clang(), "-x", "c++", "-fsyntax-only", "-Xclang", "-dump-raw-tokens"]
    try:
        done = subprocess.run(
            [*argv, path.name], cwd=path.parent, check=False, capture_output=True
        )
    except OSError as error:
        raise Unreadable(f"clang could not run on {path}: {error}") from error
    dump = done.stderr.decode("utf-8", errors="backslashreplace")
    if done.returncode != 0:
        raise Unreadable(f"clang could not lex {path}: {dump.strip()[:200]}")
    lines = []
    spaced = False
    end = 0
    tokens = re.compile(
        _TOKEN.format(name=re.escape(path.name)), re.MULTILINE | re.DOTALL
    )
    for token in tokens.finditer(dump):
        if not _GAP.fullmatch(dump, end, token.start()):
            raise Unreadable(f"clang's tokens of {path} could not be read")
        end = token.end()
        kind, text, line = token.groups()
        if kind == "comment" or (kind == "unknown" and _SPACE.fullmatch(text)):
            spaced = True
            continue
        if spaced and lines:
            lines.append("space")
        spaced = False
        lines.append(f"{line} {kind} {text}")
    if not _GAP.fullmatch(dump, end):
        raise Unreadable(f"clang's tokens of {path} could not be read")
    return "\n".join(lines)


def _normalised(argv: Sequence[str], root: Path) -> str:
    """Return `argv` joined, with the checkout's and uv's places taken out."""
    return _normal(shlex.join(argv), root)


def _files(directory: Path) -> list[Path]:
    """Return the C++ files under `directory`, which must exist."""
    if not directory.is_dir():
        raise Unreadable(f"{directory} is missing")
    return sorted(
        p.resolve()
        for p in directory.rglob("*")
        if p.is_file() and p.suffix in CPP_SUFFIXES
    )


def _link_command(build: Path) -> list[str]:
    """Return the module's link command: the last line Ninja prints for it."""
    listing = _ctest._output(["ninja", "-C", str(build), "-t", "commands", MODULE])
    lines = [line for line in (listing or "").splitlines() if line.strip()]
    if not lines:
        raise Unreadable(f"ninja gives no link command of {MODULE} in {build}")
    return shlex.split(lines[-1])


def _recorded(build: Path, entry: _ctest.Entry) -> list[Path] | None:
    """Return what Ninja recorded the compiler read for `entry`, None for none.

    ``ninja -t deps`` keeps the compiler's own depfile of the last build: it
    lists a source whose ``-M`` fails today because a header it needs is
    gone (nanobind's, in uv's build environment, which uv deletes after the
    build). Only a ``VALID`` record counts.
    """
    output = Path(str(entry.get("output", "")))
    if output.is_absolute():
        if not output.is_relative_to(build):
            return None
        output = output.relative_to(build)
    listing = _ctest._output(["ninja", "-C", str(build), "-t", "deps", str(output)])
    lines = (listing or "").splitlines()
    if not lines or not lines[0].rstrip().endswith("(VALID)"):
        return None
    return [build / line.strip() for line in lines[1:] if line.strip()]


def _build_tables(root: Path) -> str:
    """Return ``pyproject.toml``'s build tables as sorted JSON.

    An override taken only under ``AUDIT_ENV`` (the coverage wheel's) is left
    out, and the overrides list with it when none remains: the normal wheel
    never takes it, so its tables read as they would without it.
    """
    path = root / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unreadable(f"{path} could not be read: {error}") from error
    build = data.get("tool", {}).get("scikit-build")
    if isinstance(build, dict) and isinstance(build.get("overrides"), list):
        audit = {"env": {AUDIT_ENV: True}}
        kept = [
            o
            for o in build["overrides"]
            if not (isinstance(o, dict) and o.get("if") == audit)
        ]
        build = {k: v for k, v in build.items() if k != "overrides"}
        if kept:
            build["overrides"] = kept
    tables = {
        "build-system": data.get("build-system"),
        "tool.scikit-build": build,
    }
    return json.dumps(tables, sort_keys=True)


def _pins(root: Path) -> dict[str, str]:
    """Return each submodule under ``engine/`` with the commit the tree pins."""
    try:
        return _checks._gitlinks(["engine"], root)
    except (OSError, subprocess.CalledProcessError) as error:
        raise Unreadable(
            f"git could not list the pins under engine/: {error}"
        ) from error


def _normal(text: str, root: Path) -> str:
    """Return `text` with the checkout's and uv's places taken out.

    A setuptools-scm version is cut to its release (``_versionless``).
    """
    text = text.replace(str(root), "<root>")
    return _versionless(_BUILD_ENVIRONMENT.sub("<build-environment>", text))


def _bytes(path: Path, root: Path) -> str:
    """Return a generated file's text, its places taken out (``_normal``)."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Unreadable(f"{path} could not be read: {error}") from error
    return _normal(data.decode("utf-8", errors="surrogateescape"), root)


def _digest(parts: Iterable[str]) -> str:
    """Return the SHA-256 of `parts`, each ended by a NUL."""
    sha = hashlib.sha256()
    for part in parts:
        sha.update(part.encode("utf-8", errors="surrogateescape") + b"\0")
    return sha.hexdigest()


@dataclass(frozen=True)
class _Compiled:
    """One compile entry: its source, the group holding it, what it reads."""

    entry: _ctest.Entry
    source: Path
    owner: str | None
    reads: tuple[Path, ...]


class _Fingerprinter:
    """The fingerprints of one build, each file stripped once."""

    def __init__(
        self,
        root: Path,
        build: Path,
        groups: dict[str, Group],
        shared: Sequence[str],
    ) -> None:
        self.root = root
        self.build = build
        self.groups = groups
        self.shared_dirs = sorted(shared)
        self.dirs = {name: (root / g.dir).resolve() for name, g in groups.items()}
        self.pins = _pins(root)
        self.submodules = [(root / name).resolve() for name in self.pins]
        self.texts: dict[Path, str] = {}
        self.done: dict[str, str] = {}
        # Set by ``shared``: the groups in the shared part.
        self.shared_groups: frozenset[str] = frozenset()
        self.compiled = [self._compiled(e) for e in self._entries()]
        # A file under a group's directory counts for that group, whoever
        # reads it, so a file of any suffix its own sources never read is
        # still hashed, and its readers reach it through ``depends``.
        self.held: dict[str, set[Path]] = {name: set() for name in groups}
        for compiled in self.compiled:
            for found in compiled.reads:
                holder = self.owner(found)
                if holder is not None:
                    self.held[holder].add(found)

    def _entries(self) -> list[_ctest.Entry]:
        path = self.build / "compile_commands.json"
        if not path.is_file():
            raise Unreadable(f"{path} is missing")
        try:
            return _ctest._compile_entries(self.build)
        except ValueError as error:
            raise Unreadable(f"{path} could not be read: {error}") from error

    def _compiled(self, entry: _ctest.Entry) -> _Compiled:
        """Return `entry` with its source, and what it reads when ours.

        The compiler lists what an entry reads only for a source of the
        tree outside the build and the submodules: a submodule's files
        change with its pin, a generated source is hashed as it is.
        """
        here = Path(str(entry.get("directory", ".")))
        source = (here / str(entry.get("file", ""))).resolve()
        reads: tuple[Path, ...] = ()
        if self.counted(source) and not source.is_relative_to(self.build):
            listed = _ctest._read_by_compiler(entry) or _recorded(self.build, entry)
            if listed is None:
                raise Unreadable(f"the compiler cannot list what {source} reads")
            # What Ninja recorded may name uv's build environment, deleted
            # after the build and pinned by [build-system]. A file of the
            # tree removed since leaves the set it was in, so it still
            # changes a fingerprint.
            reads = tuple(sorted({p.resolve() for p in listed if p.is_file()}))
        return _Compiled(entry, source, self.owner(source), reads)

    def name(self, path: Path) -> str:
        """Return `path` relative to the root, or to the build as ``<build>``."""
        if path.is_relative_to(self.build):
            return f"<build>/{path.relative_to(self.build).as_posix()}"
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        return _normal(path.as_posix(), self.root)

    def text(self, path: Path) -> str:
        """Return ``stripped(path)``, read once a run.

        A file of the build directory is generated: its versions are cut to
        their release (``_versionless``).
        """
        if path not in self.texts:
            text = stripped(path)
            if path.is_relative_to(self.build):
                text = _versionless(text)
            self.texts[path] = text
        return self.texts[path]

    def owner(self, path: Path) -> str | None:
        """Return the group whose directory holds `path`, None for none."""
        for name, directory in self.dirs.items():
            if path.is_relative_to(directory):
                return name
        return None

    def counted(self, path: Path) -> bool:
        """Return whether `path` is hashed as read: in the tree, no submodule's.

        The build directory's files count (generated headers); a
        submodule's change with its pin; the system's with the compiler.
        """
        if path.is_relative_to(self.build):
            return True
        return path.is_relative_to(self.root) and not any(
            path.is_relative_to(s) for s in self.submodules
        )

    def entry(self, compiled: _Compiled) -> str:
        """Return the part of a compile entry: its source and its argv."""
        argv = _normalised(_ctest._arguments(compiled.entry), self.root)
        return f"entry\0{self.name(compiled.source)}\0{argv}"

    def group(self, name: str, seen: tuple[str, ...] = ()) -> str:
        """Return the fingerprint of the group `name`."""
        if name in self.done:
            return self.done[name]
        if name in seen:
            raise Unreadable(f"the groups depend on each other: {' -> '.join(seen)}")
        directory = self.dirs[name]
        files = set(_files(directory)) | self.held[name]
        depends = set(self.groups[name].depends)
        parts = []
        built = set()
        for compiled in self.compiled:
            if compiled.owner != name:
                continue
            built.add(compiled.source)
            parts.append(self.entry(compiled))
            for found in compiled.reads:
                holder = self.owner(found)
                if holder is not None:
                    depends.add(holder)
                elif self.counted(found):
                    files.add(found)
        unbuilt = sorted(
            p
            for p in files - built
            if p.suffix in SOURCE_SUFFIXES and p.is_relative_to(directory)
        )
        if unbuilt:
            raise Unreadable(
                f"{', '.join(self.name(p) for p in unbuilt)}: no compile entry of "
                f"{self.build / 'compile_commands.json'} builds it"
            )
        parts.sort()
        parts.extend(f"file\0{self.name(p)}\0{self.text(p)}" for p in sorted(files))
        depends.discard(name)
        parts.extend(
            f"depends\0{d}\0{self.group(d, (*seen, name))}" for d in sorted(depends)
        )
        self.done[name] = _digest(parts)
        return self.done[name]

    def shared(self) -> str:
        """Return the SHA-256 of what every group runs with.

        Every compile entry of no group (DuckDB's, cpptrace's, nanobind's,
        the bindings', the extension's, generated ones), a generated
        source's text, every file such an entry reads in the tree outside a
        group's directory, and the fingerprints of the closure of each
        group whose file such an entry reads.
        """
        files: set[Path] = set()
        for directory in self.shared_dirs:
            files.update(_files((self.root / directory).resolve()))
        entries = []
        generated = set()
        read_groups: set[str] = set()
        for compiled in self.compiled:
            if compiled.owner is not None:
                continue
            entries.append(self.entry(compiled))
            if compiled.source.is_relative_to(self.build):
                generated.add(compiled.source)
            for found in compiled.reads:
                holder = self.owner(found)
                if holder is not None:
                    read_groups.add(holder)
                elif self.counted(found):
                    files.add(found)
        generated.update(
            p
            for p in self.build.rglob("*")
            if p.suffix in CPP_SUFFIXES - SOURCE_SUFFIXES
            and "CMakeFiles" not in p.relative_to(self.build).parts
            and p.is_file()
        )
        files -= generated
        parts = sorted(entries)
        parts.extend(
            f"generated\0{self.name(p)}\0{_bytes(p, self.root)}"
            for p in sorted(generated)
        )
        parts.extend(f"file\0{self.name(p)}\0{self.text(p)}" for p in sorted(files))
        # The bindings run the groups they read (crash::install at start-up,
        # spec 5.2): those groups and the ones they are built on are shared.
        parts.extend(
            f"group\0{name}\0{self.group(name)}"
            for name in sorted(closure(self.groups, read_groups))
        )
        self.shared_groups = frozenset(closure(self.groups, read_groups))
        pins = "\n".join(f"{n}\0{c}" for n, c in sorted(self.pins.items()))
        parts.append(f"pins\0{pins}")
        parts.append(f"build tables\0{_build_tables(self.root)}")
        parts.append(f"compiler\0{_ctest.compiler(self.build)}")
        # A group's own objects are in its fingerprint (its sources and
        # flags): leave them out, or a new source of a group moves every part.
        markers = tuple(f"/CMakeFiles/sq_{name}.dir/" for name in self.groups)
        link = [
            arg
            for arg in _link_command(self.build)
            if not any(marker in arg for marker in markers)
        ]
        parts.append(f"link\0{_normalised(link, self.root)}")
        return _digest(parts)


def fingerprints(root: Path, build: Path) -> Fingerprints:
    """Return the module's fingerprints as `build` builds it from `root`.

    Parameters
    ----------
    root : Path
        The repository's working tree.
    build : Path
        The module's build directory, relative to `root` or absolute
        (``WHEEL_BUILD``).

    Returns
    -------
    Fingerprints
        The shared part, each group's fingerprint and the manifest read.

    Raises
    ------
    Unreadable
        The manifest, ``compile_commands.json``, the link command or a listed
        file is missing, or a source no compile entry builds.
    """
    root = root.resolve()
    build = (root / build).resolve()
    groups, shared = load(build)
    making = _Fingerprinter(root, build, groups, shared)
    prints = {name: making.group(name) for name in sorted(groups)}
    shared_part = making.shared()
    return Fingerprints(
        shared=shared_part,
        groups=prints,
        shared_groups=making.shared_groups,
        manifest=groups,
    )


def closure(groups: dict[str, Group], names: Iterable[str]) -> set[str]:
    """Return the groups `names` and every group they depend on, transitively.

    Parameters
    ----------
    groups : dict of str to Group
        The manifest's groups.
    names : iterable of str
        The groups used.

    Returns
    -------
    set of str
        The names, with their dependencies.

    Raises
    ------
    Unreadable
        A name is no group of the manifest.
    """
    found: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in found:
            continue
        if name not in groups:
            raise Unreadable(f"no C++ group {name} in the manifest")
        found.add(name)
        pending.extend(groups[name].depends)
    return found


def identity(
    prints: Fingerprints, groups: dict[str, Group], uses: Iterable[str] | None
) -> str:
    """Return the SHA-256 of the module as what uses `uses` reads it.

    Parameters
    ----------
    prints : Fingerprints
        The module's fingerprints.
    groups : dict of str to Group
        The manifest's groups.
    uses : iterable of str or None
        The groups used; None for every group (what no group claims).

    Returns
    -------
    str
        The SHA-256 of the shared part and the fingerprints of the groups'
        closure.
    """
    chosen = set(groups) if uses is None else closure(groups, uses)
    missing = sorted(chosen - set(prints.groups))
    if missing:
        raise Unreadable(f"no fingerprint of the group {', '.join(missing)}")
    parts = [f"shared\0{prints.shared}"]
    parts.extend(f"group\0{name}\0{prints.groups[name]}" for name in sorted(chosen))
    return _digest(parts)

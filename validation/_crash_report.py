"""Read a crash report (``just crash-report <file>``).

The crash handler writes addresses, not names (it may not allocate in a
signal): each frame's address, the image it falls in and that image's load
address. This turns them into names and says whose code each frame is.

The module's names come from the linker's map, ``build/<cache tag>/_duckdb.map``
(``engine/CMakeLists.txt``): nanobind links the module with ``-x -S``, which
keeps none of sqlearn's (hidden) names in the binary, so ``atos`` alone would
name a sqlearn frame after the DuckDB symbol before it. The map lists every
symbol with the object it came from, so a frame's owner is read from that
object: sqlearn's groups and extension, DuckDB's library and extensions,
nanobind, cpptrace. Frames of other images are named by ``atos`` and owned by
Python (its library or program) or the system. macOS only: Linux's map and
``addr2line`` come at step 3.
"""

from __future__ import annotations

import bisect
import ctypes
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MODULE = "_duckdb.abi3.so"
"""The image sqlearn's and DuckDB's code is in."""

MAP_NAME = "_duckdb.map"
"""The linker's map of the module, in the wheel's build directory."""


@dataclass(frozen=True)
class Frame:
    """One line of a report's stack: ``pc`` or ``#<n>``."""

    label: str
    """``pc`` for the faulting instruction, ``#0`` and on for the stack."""
    address: int
    """The code address."""
    image: str | None
    """The image's path; None when the handler knew none."""
    load: int | None
    """The image's load address; None without an image."""


@dataclass(frozen=True)
class Report:
    """What a report says."""

    signal: str
    """The signal's name, such as ``SIGSEGV``."""
    build: str
    """The build line, as ``sqlearn._native.describe()`` gives it."""
    frames: tuple[Frame, ...]
    """The faulting instruction, then the stack, innermost first."""


@dataclass(frozen=True)
class Symbol:
    """A code symbol of the map."""

    start: int
    """Its address in the module, from the module's load address."""
    size: int
    """Its size in bytes."""
    name: str
    """Its mangled name."""
    source: str
    """The object file it came from, as the map gives it."""


@dataclass(frozen=True)
class Named:
    """A frame with its owner and its name."""

    label: str
    """As the frame's."""
    owner: str
    """``sqlearn``, ``DuckDB``, ``nanobind``, ``cpptrace``, ``Python`` or
    ``system``; ``unknown`` when neither the map nor ``atos`` names it."""
    name: str
    """The function, demangled; empty when unknown."""


FRAME = re.compile(
    r"^(pc|#\d+) 0x([0-9a-fA-F]+) (?:(.+?) \(load address 0x([0-9a-fA-F]+)\)|\(.*\))$"
)
"""A frame's line: its label, address, and the image and its load address
(none for the program or an address in no image)."""

SYMBOL = re.compile(r"^0x([0-9A-Fa-f]+)\t0x([0-9A-Fa-f]+)\t\[ *(\d+)\] (.+)$")
"""A line of the map's symbols: address, size, object file, name."""

NOT_CODE = ("FDE for:", "CIE", "literal string:", "ltmp")
"""Map entries that name no function: unwind entries, strings, labels."""

HANDLER = ("sq::crash::", "cpptrace::", "_sigtramp")
"""The crash handler's own frames, and the system's signal trampoline that
calls it: on every report's stack, never the crash."""

PLAIN_DUCKDB = (
    "Fix: reproduce it in plain DuckDB 2.0.1 (the official duckdb package, in "
    "an environment of its own) with the SQL sqlearn ran, on made-up data "
    "shaped like the user's, never their data: a crash there is DuckDB's, to "
    "report on DuckDB's issue tracker and explain to the user; none there "
    "means sqlearn's calls reached DuckDB in a state it does not expect, and "
    "it is sqlearn's to fix."
)


def parse(text: str) -> Report:
    """Return what the report `text` says.

    Parameters
    ----------
    text : str
        The report, as the crash handler wrote it.

    Returns
    -------
    Report
        Its signal, build line and frames; empty fields for lines it lacks.
    """
    signal = re.search(r"^signal: (\S+)", text, re.MULTILINE)
    build = re.search(r"^build: (.*)$", text, re.MULTILINE)
    frames = []
    for line in text.splitlines():
        found = FRAME.match(line)
        if not found:
            continue
        label, address, image, load = found.groups()
        if image == "(the program)":
            # The loader gave the program no name: nothing to name it with.
            image, load = None, None
        frames.append(
            Frame(
                label,
                int(address, 16),
                image,
                int(load, 16) if load is not None and image is not None else None,
            )
        )
    return Report(
        signal=signal.group(1) if signal else "",
        build=build.group(1) if build else "",
        frames=tuple(frames),
    )


class Map:
    """The linker's map of the module: its code symbols, by address."""

    def __init__(self, text: str) -> None:
        objects: dict[int, str] = {}
        symbols: list[Symbol] = []
        part = ""
        for line in text.splitlines():
            if line.startswith("# Object files:"):
                part = "objects"
            elif line.startswith("# Symbols:"):
                part = "symbols"
            elif line.startswith(("# Sections:", "# Dead Stripped Symbols:")):
                part = ""
            elif part == "objects":
                found = re.match(r"^\[ *(\d+)\] (.+)$", line)
                if found:
                    objects[int(found.group(1))] = found.group(2)
            elif part == "symbols":
                found = SYMBOL.match(line)
                if not found or found.group(4).startswith(NOT_CODE):
                    continue
                start, size = int(found.group(1), 16), int(found.group(2), 16)
                if size == 0:
                    continue
                source = objects.get(int(found.group(3)), "")
                symbols.append(Symbol(start, size, found.group(4), source))
        symbols.sort(key=lambda s: s.start)
        self.symbols = symbols
        self._starts = [s.start for s in symbols]

    def symbol_at(self, offset: int) -> Symbol | None:
        """Return the symbol holding `offset` (from the load address).

        Parameters
        ----------
        offset : int
            A frame's address less the module's load address.

        Returns
        -------
        Symbol or None
            The symbol whose bytes hold it; None when none does.
        """
        at = bisect.bisect_right(self._starts, offset) - 1
        if at < 0:
            return None
        symbol = self.symbols[at]
        return symbol if offset < symbol.start + symbol.size else None


def owner_of_object(source: str) -> str:
    """Return whose code the map's object file `source` is.

    Parameters
    ----------
    source : str
        The object's path as the map gives it, relative to the build.

    Returns
    -------
    str
        ``sqlearn``, ``DuckDB``, ``nanobind``, ``cpptrace`` or ``unknown``.
    """
    if "CMakeFiles/sq_" in source or "libsqlearn_extension.a" in source:
        return "sqlearn"
    if "cpptrace" in source:
        return "cpptrace"
    if "nanobind" in source:
        return "nanobind"
    if source.startswith("duckdb-python/"):
        return "DuckDB"
    return "unknown"


def owner_of_image(path: str) -> str:
    """Return whose code an image other than the module is.

    Parameters
    ----------
    path : str
        The image's path.

    Returns
    -------
    str
        ``Python`` for Python's library, program or one of its extension
        modules; ``system`` otherwise.
    """
    name = Path(path).name.lower()
    if (
        "python" in name
        or "Python.framework" in path
        or re.match(r".*\.cpython-\d+.*\.so$", name)
    ):
        return "Python"
    return "system"


def _outside_handler(frames: list[Named]) -> list[Named]:
    """The faulting instruction, then the stack without the handler's frames."""
    return [f for f in frames if f.label == "pc" or not f.name.startswith(HANDLER)]


def verdict(frames: list[Named]) -> str:
    """Say whose code most likely crashed, and what to do about it.

    The nearest frame to the fault that is sqlearn's or DuckDB's decides:
    the faulting instruction itself, else its nearest caller (a fault in a
    system function, memcpy say, is the caller's). The crash handler's own
    frames are left out.

    Parameters
    ----------
    frames : list of Named
        The report's frames, named, the faulting instruction first.

    Returns
    -------
    str
        One paragraph.
    """
    kept = _outside_handler(frames)
    fault = kept[0] if kept else None
    nearest = next((f for f in kept if f.owner in ("sqlearn", "DuckDB")), None)
    where = (
        f"{fault.name or 'an unnamed address'} ({fault.owner})"
        if fault
        else "an unknown place"
    )
    if nearest is None:
        return (
            "Neither sqlearn's nor DuckDB's code crashed: the fault is in "
            f"{where}, and no frame below the crash handler is theirs. Read "
            "the frames for who called it."
        )
    who = "DuckDB's" if nearest.owner == "DuckDB" else "sqlearn's"
    said = f"{who} code crashed: {nearest.name}"
    if nearest is not fault:
        said += f", in a call to {where}"
    if nearest.owner == "DuckDB":
        return f"{said}.\n{PLAIN_DUCKDB}"
    return f"{said}. It is sqlearn's to fix: the frames above show the path."


def _demangle(names: list[str]) -> dict[str, str]:
    """Demangle the map's names with c++filt, which drops one underscore."""
    if not names:
        return {}
    done = subprocess.run(
        ["c++filt"], input="\n".join(names), capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return dict(zip(names, done, strict=True))


def _loaded_here(address: int, image: str, load: int) -> bool:
    """Whether `image` is loaded in this process at `load`, with `address`
    in it: a library of the system's shared cache, mapped at the same place
    in every process until the next boot."""
    info = _DlInfo()
    if _dladdr(ctypes.c_void_p(address), ctypes.byref(info)) == 0:
        return False
    name = info.dli_fname.decode(errors="replace") if info.dli_fname else ""
    return name == image and info.dli_fbase == load


class _DlInfo(ctypes.Structure):
    """dladdr(3)'s answer."""

    _fields_ = [
        ("dli_fname", ctypes.c_char_p),
        ("dli_fbase", ctypes.c_void_p),
        ("dli_sname", ctypes.c_char_p),
        ("dli_saddr", ctypes.c_void_p),
    ]


def _dladdr_function() -> Callable[..., int]:
    """dladdr(3), from the system's C library."""
    function = ctypes.CDLL(None).dladdr
    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DlInfo)]
    function.restype = ctypes.c_int
    return function


_dladdr = _dladdr_function()


def _atos(image: str, load: int, addresses: list[int]) -> list[str]:
    """Name `addresses` of `image` with atos; an empty name when it cannot.

    A library loaded at the same place here (the system's shared cache, the
    same boot) is named through this process (``atos -p``), which reads the
    cache as loaded, its local symbols too; ``atos -o`` on the library's file
    names it wrong, the file on disk not being the cache's copy. Any other
    image is named from its file.
    """
    if all(_loaded_here(a, image, load) for a in addresses):
        command = ["atos", "-p", str(os.getpid())]
    else:
        command = ["atos", "-o", image, "-l", hex(load)]
    command += [hex(a) for a in addresses]
    try:
        out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ["" for _ in addresses]
    names = []
    for line in out.splitlines():
        # "name (in image) (file:line)" or "name (in image) + offset"; a bare
        # address when it knows none.
        name = re.sub(r" \(in [^)]*\).*$", "", line.strip())
        names.append("" if name.startswith("0x") else name)
    return (names + [""] * len(addresses))[: len(addresses)]


def name_frames(report: Report, symbols: Map) -> list[Named]:
    """Name each of `report`'s frames and say whose code it is.

    Parameters
    ----------
    report : Report
        The report.
    symbols : Map
        The module's map, from the build the report was written by.

    Returns
    -------
    list of Named
        One per frame, in the report's order.
    """
    found: dict[int, tuple[str, str]] = {}
    mangled: list[str] = []
    others: dict[tuple[str, int], list[int]] = {}
    for i, frame in enumerate(report.frames):
        if frame.image is None or frame.load is None:
            continue
        if Path(frame.image).name == MODULE:
            symbol = symbols.symbol_at(frame.address - frame.load)
            if symbol is not None:
                found[i] = (owner_of_object(symbol.source), symbol.name)
                mangled.append(symbol.name)
        else:
            others.setdefault((frame.image, frame.load), []).append(i)
    plain = _demangle(sorted(set(mangled)))
    out: dict[int, Named] = {}
    for i, (owner, name) in found.items():
        out[i] = Named(report.frames[i].label, owner, plain.get(name, name))
    for (image, load), indices in others.items():
        names = _atos(image, load, [report.frames[i].address for i in indices])
        for i, name in zip(indices, names, strict=True):
            out[i] = Named(report.frames[i].label, owner_of_image(image), name)
    return [
        out.get(i, Named(f.label, "unknown", "")) for i, f in enumerate(report.frames)
    ]


def _installed_build() -> str:
    """The build line of the sqlearn installed here."""
    from sqlearn import _native

    return _native.describe()


def _the_map(repo: Path) -> Path | None:
    """The module's map in the wheel's build directory, or None."""
    found = sorted((repo / "build").glob(f"*/{MAP_NAME}"))
    return found[0] if found else None


def main(argv: list[str]) -> int:
    """Print the report `argv[0]`'s frames, named and owned, and the verdict.

    Parameters
    ----------
    argv : list of str
        The report's path.

    Returns
    -------
    int
        0 when it was read, 1 when it could not be (with a ``Fix:`` line).
    """
    if len(argv) != 1:
        print("Fix: just crash-report <the report's path>")  # noqa: T201
        return 1
    if sys.platform != "darwin":
        print(  # noqa: T201
            "Reading a report needs macOS's atos and its linker's map; Linux's "
            "come at Phase 1 step 3.\nFix: read it on macOS, or symbolise each "
            "address with the addr2line line the report gives"
        )
        return 1
    report = parse(Path(argv[0]).read_text(encoding="utf-8", errors="replace"))
    here = _installed_build()
    if report.build != here:
        print(  # noqa: T201
            f"The report was written by the build\n  {report.build}\nand this "
            f"one is\n  {here}\nso its addresses name nothing here.\nFix: "
            "check out the commit the report's build names, then uv sync "
            "--locked, and read it there"
        )
        return 1
    map_path = _the_map(Path(__file__).resolve().parents[1])
    if map_path is None:
        print(  # noqa: T201
            "There is no linker map of the module (build/<cache tag>/"
            f"{MAP_NAME}), so sqlearn's frames cannot be named.\nFix: uv sync "
            "--reinstall-package sqlearn, whose link writes it"
        )
        return 1
    frames = name_frames(
        report, Map(map_path.read_text(encoding="utf-8", errors="replace"))
    )
    print(f"{report.signal}, {report.build}")  # noqa: T201
    width = max((len(f.owner) for f in frames), default=0)
    for frame in frames:
        print(f"{frame.label} {frame.owner:<{width}} {frame.name}".rstrip())  # noqa: T201
    print()  # noqa: T201
    print(verdict(frames))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

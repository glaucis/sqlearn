"""A profile's summary and its comparison with the previous one.

A profile is a samply recording (``samply record --save-only
--unstable-presymbolicate``), in the Firefox Profiler's processed format as
samply 0.13.1 writes it (``meta.version`` 24, ``preprocessedProfileVersion``
49), plain or gzipped. With ``--unstable-presymbolicate`` the function names
are not in the profile but in a sidecar beside it: for ``profile.json.gz`` or
``profile.json``, ``profile.json.syms.json``. ``summarise`` takes the
profile's path and reads the sidecar from there when it exists; without one,
it uses the names the profile holds.

A frame is named after the symbol whose range holds its address in its image
(inlined frames are not split out). A frame neither the sidecar nor the
profile names (the profile's name is then its address, ``0x…``) is counted as
``unsymbolicated code in <image>``, so its addresses do not split its share.

A sample's stack is read root to leaf: its self time goes to the leaf, its
total time to every distinct function on the stack, once (a recursive
function counts once). Shares are fractions of all samples with a stack,
weighted by samply's sample weights. Each function's owner is whose code it
is (``owner``), and ``owners`` sums the self shares by owner.

The agent reads the summary (``summary.json``) and the comparison
(``compare.md``), so both are exact and stable: functions are ranked by share
descending, then by name, and values are written the same way each time.
"""

from __future__ import annotations

import bisect
import gzip
import json
import re
import shutil
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from validation import _bench, _checks, _groups
from validation._crash_report import owner_of_image

TOP = 30
"""How many functions each ranking keeps."""

MOVED = 0.02
"""A function whose self share moved more than this is in the comparison."""

KEEP = 5
"""How many recordings of a program are kept."""

PROFILES = Path("build/profiles")
"""Where the recordings are, relative to the root: one folder for each program."""

_STAMP = re.compile(r"\d{8}-\d{6}(-\d+)?")


def SAMPLER(argv: list[str], out_file: Path) -> list[str]:  # noqa: N802
    """Return samply's argv recording the program `argv` into `out_file`.

    Parameters
    ----------
    argv : list of str
        The program and its arguments.
    out_file : Path
        Where the profile is written (``profile.json.gz``; the sidecar of
        names goes beside it).

    Returns
    -------
    list of str
        The command that records it, saving only (no browser) and
        presymbolicating.
    """
    return [
        "samply",
        "record",
        "--save-only",
        "--unstable-presymbolicate",
        "-o",
        str(out_file),
        "--",
        *argv,
    ]


@dataclass(frozen=True)
class Function:
    """One function of a profile, with its shares of all samples."""

    name: str
    owner: str
    self_share: float
    total_share: float


@dataclass(frozen=True)
class Summary:
    """What a profile says: its time, its load, and where the time went.

    ``owners`` maps each owner to its share of samples by self time;
    ``by_self`` and ``by_total`` are the top functions by self and by total
    time, each sorted by that share descending, then by name.
    """

    seconds: float
    load_before: str
    load_after: str
    owners: dict[str, float]
    by_self: tuple[Function, ...]
    by_total: tuple[Function, ...]

    def to_json(self) -> dict[str, Any]:
        """Return the summary as JSON data (``from_json`` reads it back).

        Returns
        -------
        dict[str, Any]
            The summary's fields; each function is an object of its four.
        """
        return {
            "seconds": self.seconds,
            "load_before": self.load_before,
            "load_after": self.load_after,
            "owners": dict(self.owners),
            "by_self": [_function_json(f) for f in self.by_self],
            "by_total": [_function_json(f) for f in self.by_total],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Summary:
        """Read a summary that ``to_json`` wrote.

        Parameters
        ----------
        data : dict[str, Any]
            The JSON data.

        Returns
        -------
        Summary
            The summary, equal to the one written.
        """
        return cls(
            seconds=float(data["seconds"]),
            load_before=str(data["load_before"]),
            load_after=str(data["load_after"]),
            owners={str(k): float(v) for k, v in data["owners"].items()},
            by_self=tuple(Function(**f) for f in data["by_self"]),
            by_total=tuple(Function(**f) for f in data["by_total"]),
        )


def _function_json(function: Function) -> dict[str, Any]:
    return {
        "name": function.name,
        "owner": function.owner,
        "self_share": function.self_share,
        "total_share": function.total_share,
    }


def owner(name: str, image: str, program: Path | None = None) -> str:
    """Return whose code a function is.

    Parameters
    ----------
    name : str
        The function's demangled name.
    image : str
        The path (or name) of the image it is in.
    program : Path or None
        The profiled program; an image with its file name is the program's.

    Returns
    -------
    str
        ``sqlearn`` for a name in ``sq::``, ``DuckDB`` in ``duckdb::``,
        ``standard library`` in ``std::`` or in an image named ``libc++*``;
        otherwise ``benchmark program`` in the program's own image, else the
        image's owner (``Python`` or ``system``).
    """
    if name.startswith("sq::"):
        return "sqlearn"
    if name.startswith("duckdb::"):
        return "DuckDB"
    if name.startswith("std::") or Path(image).name.startswith("libc++"):
        return "standard library"
    if program is not None and image and Path(image).name == program.name:
        return "benchmark program"
    return owner_of_image(image)


def _sidecar(profile: Path) -> Path:
    stem = profile.name.removesuffix(".gz")
    return profile.with_name(stem + ".syms.json")


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as text:
            return json.load(text)
    return json.loads(path.read_text(encoding="utf-8"))


class _Symbols:
    """The sidecar's symbols of each image: its ranges, sorted by address."""

    def __init__(self, sidecar: Any) -> None:
        strings = sidecar["string_table"]
        self._images: dict[str, tuple[list[int], list[tuple[int, str]]]] = {}
        for image in sidecar["data"]:
            entries = sorted(
                (e["rva"], e["size"], strings[e["symbol"]])
                for e in image["symbol_table"]
            )
            starts = [rva for rva, _, _ in entries]
            ranges = [(rva + size, name) for rva, size, name in entries]
            for key in (image.get("code_id"), image.get("debug_name")):
                if key:
                    self._images.setdefault(str(key).upper(), (starts, ranges))

    def name(self, lib: dict[str, Any], address: int) -> str | None:
        for key in (lib.get("codeId"), lib.get("debugName"), lib.get("name")):
            if key and str(key).upper() in self._images:
                starts, ranges = self._images[str(key).upper()]
                at = bisect.bisect_right(starts, address) - 1
                if at >= 0 and address < ranges[at][0]:
                    return ranges[at][1]
                return None
        return None


def _frame_names(
    thread: dict[str, Any],
    libs: list[dict[str, Any]],
    strings: list[str],
    symbols: _Symbols,
) -> list[tuple[str, str]]:
    """Each frame's function name and image path."""
    frames = thread["frameTable"]
    funcs = thread["funcTable"]
    resources = thread["resourceTable"]
    named = []
    for frame in range(frames["length"]):
        func = frames["func"][frame]
        resource = funcs["resource"][func]
        lib = None
        if resource is not None and resource >= 0:
            index = resources["lib"][resource]
            if index is not None and index >= 0:
                lib = libs[index]
        image = (lib.get("path") or lib.get("name") or "") if lib else ""
        address = frames["address"][frame]
        name = None
        if lib is not None and address is not None and address >= 0:
            name = symbols.name(lib, address)
        if name is None:
            name = strings[funcs["name"][func]]
            if name.startswith("0x"):
                name = f"unsymbolicated code in {Path(image).name or 'no image'}"
        named.append((name, image))
    return named


def summarise(
    profile: Path,
    seconds: float,
    load_before: str,
    load_after: str,
    *,
    program: Path | None = None,
) -> Summary:
    """Summarise a samply profile.

    Parameters
    ----------
    profile : Path
        The recording (``.json`` or ``.json.gz``); its ``.syms.json``
        sidecar, when beside it, names the functions.
    seconds : float
        The run's wall time.
    load_before, load_after : str
        The load before and after the run (``uptime``'s line).
    program : Path or None
        The profiled program: its own frames that are not in ``sq::``,
        ``duckdb::`` or ``std::`` are owned by ``benchmark program``.

    Returns
    -------
    Summary
        Its owners' shares and its top functions by self and total time.
    """
    data = _read_json(profile)
    sidecar_path = _sidecar(profile)
    symbols = _Symbols(
        _read_json(sidecar_path)
        if sidecar_path.exists()
        else {"string_table": [], "data": []}
    )
    shared = data.get("shared") or {}
    self_weight: Counter[str] = Counter()
    total_weight: Counter[str] = Counter()
    owners_of: dict[str, str] = {}
    all_weight = 0
    for thread in data["threads"]:
        strings = thread.get("stringArray") or shared.get("stringArray") or []
        names = _frame_names(thread, data["libs"], strings, symbols)
        stacks = thread["stackTable"]
        samples = thread["samples"]
        weights = samples.get("weight") or [1] * samples["length"]
        for stack, weight in zip(samples["stack"], weights, strict=True):
            if stack is None:
                continue
            weight = 1 if weight is None else weight
            all_weight += weight
            leaf = True
            seen: set[str] = set()
            while stack is not None:
                name, image = names[stacks["frame"][stack]]
                owners_of.setdefault(name, owner(name, image, program))
                if leaf:
                    self_weight[name] += weight
                    leaf = False
                if name not in seen:
                    seen.add(name)
                    total_weight[name] += weight
                stack = stacks["prefix"][stack]
    if all_weight == 0:
        raise ValueError(f"{profile} holds no samples with a stack")
    functions = [
        Function(
            name,
            owners_of[name],
            self_weight[name] / all_weight,
            total_weight[name] / all_weight,
        )
        for name in total_weight
    ]
    owners: Counter[str] = Counter()
    for function in functions:
        if function.self_share > 0:
            owners[function.owner] += self_weight[function.name]
    by_self = sorted(
        (f for f in functions if f.self_share > 0),
        key=lambda f: (-f.self_share, f.name),
    )
    by_total = sorted(functions, key=lambda f: (-f.total_share, f.name))
    return Summary(
        seconds=seconds,
        load_before=load_before,
        load_after=load_after,
        owners={
            name: count / all_weight
            for name, count in sorted(owners.items(), key=lambda o: (-o[1], o[0]))
        },
        by_self=tuple(by_self[:TOP]),
        by_total=tuple(by_total[:TOP]),
    )


def _share(share: float) -> str:
    return f"{share * 100:.1f}%"


def _cell(name: str) -> str:
    return "`" + name.replace("|", "\\|") + "`"


def _left_the_top(previous: Summary, current: Summary) -> list[str]:
    """Rows for the functions of the previous top 30 the current one lacks.

    The current share is ``by_total``'s when that run knows the function; 0
    when the current top 30 is not full (every function with self time is in
    it); otherwise at most the 30th's, shown as below the top 30. A function
    is listed when it fell by more than 2 points (by that bound, for one below
    a full top 30), in the previous ranking's order.
    """
    in_top = {f.name for f in current.by_self}
    known_now = {f.name: f.self_share for f in current.by_total}
    full = len(current.by_self) >= TOP
    rows = []
    for function in previous.by_self:
        if function.name in in_top:
            continue
        if function.name in known_now:
            now: float = known_now[function.name]
            shown = _share(now)
        elif not full:
            now = 0.0
            shown = _share(now)
        else:
            now = current.by_self[-1].self_share
            shown = "below the top 30"
        if round(function.self_share - now, 12) > MOVED:
            rows.append(
                f"| {_cell(function.name)} | {function.owner}"
                f" | {_share(function.self_share)} | {shown} |"
            )
    return rows


def compare(previous: Summary | None, current: Summary) -> str:
    """Compare a profile's summary with the previous clean one, as Markdown.

    Parameters
    ----------
    previous : Summary or None
        The previous clean profile's summary, None when there is none.
    current : Summary
        This profile's summary.

    Returns
    -------
    str
        Both runs' wall time and loads, each owner's share side by side, and
        the functions whose self share moved more than 2 percentage points
        or that are new in the top 30 by self time, or left it having fallen
        more than 2 points, with both shares. With
        no previous summary, a line saying so.
    """
    heading = "# Profile comparison\n\n"
    if previous is None:
        return heading + "No previous clean profile to compare with.\n"
    lines = [
        "| | previous | current |",
        "| --- | --- | --- |",
        f"| wall time | {previous.seconds:.3f} s | {current.seconds:.3f} s |",
        f"| load before | {previous.load_before} | {current.load_before} |",
        f"| load after | {previous.load_after} | {current.load_after} |",
        "",
        "## Owners, by self time",
        "",
        "| owner | previous | current |",
        "| --- | --- | --- |",
    ]
    for name in sorted(previous.owners.keys() | current.owners.keys()):
        lines.append(
            f"| {name} | {_share(previous.owners.get(name, 0.0))}"
            f" | {_share(current.owners.get(name, 0.0))} |"
        )
    lines += ["", "## Functions that moved", ""]
    top_before = {f.name: f.self_share for f in previous.by_self}
    known_before = {f.name: f.self_share for f in previous.by_total} | top_before
    rows = []
    for function in current.by_self:
        before = known_before.get(function.name)
        if function.name not in top_before:
            shown = "new" if before is None else f"new, {_share(before)}"
        elif round(abs(function.self_share - before), 12) > MOVED:
            shown = _share(before)
        else:
            continue
        rows.append(
            f"| {_cell(function.name)} | {function.owner} | {shown}"
            f" | {_share(function.self_share)} |"
        )
    rows += _left_the_top(previous, current)
    if rows:
        lines += [
            "| function | owner | previous | current |",
            "| --- | --- | --- | --- |",
            *rows,
        ]
    else:
        lines.append(
            "No function's self share moved more than 2 points, and none is"
            " new in the top 30."
        )
    return heading + "\n".join(lines) + "\n"


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _clean_records(root: Path, name: str) -> list[dict[str, Any]]:
    """Return the clean records whose summary file still exists, oldest first."""
    records = cast(
        "list[dict[str, Any]]",
        _checks.load(_checks.record_dir(root), f"{_bench._PROFILE_KEY}-{name}"),
    )
    return [
        r
        for r in records
        if _bench.clean(r) and r.get("summary") and (root / str(r["summary"])).is_file()
    ]


def _previous(root: Path, name: str) -> Summary | None:
    """Return the summary of the newest clean profile that reads, else None."""
    for record in reversed(_clean_records(root, name)):
        try:
            text = (root / str(record["summary"])).read_text(encoding="utf-8")
            return Summary.from_json(json.loads(text))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def _order(path: Path) -> tuple[str, int]:
    """Sort by the stamp (15 characters), then by the ``-N`` after it."""
    return (path.name[:15], int(path.name[16:] or 1))


def _prune(folder: Path, keep: Path | None = None) -> None:
    """Keep the `KEEP` newest recordings and `keep`; delete only ours (``_STAMP``)."""
    ours = sorted(
        (p for p in folder.iterdir() if p.is_dir() and _STAMP.fullmatch(p.name)),
        key=_order,
    )
    for old in ours[:-KEEP]:
        if old != keep:
            shutil.rmtree(old)


def _new_run_dir(folder: Path) -> Path:
    """Make a directory named by ``_stamp``, with ``-2``, ``-3`` after a clash."""
    stamp = _stamp()
    for number in range(1, 1000):
        run_dir = folder / (stamp if number == 1 else f"{stamp}-{number}")
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError:
            continue
        return run_dir
    raise OSError(f"no free directory named {stamp} in {folder}")


def run(root: Path, name: str) -> int:
    """Record the program `name` under samply, summarise and compare it.

    Parameters
    ----------
    root : Path
        The repository's working tree, built, with the profile build's
        program (``just profile`` builds it first).
    name : str
        A C++ benchmark program, ``bench_<name>``.

    Returns
    -------
    int
        0 when recorded; 1 when refused (no samply, a stale build), the
        sampler failed or its profile could not be read (no record is saved); 2
        when `name` is no program.
        The recording is in ``build/profiles/<name>/<YYYYMMDD-HHMMSS>/``
        (``profile.json.gz``, its sidecar, ``summary.json``, ``compare.md``),
        and the ``profile-<name>`` record names the summary.
    """
    if name not in _bench.programs(root):
        print(f"no benchmark program {name}: `just benchmarks-due` lists them")  # noqa: T201
        return 2
    if shutil.which("samply") is None:
        print("samply is not installed.\nFix: brew install samply")  # noqa: T201
        return 1
    stale = _bench._out_of_date(root, name, _bench.PROFILE_BUILD)
    if stale is not None:
        print(  # noqa: T201
            f"{name}: not profiled, {stale}.\n"
            f"Fix: just profile {name} (it builds the program first)"
        )
        return 1
    identity = _bench.profile_identity(root, name)
    folder = root / PROFILES / name
    run_dir = _new_run_dir(folder)
    out_file = run_dir / "profile.json.gz"
    program = [str(root / _bench.PROFILE_BINARIES / name)]
    try:
        measured = _bench.measure(SAMPLER(program, out_file), root)
    except OSError as error:
        print(f"{name} did not start: {error}")  # noqa: T201
        shutil.rmtree(run_dir)
        return 1
    if measured.returncode != 0 or not out_file.is_file():
        why = (
            f"samply exited with {measured.returncode}"
            if measured.returncode != 0
            else "samply wrote no profile"
        )
        print(f"{name}: not recorded, {why}.")  # noqa: T201
        shutil.rmtree(run_dir)
        return 1
    wall, cores = measured.wall, measured.cores
    before, after = measured.before, measured.after
    summary_file = run_dir / "summary.json"
    try:
        summary = summarise(out_file, wall, before, after, program=Path(program[0]))
        previous = _previous(root, name)
        summary_file.write_text(
            json.dumps(summary.to_json(), indent=2) + "\n", encoding="utf-8"
        )
        (run_dir / "compare.md").write_text(
            compare(previous, summary), encoding="utf-8"
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, EOFError) as error:
        print(  # noqa: T201
            f"{name}: not summarised, {error!r}.\n"
            "Fix: update samply (`brew upgrade samply`) if its profile format "
            "changed, or report it: the recording was removed"
        )
        shutil.rmtree(run_dir, ignore_errors=True)
        return 1
    record = {
        "digest": identity,
        "config": name,
        "files": {},
        "seconds": wall,
        "cores": cores,
        "loaded": _bench.loaded(measured),
        "uptime_before": before,
        "uptime_after": after,
        "summary": str(summary_file.relative_to(root)),
    }
    _checks.save(
        _checks.record_dir(root),
        f"{_bench._PROFILE_KEY}-{name}",
        cast("_checks.Record", record),
    )
    newest_clean = _clean_records(root, name)
    _prune(
        folder,
        (root / str(newest_clean[-1]["summary"])).parent if newest_clean else None,
    )
    print(  # noqa: T201
        f"{name}: profiled in {wall:.1f} s"
        f"{' (machine loaded: the record stays due)' if record['loaded'] else ''}.\n"
        f"Read {run_dir.relative_to(root) / 'compare.md'} and "
        f"{run_dir.relative_to(root) / 'summary.json'}."
    )
    return 0


def cli(argv: Sequence[str]) -> int:
    """Parse ``run <name>`` and act in the current directory."""
    if argv[:1] == ["run"] and len(argv) == 2:
        try:
            return run(Path.cwd(), argv[1])
        except _groups.Unreadable as error:
            print(f"profile: {error}")  # noqa: T201
            return 1
    print("usage: python -m validation._profile run <name>")  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))

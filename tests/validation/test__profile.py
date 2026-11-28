"""A profile's summary (top functions, owners' shares) and its comparison.

The fixture, ``data/samply-small.json`` and its ``.syms.json`` sidecar, is a
samply 0.13.1 recording of a two-second loop in ``sq::`` calling ``std::sort``,
trimmed to one frame per function: 2000 samples, whose leaves are
``__bitset_partition`` 1016, ``__introsort`` 693, ``sq::sort_batch`` 226,
``sq::accumulate_squares`` 54, ``_platform_memmove`` 9 and
``__insertion_sort_incomplete`` 2. ``__introsort`` is recursive.
"""

import gzip
import json
import shutil
from pathlib import Path

import pytest

from validation import _bench, _checks, _load
from validation import _profile as pr

DATA = Path(__file__).parent / "data"
FIXTURE = DATA / "samply-small.json"

BITSET = (
    "std::__1::__bitset_partition[abi:nqe220106]<std::__1::_ClassicAlgPolicy,"
    " double*, std::__1::greater<double>&>(std::__1::pair, std::__1::pair,"
    " std::__1::greater<double>&)"
)
INTROSORT = (
    "std::__1::__introsort<std::__1::_ClassicAlgPolicy,"
    " std::__1::greater<double>&, double*, true>(double*, double*,"
    " std::__1::greater<double>&,"
    " std::__1::iterator_traits<double*>::difference_type, bool)"
)
ACCUMULATE = (
    "sq::accumulate_squares(std::__1::vector<double,"
    " std::__1::allocator<double> > const&)"
)
INSERTION = (
    "std::__1::__insertion_sort_incomplete[abi:nqe220106]"
    "<std::__1::_ClassicAlgPolicy, std::__1::greater<double>&, double*>"
    "(double*, double*, std::__1::greater<double>&)"
)


def _summary() -> pr.Summary:
    return pr.summarise(FIXTURE, 2.0, "load averages: 1.0", "load averages: 1.2")


def test_a_summary_names_each_function_with_its_owner():
    """Each function, ranked by self and by total time, with its owner."""
    summary = _summary()
    assert summary.seconds == 2.0
    assert summary.load_before == "load averages: 1.0"
    assert summary.load_after == "load averages: 1.2"
    by_self = [(f.name, f.owner, f.self_share) for f in summary.by_self]
    sort_batch = summary.by_self[2].name
    assert sort_batch.startswith("sq::sort_batch(")
    assert by_self == [
        (BITSET, "standard library", pytest.approx(1016 / 2000, abs=1e-12)),
        (INTROSORT, "standard library", pytest.approx(693 / 2000, abs=1e-12)),
        (sort_batch, "sqlearn", pytest.approx(226 / 2000, abs=1e-12)),
        (ACCUMULATE, "sqlearn", pytest.approx(54 / 2000, abs=1e-12)),
        ("_platform_memmove", "system", pytest.approx(9 / 2000, abs=1e-12)),
        (INSERTION, "standard library", pytest.approx(2 / 2000, abs=1e-12)),
    ]
    assert sum(f.self_share for f in summary.by_self) == pytest.approx(1, abs=1e-9)
    # Total time counts each function once a sample, the recursive
    # __introsort too.
    by_total = [(f.name, f.owner, f.total_share) for f in summary.by_total]
    assert by_total == [
        ("main", "system", 1.0),
        ("sq::run()", "sqlearn", 1.0),
        ("start", "system", 1.0),
        (sort_batch, "sqlearn", pytest.approx(1937 / 2000, abs=1e-12)),
        (INTROSORT, "standard library", pytest.approx(1711 / 2000, abs=1e-12)),
        (BITSET, "standard library", pytest.approx(1016 / 2000, abs=1e-12)),
        (ACCUMULATE, "sqlearn", pytest.approx(54 / 2000, abs=1e-12)),
        ("_platform_memmove", "system", pytest.approx(9 / 2000, abs=1e-12)),
        (INSERTION, "standard library", pytest.approx(2 / 2000, abs=1e-12)),
    ]
    assert summary.owners == {
        "standard library": pytest.approx(1711 / 2000, abs=1e-12),
        "sqlearn": pytest.approx(280 / 2000, abs=1e-12),
        "system": pytest.approx(9 / 2000, abs=1e-12),
    }
    assert sum(summary.owners.values()) == pytest.approx(1, abs=1e-9)


def test_a_gzipped_profile_reads_its_sidecar_beside_it(tmp_path):
    """samply's ``-o profile.json.gz`` writes ``profile.json.syms.json`` beside it."""
    with gzip.open(tmp_path / "profile.json.gz", "wb") as out:
        out.write(FIXTURE.read_bytes())
    shutil.copy(
        DATA / "samply-small.json.syms.json", tmp_path / "profile.json.syms.json"
    )
    summary = pr.summarise(
        tmp_path / "profile.json.gz", 2.0, "load averages: 1.0", "load averages: 1.2"
    )
    assert summary == _summary()


def _one_frame_profile(func_name: str, lib: str) -> dict[str, object]:
    return {
        "meta": {"version": 24, "preprocessedProfileVersion": 49},
        "libs": [{"name": lib, "path": f"/usr/lib/{lib}", "codeId": "AB"}],
        "threads": [
            {
                "samples": {"length": 1, "stack": [0], "weight": [3]},
                "stackTable": {"length": 1, "prefix": [None], "frame": [0]},
                "frameTable": {"length": 1, "address": [0x1234], "func": [0]},
                "funcTable": {"length": 1, "name": [0], "resource": [0]},
                "resourceTable": {"length": 1, "lib": [0], "name": [1]},
                "stringArray": [func_name, lib],
            }
        ],
    }


def test_an_address_without_a_symbol_counts_under_its_image(tmp_path):
    """A frame no one names counts under its image, its addresses together."""
    # ASSUMPTION: a frame neither the sidecar nor the profile names is
    # grouped under its image, so its addresses do not split its share.
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_one_frame_profile("0x1234", "libc++.1.dylib")))
    summary = pr.summarise(path, 1.0, "a", "b")
    assert summary.by_self == (
        pr.Function(
            "unsymbolicated code in libc++.1.dylib", "standard library", 1.0, 1.0
        ),
    )


def test_a_name_the_profile_holds_is_used_without_a_sidecar(tmp_path):
    """Without a sidecar the names come from the profile itself."""
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_one_frame_profile("duckdb::Run()", "libx.dylib")))
    summary = pr.summarise(path, 1.0, "a", "b")
    assert summary.by_self == (pr.Function("duckdb::Run()", "DuckDB", 1.0, 1.0),)
    assert summary.owners == {"DuckDB": 1.0}


def test_a_summary_round_trips_through_json():
    """``from_json`` reads back exactly what ``to_json`` wrote."""
    summary = _summary()
    data = json.loads(json.dumps(summary.to_json()))
    assert pr.Summary.from_json(data) == summary
    assert data["by_self"][4] == {
        "name": "_platform_memmove",
        "owner": "system",
        "self_share": 9 / 2000,
        "total_share": 9 / 2000,
    }


@pytest.mark.parametrize(
    ("name", "image", "expected"),
    [
        ("sq::run()", "/x/_duckdb.abi3.so", "sqlearn"),
        ("duckdb::Executor::Run()", "/x/_duckdb.abi3.so", "DuckDB"),
        ("std::__1::__introsort<double*>()", "/x/loop", "standard library"),
        ("operator new(unsigned long)", "/usr/lib/libc++.1.dylib", "standard library"),
        ("__cxa_throw", "/usr/lib/libc++abi.dylib", "standard library"),
        ("_PyEval_EvalFrameDefault", "/x/Python.framework/Python", "Python"),
        ("_platform_memmove", "/usr/lib/system/libsystem_platform.dylib", "system"),
        ("main", "/x/build/bench_thing", "benchmark program"),
        (
            "ankerl::nanobench::Bench::run()",
            "/x/build/bench_thing",
            "benchmark program",
        ),
        ("sq::run()", "/x/build/bench_thing", "sqlearn"),
        ("std::__1::sort<int*>()", "/x/build/bench_thing", "standard library"),
        ("_platform_memmove", "/x/libsystem_platform.dylib", "system"),
    ],
)
def test_owner_reads_the_namespace_then_the_image(name, image, expected):
    """The namespace decides first, then the image; the program's own is its own."""
    assert pr.owner(name, image, Path("/x/build/bench_thing")) == expected


def test_the_program_is_not_owned_without_its_path():
    """Without the program's path its image is system, not the program's."""
    assert pr.owner("main", "/x/build/bench_thing") == "system"


LAMBDA = "(anonymous namespace)::run()::$_0::operator()() const"


def test_a_frame_in_the_programs_own_image_is_the_benchmark_program(tmp_path):
    """A lambda in the profiled program's image counts under benchmark program."""
    sidecar = json.loads((DATA / "samply-small.json.syms.json").read_text())
    sidecar["string_table"][sidecar["string_table"].index(ACCUMULATE)] = LAMBDA
    (tmp_path / "profile.json.syms.json").write_text(json.dumps(sidecar))
    shutil.copy(FIXTURE, tmp_path / "profile.json")
    summary = pr.summarise(
        tmp_path / "profile.json", 2.0, "a", "b", program=Path("/x/build/loop")
    )
    lambda_function = next(f for f in summary.by_self if f.name == LAMBDA)
    assert lambda_function.owner == "benchmark program"
    assert summary.owners["benchmark program"] == pytest.approx(54 / 2000, abs=1e-12)
    assert summary.owners["sqlearn"] == pytest.approx(226 / 2000, abs=1e-12)
    plain = pr.summarise(tmp_path / "profile.json", 2.0, "a", "b")
    assert plain.owners["system"] == pytest.approx(63 / 2000, abs=1e-12)


def _function(name: str, self_share: float) -> pr.Function:
    return pr.Function(name, "sqlearn", self_share, self_share)


def _made(seconds: float, load: str, *functions: pr.Function) -> pr.Summary:
    owners = {"sqlearn": sum(f.self_share for f in functions)}
    return pr.Summary(
        seconds, f"{load} before", f"{load} after", owners, functions, functions
    )


PREVIOUS = _made(2.0, "quiet", _function("sq::a", 0.10), _function("sq::b", 0.20))


def test_a_comparison_names_a_function_that_moved_over_two_points():
    """A move of 2.5 points is listed with both shares; one of 1 point is not."""
    current = _made(2.5, "busy", _function("sq::a", 0.11), _function("sq::b", 0.225))
    text = pr.compare(PREVIOUS, current)
    assert "| `sq::b` | sqlearn | 20.0% | 22.5% |" in text
    assert "sq::a" not in text


def test_a_comparison_names_a_function_new_in_the_top_thirty():
    """A function absent from the previous top 30 is listed as new."""
    current = _made(
        2.0,
        "quiet",
        _function("sq::a", 0.10),
        _function("sq::b", 0.20),
        _function("sq::c", 0.05),
    )
    text = pr.compare(PREVIOUS, current)
    assert "| `sq::c` | sqlearn | new | 5.0% |" in text
    assert "sq::a" not in text
    assert "sq::b" not in text


def test_a_comparison_states_both_loads():
    """Both runs' wall time and loads, and the owners side by side."""
    current = _made(2.5, "busy", _function("sq::a", 0.10), _function("sq::b", 0.20))
    assert pr.compare(PREVIOUS, current) == (
        "# Profile comparison\n"
        "\n"
        "| | previous | current |\n"
        "| --- | --- | --- |\n"
        "| wall time | 2.000 s | 2.500 s |\n"
        "| load before | quiet before | busy before |\n"
        "| load after | quiet after | busy after |\n"
        "\n"
        "## Owners, by self time\n"
        "\n"
        "| owner | previous | current |\n"
        "| --- | --- | --- |\n"
        "| sqlearn | 30.0% | 30.0% |\n"
        "\n"
        "## Functions that moved\n"
        "\n"
        "No function's self share moved more than 2 points, and none is new in"
        " the top 30.\n"
    )


def test_with_no_previous_summary_the_comparison_says_so():
    """With no previous clean profile, one line says so."""
    current = _made(2.5, "busy", _function("sq::a", 0.10))
    assert pr.compare(None, current) == (
        "# Profile comparison\n\nNo previous clean profile to compare with.\n"
    )


def test_a_comparison_names_a_function_that_left_the_top_thirty():
    """A function gone from the current top 30 is listed when it fell more
    than 2 points: its current share from ``by_total``, or 0 when the
    current ranking is shorter than 30 and does not know it."""
    previous = _made(
        2.0,
        "quiet",
        _function("sq::gone", 0.15),
        _function("sq::dropped", 0.15),
        _function("sq::eased", 0.15),
    )
    kept = _function("sq::kept", 0.5)
    current = pr.Summary(
        2.0,
        "quiet before",
        "quiet after",
        {"sqlearn": 0.5},
        (kept,),
        (
            kept,
            pr.Function("sq::dropped", "sqlearn", 0.12, 0.3),
            pr.Function("sq::eased", "sqlearn", 0.14, 0.3),
        ),
    )
    text = pr.compare(previous, current)
    assert "| `sq::gone` | sqlearn | 15.0% | 0.0% |" in text
    assert "| `sq::dropped` | sqlearn | 15.0% | 12.0% |" in text
    assert "sq::eased" not in text


def test_a_function_below_a_full_top_thirty_is_shown_as_below_it():
    """When the current top 30 is full and does not know a function, its
    share is at most the 30th's: listed as below the top 30 when that bound
    is more than 2 points under its previous share."""
    previous = _made(2.0, "quiet", _function("sq::gone", 0.15))
    top = tuple(_function(f"sq::f{i:02}", 0.04) for i in range(30))
    current = pr.Summary(2.0, "a", "b", {"sqlearn": 1.0}, top, top)
    text = pr.compare(previous, current)
    assert "| `sq::gone` | sqlearn | 15.0% | below the top 30 |" in text


def _many_functions_profile(count: int) -> dict[str, object]:
    """One one-frame sample per function, function ``i`` weighing ``i + 1``."""
    return {
        "meta": {"version": 24, "preprocessedProfileVersion": 49},
        "libs": [{"name": "loop", "path": "/x/loop", "codeId": "AB"}],
        "threads": [
            {
                "samples": {
                    "length": count,
                    "stack": list(range(count)),
                    "weight": [i + 1 for i in range(count)],
                },
                "stackTable": {
                    "length": count,
                    "prefix": [None] * count,
                    "frame": list(range(count)),
                },
                "frameTable": {
                    "length": count,
                    "address": [-1] * count,
                    "func": list(range(count)),
                },
                "funcTable": {
                    "length": count,
                    "name": list(range(count)),
                    "resource": [0] * count,
                },
                "resourceTable": {"length": 1, "lib": [0], "name": [count]},
                "stringArray": [f"sq::f{i:02}" for i in range(count)] + ["loop"],
            }
        ],
    }


def test_each_ranking_keeps_the_top_thirty(tmp_path):
    """Of 31 functions, the lightest is cut from both rankings."""
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_many_functions_profile(31)))
    summary = pr.summarise(path, 1.0, "a", "b")
    expected = [f"sq::f{i:02}" for i in range(30, 0, -1)]
    assert [f.name for f in summary.by_self] == expected
    assert [f.name for f in summary.by_total] == expected
    assert summary.owners == {"sqlearn": pytest.approx(1.0, abs=1e-12)}


# `run`: one profile of a C++ program, the sampler replaced by a fake that
# writes the fixture where samply would.


@pytest.fixture(autouse=True)
def _idle_machine(monkeypatch):
    """Run every test on an idle machine, with samply found."""
    monkeypatch.setattr(_load, "now", lambda: 0.0)
    _samply(monkeypatch, "/fake/samply")


def _samply(monkeypatch, found):
    """Make `shutil.which("samply")` say `found`; other tools are found as usual."""
    which = shutil.which
    monkeypatch.setattr(
        pr.shutil,
        "which",
        lambda tool, *a, **k: found if tool == "samply" else which(tool, *a, **k),
    )


def _program(scratch):
    manifest = scratch.build / "sq_groups.json"
    text = manifest.read_text().replace('"bench": []', '"bench": ["thing"]', 1)
    manifest.write_text(text)
    bench = scratch.root / "engine" / "bench"
    bench.mkdir(parents=True)
    (bench / "bench_thing.cpp").write_text("int main() {}\n")
    binary = scratch.root / "engine" / "build" / "profile" / "bench" / "bench_thing"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


def _fake_sampler(monkeypatch, *, write=True, exit_code=0):
    """Replace samply: write the fixture to the output file, run `exit_code`."""
    calls = []

    def sampler(argv, out_file):
        calls.append((list(argv), out_file))
        if write:
            with gzip.open(out_file, "wt", encoding="utf-8") as text:
                text.write(FIXTURE.read_text(encoding="utf-8"))
            shutil.copy(
                DATA / "samply-small.json.syms.json",
                out_file.with_name("profile.json.syms.json"),
            )
        return ["sh", "-c", f"exit {exit_code}"]

    monkeypatch.setattr(pr, "SAMPLER", sampler)
    return calls


def _clock(monkeypatch):
    """Make each run's directory name a different second."""
    ticks = iter(range(100))
    monkeypatch.setattr(pr, "_stamp", lambda: f"20261128-1200{next(ticks):02d}")


def _records(scratch):
    return _checks.load(_checks.record_dir(scratch.root), "profile-bench_thing")


def _dirs(scratch):
    folder = scratch.root / "build" / "profiles" / "bench_thing"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_a_profile_writes_its_summary_comparison_and_record(
    scratch, monkeypatch, capsys
):
    """A run records the program under samply and saves what the agent reads."""
    _program(scratch)
    calls = _fake_sampler(monkeypatch)
    _clock(monkeypatch)
    assert pr.run(scratch.root, "bench_thing") == 0
    [(argv, out_file)] = calls
    assert argv == [str(scratch.root / "engine/build/profile/bench/bench_thing")]
    [folder] = (scratch.root / "build/profiles/bench_thing").iterdir()
    assert out_file == folder / "profile.json.gz"
    assert (folder / "summary.json").is_file()
    assert "No previous clean profile" in (folder / "compare.md").read_text()
    summary = pr.Summary.from_json(json.loads((folder / "summary.json").read_text()))
    assert summary.by_self[0].name == BITSET
    [record] = _records(scratch)
    assert record["digest"] == _bench.profile_identity(scratch.root, "bench_thing")
    assert record["config"] == "bench_thing"
    assert record["files"] == {}
    assert record["loaded"] is False
    assert record["summary"] == str((folder / "summary.json").relative_to(scratch.root))
    assert record["seconds"] > 0
    assert record["cores"] >= 0
    assert {"uptime_before", "uptime_after"} <= record.keys()
    assert "compare.md" in capsys.readouterr().out


def test_the_comparison_uses_the_last_clean_profile(scratch, monkeypatch):
    """A loaded profile newer than a clean one is skipped as the previous."""
    _program(scratch)
    _fake_sampler(monkeypatch)
    _clock(monkeypatch)
    assert pr.run(scratch.root, "bench_thing") == 0
    assert pr.run(scratch.root, "bench_thing") == 0
    monkeypatch.setattr(_load, "now", lambda: 1000.0)
    assert pr.run(scratch.root, "bench_thing") == 0
    monkeypatch.setattr(_load, "now", lambda: 0.0)
    second = _dirs(scratch)[1]
    assert _records(scratch)[2]["loaded"] is True
    assert pr.run(scratch.root, "bench_thing") == 0
    folder = scratch.root / "build/profiles/bench_thing"
    text = (folder / _dirs(scratch)[-1] / "compare.md").read_text()
    assert "| wall time |" in text
    # Its previous is the second run: the loaded third is skipped.
    previous = pr.Summary.from_json(
        json.loads((folder / second / "summary.json").read_text())
    )
    assert f"| wall time | {previous.seconds:.3f} s |" in text


def test_only_five_recordings_are_kept(scratch, monkeypatch):
    """Seven runs leave the five newest directories."""
    _program(scratch)
    _fake_sampler(monkeypatch)
    _clock(monkeypatch)
    for _ in range(7):
        assert pr.run(scratch.root, "bench_thing") == 0
    assert _dirs(scratch) == [f"20261128-1200{n:02d}" for n in range(2, 7)]


def test_a_directory_this_module_did_not_make_is_never_deleted(scratch, monkeypatch):
    """Retention touches only names of the form YYYYMMDD-HHMMSS."""
    _program(scratch)
    _fake_sampler(monkeypatch)
    _clock(monkeypatch)
    other = scratch.root / "build/profiles/bench_thing/notes"
    other.mkdir(parents=True)
    for _ in range(6):
        assert pr.run(scratch.root, "bench_thing") == 0
    assert other.is_dir()
    assert len(_dirs(scratch)) == 6


def test_without_samply_nothing_runs_and_the_fix_is_named(scratch, monkeypatch, capsys):
    """No samply: exit 1, the fix named, nothing created."""
    _program(scratch)
    calls = _fake_sampler(monkeypatch)
    _samply(monkeypatch, None)
    assert pr.run(scratch.root, "bench_thing") == 1
    out = capsys.readouterr().out
    assert "samply is not installed." in out
    assert "Fix: brew install samply" in out
    assert not calls
    assert not (scratch.root / "build" / "profiles").exists()
    assert _records(scratch) == []


def test_a_stale_profile_build_is_refused_with_a_fix(scratch, monkeypatch, capsys):
    """A program whose profile build is out of date is not profiled."""
    binary = _program(scratch)
    calls = _fake_sampler(monkeypatch)
    (binary.parent.parent / "stale").write_text("")
    assert pr.run(scratch.root, "bench_thing") == 1
    out = capsys.readouterr().out
    assert "out of date" in out
    assert "Fix: just profile bench_thing" in out
    assert not calls
    assert _records(scratch) == []
    (binary.parent.parent / "stale").unlink()
    assert pr.run(scratch.root, "bench_thing") == 0


def test_a_failed_sampler_saves_no_record(scratch, monkeypatch, capsys):
    """A nonzero exit, or no profile file: no record, no directory, exit 1."""
    _program(scratch)
    _clock(monkeypatch)
    _fake_sampler(monkeypatch, exit_code=3)
    assert pr.run(scratch.root, "bench_thing") == 1
    assert "exit" in capsys.readouterr().out
    _fake_sampler(monkeypatch, write=False)
    assert pr.run(scratch.root, "bench_thing") == 1
    assert "no profile" in capsys.readouterr().out
    assert _records(scratch) == []
    assert _dirs(scratch) == []


def test_a_name_that_is_no_program_is_refused(scratch, monkeypatch):
    """Exit 2 for a name no group claims."""
    _program(scratch)
    _fake_sampler(monkeypatch)
    assert pr.run(scratch.root, "bench_nothing") == 2

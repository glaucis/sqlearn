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
    ],
)
def test_owner_reads_the_namespace_then_the_image(name, image, expected):
    """The namespace decides first, then the image."""
    assert pr.owner(name, image) == expected


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

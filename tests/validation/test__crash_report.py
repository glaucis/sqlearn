"""Reading a crash report: its frames named, each with whose code it is."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from validation import _crash_report as cr

REPO = Path(__file__).resolve().parents[2]
BUILD = "sqlearn 0.1, DuckDB 2.0.1 (8d78114e90), AppleClang 21, Release"

REPORT = f"""sqlearn crash report
signal: SIGSEGV (11)
fault address: 0x0
pid: 7
build: {BUILD}
This file stays on this machine: sqlearn sends nothing anywhere.
symbolise an address with atos -o <image> -l <load address> <address>
pc 0x19a6e6b44 /usr/lib/system/libsystem_platform.dylib (load address 0x19a6e6000)
stack, innermost first:
#0 0x10df03997 /x/site-packages/_duckdb.abi3.so (load address 0x10de14000)
#1 0x10 (in no image loaded when the handler was installed)
#2 0x20 (the program) (load address 0x0)
end of report
"""

MAP = """# Path: duckdb-python/_duckdb.abi3.so
# Arch: arm64
# Object files:
[  0] linker synthesized
[  1] CMakeFiles/sq_core.dir/src/core/version.cpp.o
[  2] duckdb-python/duckdb/src/libduckdb_static.a(ub_duckdb_main.cpp.o)
# Sections:
# Address\tSize    \tSegment\tSection
0x00000F60\t0x00001000\t__TEXT\t__text
# Symbols:
# Address\tSize    \tFile  Name
0x00000000\t0x00000000\t[  0] ___dso_handle
0x00000F60\t0x00000040\t[  1] __ZN2sq4core8describeERKNS0_13BuildIdentityE
0x00000FA0\t0x00000020\t[  2] __ZN6duckdb13ClientContext4LockEv
0x00002000\t0x00000038\t[  1] FDE for: __ZN2sq4core8describeERKNS0_13BuildIdentityE
# Dead Stripped Symbols:
#        \tSize    \tFile  Name
<<dead>> \t0x00000010\t[  2] __ZN6duckdb4GoneEv
"""


def test_a_report_gives_its_signal_build_and_frames():
    """Each pc and # line is a frame, with its image and load address."""
    report = cr.parse(REPORT)
    assert report.signal == "SIGSEGV"
    assert report.build == BUILD
    assert report.frames == (
        cr.Frame(
            "pc", 0x19A6E6B44, "/usr/lib/system/libsystem_platform.dylib", 0x19A6E6000
        ),
        cr.Frame("#0", 0x10DF03997, "/x/site-packages/_duckdb.abi3.so", 0x10DE14000),
        cr.Frame("#1", 0x10, None, None),
        cr.Frame("#2", 0x20, None, None),
    )


def test_the_map_finds_the_symbol_holding_an_offset():
    """A symbol holds its first byte and its last, not the one past it; the
    unwind entries (FDE) and the dead-stripped symbols are no code."""
    symbols = cr.Map(MAP)
    describe = symbols.symbol_at(0xF60)
    assert describe is not None
    assert describe.name == "__ZN2sq4core8describeERKNS0_13BuildIdentityE"
    assert describe.source == "CMakeFiles/sq_core.dir/src/core/version.cpp.o"
    assert symbols.symbol_at(0xF9F) == describe
    lock = symbols.symbol_at(0xFA0)
    assert lock is not None
    assert lock.source.endswith("libduckdb_static.a(ub_duckdb_main.cpp.o)")
    assert symbols.symbol_at(0xFC0) is None
    assert symbols.symbol_at(0xF5F) is None
    assert symbols.symbol_at(0x2000) is None
    assert [s.name for s in symbols.symbols] == [
        "__ZN2sq4core8describeERKNS0_13BuildIdentityE",
        "__ZN6duckdb13ClientContext4LockEv",
    ]


@pytest.mark.parametrize(
    ("source", "owner"),
    [
        ("CMakeFiles/sq_core.dir/src/core/version.cpp.o", "sqlearn"),
        ("CMakeFiles/sq_bindings.dir/src/bindings/module.cpp.o", "sqlearn"),
        (
            "duckdb-python/duckdb/extension/sqlearn/libsqlearn_extension.a(x.o)",
            "sqlearn",
        ),
        ("duckdb-python/duckdb/src/libduckdb_static.a(ub_duckdb_main.cpp.o)", "DuckDB"),
        ("duckdb-python/duckdb/extension/json/libjson_extension.a(x.o)", "DuckDB"),
        ("duckdb-python/src/CMakeFiles/python_src.dir/dataframe.cpp.o", "DuckDB"),
        (
            "duckdb-python/CMakeFiles/_duckdb.dir/_duckdb_static_extension_loader.cpp.o",
            "DuckDB",
        ),
        ("duckdb-python/libnanobind-static-abi3.a(common.cpp.o)", "nanobind"),
        ("third_party/cpptrace/libcpptrace.a(unwind.cpp.o)", "cpptrace"),
        ("linker synthesized", "unknown"),
    ],
)
def test_an_object_files_owner(source, owner):
    """The object a symbol came from says whose code it is."""
    assert cr.owner_of_object(source) == owner


@pytest.mark.parametrize(
    ("image", "owner"),
    [
        (
            "/u/python/cpython-3.12.13-macos-aarch64-none/lib/libpython3.12.dylib",
            "Python",
        ),
        ("/Library/Frameworks/Python.framework/Versions/3.12/Python", "Python"),
        ("/x/.venv/bin/python3", "Python"),
        ("/x/site-packages/_ctypes.cpython-312-darwin.so", "Python"),
        ("/usr/lib/system/libsystem_platform.dylib", "system"),
        ("/usr/lib/libc++.1.dylib", "system"),
    ],
)
def test_an_images_owner(image, owner):
    """An image other than the module is Python's or the system's."""
    assert cr.owner_of_image(image) == owner


def named(*frames):
    """Named frames from (label, owner, name) triples."""
    return [cr.Named(*f) for f in frames]


def test_a_fault_in_duckdb_is_duckdbs():
    """The faulting instruction in DuckDB's code: DuckDB's, with how to tell
    by reproducing it in plain DuckDB."""
    said = cr.verdict(
        named(
            ("pc", "DuckDB", "duckdb::Vector::Reference()"),
            ("#0", "sqlearn", "sq::crash::on_signal(int)"),
            ("#1", "system", "_sigtramp"),
            ("#2", "DuckDB", "duckdb::Executor::Execute()"),
        )
    )
    assert said.startswith("DuckDB's code crashed: duckdb::Vector::Reference()")
    assert "plain DuckDB" in said


def test_a_fault_in_the_system_called_from_sqlearn_is_sqlearns():
    """The nearest sqlearn or DuckDB frame outward from a system fault decides,
    the crash handler's own frames left out."""
    said = cr.verdict(
        named(
            ("pc", "system", "_platform_memmove"),
            ("#0", "sqlearn", "sq::crash::(anonymous namespace)::on_signal(int)"),
            ("#1", "cpptrace", "cpptrace::safe_generate_raw_trace()"),
            ("#2", "system", "_sigtramp"),
            ("#3", "sqlearn", "sq::raw::Buffer::fill()"),
            ("#4", "DuckDB", "duckdb::Executor::Execute()"),
        )
    )
    assert said.startswith("sqlearn's code crashed: sq::raw::Buffer::fill()")
    assert "_platform_memmove" in said


def test_a_fault_with_neither_on_the_stack_is_outside_both():
    """Only Python and the system below the handler: neither's bug."""
    said = cr.verdict(
        named(
            ("pc", "system", "_platform_strlen"),
            ("#0", "sqlearn", "sq::crash::(anonymous namespace)::on_signal(int)"),
            ("#1", "system", "_sigtramp"),
            ("#2", "Python", "PyCFuncPtr_call"),
        )
    )
    assert said.startswith("Neither sqlearn's nor DuckDB's code crashed")
    assert "_platform_strlen" in said


def _installed_build() -> str:
    from sqlearn import _native

    return _native.describe()


def test_a_report_of_another_build_is_refused(tmp_path, capsys):
    """Its addresses mean nothing in this build: refused, naming its build."""
    report = tmp_path / "report.txt"
    report.write_text(REPORT)
    assert cr.main([str(report)]) == 1
    out = capsys.readouterr().out
    assert BUILD in out
    assert _installed_build() in out
    assert "Fix:" in out


@pytest.mark.skipif(sys.platform != "darwin", reason="atos and ld64's map: macOS")
def test_a_real_crash_is_read_with_sqlearns_frames_named(tmp_path, capsys):
    """A crash after import sqlearn: its report's handler frame is sqlearn's,
    named from the map, and the crash (ctypes reading address 0) is neither
    sqlearn's nor DuckDB's."""
    if not list((REPO / "build").glob(f"*/{cr.MAP_NAME}")):
        pytest.skip("no map here yet: uv sync links the module with it")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONFAULTHANDLER",)}
    env["HOME"] = str(tmp_path)
    subprocess.run(
        [sys.executable, "-c", "import sqlearn, ctypes; ctypes.string_at(0)"],
        env=env,
        capture_output=True,
        check=False,
        timeout=60,
    )
    found = list((tmp_path / "Library" / "Logs" / "sqlearn").glob("*.txt"))
    assert len(found) == 1
    assert cr.main([str(found[0])]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    zero = next(line for line in lines if line.startswith("#0 "))
    assert "sqlearn" in zero
    assert "sq::crash::" in zero
    # The shared cache's functions, named as loaded, not from their files.
    assert re.match(r"^pc system +_platform_strlen$", lines[1]), lines[1]
    assert re.match(
        r"^#1 system +_sigtramp$", next(x for x in lines if x.startswith("#1 "))
    )
    assert any(line.startswith("#") and " Python " in line for line in lines)
    assert "Neither sqlearn's nor DuckDB's code crashed" in out


@pytest.mark.skipif(sys.platform != "darwin", reason="the reader runs on macOS")
def test_no_map_names_the_rebuild_that_writes_it(tmp_path, capsys, monkeypatch):
    """Without the module's map, sqlearn's frames cannot be named: refused,
    naming the reinstall whose link writes it."""
    report = tmp_path / "report.txt"
    report.write_text(REPORT.replace(BUILD, _installed_build()))
    monkeypatch.setattr(cr, "_the_map", lambda repo: None)
    assert cr.main([str(report)]) == 1
    out = capsys.readouterr().out
    assert cr.MAP_NAME in out
    assert "Fix: uv sync --reinstall-package sqlearn" in out

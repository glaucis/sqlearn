"""The licence check (``just check-licences``): THIRD_PARTY.md against the
wheel's build, ADR 0066's licences, and numpy's declared licence."""

import json
from importlib import metadata
from pathlib import Path

import pytest

from validation import _licences

REPO = Path(__file__).resolve().parents[2]

HEADER = """# Third-party code

## Compiled into the wheel

| Library | Version | Licence | Licence text | Compiled from |
| --- | --- | --- | --- | --- |
"""


def row(name, spdx, paths, text="LICENSE"):
    """One table row of THIRD_PARTY.md's shipped table."""
    cells = " ".join(f"`{p}`" for p in paths)
    return f"| {name} | 1.0 | {spdx} | [LICENSE]({text}) | {cells} |\n"


def scratch(tmp_path, rows, compiled, includes=(), notice=None):
    """A scratch repository: THIRD_PARTY.md of `rows`, NOTICE, a licence
    file, and a build whose compile database compiles `compiled` with the
    include directories `includes` (made, so they exist)."""
    repo = tmp_path / "repo"
    build = repo / "build" / "cpython-312"
    build.mkdir(parents=True)
    (repo / "LICENSE").write_text("licence\n")
    (repo / "THIRD_PARTY.md").write_text(
        HEADER + "".join(rows) + "\n## Development only\n"
    )
    names = [r.split("|")[1].strip() for r in rows]
    if notice is None:
        notice = "".join(f"## {n}\n\ntext\n\n" for n in names)
    (repo / "NOTICE").write_text(notice)
    for include in includes:
        (repo / include).mkdir(parents=True, exist_ok=True)
    flags = " ".join(f"-I{repo / i}" for i in includes)
    entries = [
        {
            "directory": str(build),
            "command": f"c++ {flags} -c {repo / f}",
            "file": str(repo / f),
        }
        for f in compiled
    ]
    (build / "compile_commands.json").write_text(json.dumps(entries))
    write_link(build, ["duckdb-python/libduckdb_static.a"])
    return repo


def write_link(build, inputs, objects=("duckdb-python/x.cpp.o",)):
    """Write build.ninja with _duckdb's link statement: `objects` as its
    explicit inputs, `inputs` as its LINK_LIBRARIES."""
    (build / "build.ninja").write_text(
        "rule CXX_MODULE_LIBRARY_LINKER___duckdb_Release\n"
        "  command = c++ $in -o $out $LINK_LIBRARIES\n\n"
        "build duckdb-python/_duckdb.abi3.so: "
        "CXX_MODULE_LIBRARY_LINKER___duckdb_Release "
        + " ".join(objects)
        + " | duckdb-python/libduckdb_static.a || duckdb-python/other\n"
        "  LINK_LIBRARIES = " + "  ".join(inputs) + "\n"
        "  TARGET_FILE = duckdb-python/_duckdb.abi3.so\n\n"
        "build _duckdb.abi3.so: phony duckdb-python/_duckdb.abi3.so\n"
    )


def test_a_permissive_file_passes(tmp_path):
    """Every compiled path in a row, every licence allowed: no problem."""
    repo = scratch(
        tmp_path,
        [row("fmt", "MIT", ["third_party/fmt"])],
        ["engine/src/core/a.cpp", "third_party/fmt/format.cc"],
        includes=["third_party/fmt/include"],
    )
    assert _licences.problems(repo, "MIT") == []


def test_a_gpl_row_fails(tmp_path):
    """A row under the GPL is named, with ADR 0066."""
    repo = scratch(
        tmp_path,
        [row("readline", "GPL-3.0-only", ["third_party/readline"])],
        ["third_party/readline/a.c"],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "readline" in found[0]
    assert "GPL-3.0-only" in found[0]
    assert "ADR 0066" in found[0]


def test_a_choice_takes_the_permissive_licence(tmp_path):
    """An OR with one allowed licence passes; an AND with a copyleft one fails."""
    repo = scratch(
        tmp_path,
        [
            row("mbedtls", "Apache-2.0 OR GPL-2.0-or-later", ["third_party/mbedtls"]),
            row("mixed", "(MIT AND LGPL-2.1-only)", ["third_party/mixed"]),
        ],
        ["third_party/mbedtls/a.c", "third_party/mixed/b.c"],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "mixed" in found[0]


def test_a_missing_library_fails(tmp_path):
    """A compiled file or include directory in no row is named, with its fix."""
    repo = scratch(
        tmp_path,
        [row("fmt", "MIT", ["third_party/fmt"])],
        ["third_party/fmt/format.cc", "third_party/zlib/inflate.c"],
        includes=["third_party/snappy"],
    )
    found = _licences.problems(repo, "MIT")
    assert any("third_party/zlib/inflate.c" in p for p in found)
    assert any("third_party/snappy" in p for p in found)
    assert all("Fix:" in p for p in found)


def test_a_path_outside_the_repository_matches_a_pattern(tmp_path):
    """The build environment's headers, gone after the build, still count."""
    repo = scratch(
        tmp_path,
        [row("nanobind", "BSD-3-Clause", ["*/site-packages/nanobind"])],
        ["engine/src/a.cpp"],
    )
    db = repo / "build" / "cpython-312" / "compile_commands.json"
    entries = json.loads(db.read_text())
    gone = "/gone/lib/python3.12/site-packages"
    entries[0]["command"] += f" -isystem {gone}/nanobind/include -I{gone}/other"
    db.write_text(json.dumps(entries))
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert f"{gone}/other" in found[0]


def test_a_stale_include_inside_the_repository_is_ignored(tmp_path):
    """An include directory of the repository that does not exist holds
    nothing the build could read."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    db = repo / "build" / "cpython-312" / "compile_commands.json"
    entries = json.loads(db.read_text())
    entries[0]["command"] += f" -I{repo / 'third_party/none/include'}"
    db.write_text(json.dumps(entries))
    assert _licences.problems(repo, "MIT") == []


def test_a_licence_file_that_is_not_there_fails(tmp_path):
    """A row's licence text must exist when it is a path of the repository."""
    repo = scratch(
        tmp_path,
        [row("fmt", "MIT", ["third_party/fmt"], text="third_party/fmt/LICENSE")],
        ["third_party/fmt/format.cc"],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "third_party/fmt/LICENSE" in found[0]


def test_notice_names_every_library(tmp_path):
    """NOTICE without a library's section fails."""
    repo = scratch(
        tmp_path,
        [row("fmt", "MIT", ["third_party/fmt"])],
        ["third_party/fmt/format.cc"],
        notice="## other\n",
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "NOTICE" in found[0]


def test_numpys_licence_must_be_allowed(tmp_path):
    """numpy's License-Expression is checked as a row's is."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    assert _licences.problems(repo, "BSD-3-Clause AND MIT") == []
    found = _licences.problems(repo, "BSD-3-Clause AND GPL-2.0-only")
    assert len(found) == 1
    assert "numpy" in found[0]


def test_no_build_names_the_fix(tmp_path):
    """Without the wheel's build there is nothing to check against."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "THIRD_PARTY.md").write_text(HEADER)
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "Fix: uv sync --locked" in found[0]


def test_a_foreign_archive_linked_into_duckdb_fails(tmp_path):
    """A link input not built in the build directory is named; the system's
    libraries and frameworks pass."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    build = repo / "build" / "cpython-312"
    write_link(
        build,
        [
            "duckdb-python/libduckdb_static.a",
            "/opt/homebrew/lib/libfoo.a",
            "-Wl,-force_load,/elsewhere/libbar.a",
            "-L/opt/homebrew/lib",
            "-lbaz",
            "/usr/lib/libz.dylib",
            "-framework",
            "Accelerate",
            "-ldl",
        ],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 4
    assert any("-lbaz" in p for p in found)
    assert any("/opt/homebrew/lib/libfoo.a" in p for p in found)
    assert any("/elsewhere/libbar.a" in p for p in found)
    assert any("-L/opt/homebrew/lib" in p for p in found)
    assert all("Fix:" in p for p in found)


def test_only_the_systems_libraries_are_linked_by_name(tmp_path):
    """-l names pass only for the system's own libraries."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    names = ["dl", "m", "pthread", "c", "c++", "System", "rt", "stdc++", "gcc_s"]
    write_link(repo / "build" / "cpython-312", [f"-l{n}" for n in names] + ["-lssl"])
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "-lssl" in found[0]


def test_a_name_or_directory_in_the_next_token_is_checked_alike(tmp_path):
    """``-l ssl`` and ``-L /opt/homebrew/lib``, the name or directory as the
    next token, are checked as ``-lssl`` and ``-L/opt/homebrew/lib`` are;
    ``-l dl`` passes."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    write_link(
        repo / "build" / "cpython-312",
        ["-l", "ssl", "-l", "dl", "-L", "/opt/homebrew/lib"],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 2
    assert any("-lssl" in p for p in found)
    assert any("-L/opt/homebrew/lib" in p for p in found)


def test_on_linux_only_libc_and_the_compiler_runtime_pass(tmp_path, monkeypatch):
    """Outside macOS, /usr/lib/ is not exempt as a whole: libc's and the
    compiler runtime's files are, another library there is not."""
    monkeypatch.setattr(_licences.sys, "platform", "linux")
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    write_link(
        repo / "build" / "cpython-312",
        [
            "/usr/lib/x86_64-linux-gnu/libc.so.6",
            "/lib/x86_64-linux-gnu/libm.so.6",
            "/usr/lib/gcc/x86_64-linux-gnu/14/libgcc.a",
            "/usr/lib/x86_64-linux-gnu/libssl.so.3",
        ],
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "libssl" in found[0]


def test_a_build_without_the_link_statement_fails(tmp_path):
    """No _duckdb link in build.ninja is a problem, not a pass."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    (repo / "build" / "cpython-312" / "build.ninja").write_text(
        "rule x\n  command = x\n"
    )
    found = _licences.problems(repo, "MIT")
    assert len(found) == 1
    assert "_duckdb" in found[0]


def test_a_term_allowed_for_one_row_passes_only_for_it(tmp_path):
    """ADR 0066's amendment allows Unicode-DFS-2015 for utf8proc alone, and
    0BSD and CC0-1.0 for numpy alone; anywhere else they fail."""
    repo = scratch(
        tmp_path,
        [
            row("utf8proc", "MIT AND Unicode-DFS-2015", ["third_party/utf8proc"]),
            row("fmt", "MIT AND 0BSD", ["third_party/fmt"]),
        ],
        ["third_party/utf8proc/a.c", "third_party/fmt/b.cc"],
    )
    found = _licences.problems(repo, "BSD-3-Clause AND 0BSD AND CC0-1.0")
    assert len(found) == 1
    assert "fmt" in found[0]
    assert "0BSD" in found[0]
    found = _licences.problems(repo, "MIT AND Unicode-DFS-2015")
    assert any("numpy" in p and "Unicode-DFS-2015" in p for p in found)


def test_the_terms_allowed_for_one_row_are_printed_with_it(
    tmp_path, monkeypatch, capsys
):
    """Each run prints, for each term allowed for its row alone, the row using
    it and the ADR that allows it."""
    repo = scratch(
        tmp_path,
        [row("utf8proc", "MIT AND Unicode-DFS-2015", ["third_party/utf8proc"])],
        ["third_party/utf8proc/a.c"],
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(_licences, "_numpy_expression", lambda: "BSD-3-Clause AND 0BSD")
    assert _licences.cli([]) == 0
    out = capsys.readouterr().out
    assert "Unicode-DFS-2015 passes for utf8proc, by ADR 0066" in out
    assert "0BSD passes for numpy, by ADR 0066" in out
    assert "awaiting" not in out
    assert "CC0-1.0" not in out


def test_numpy_without_a_license_expression_names_the_fix(tmp_path):
    """numpy's metadata with no License-Expression is a problem with a fix."""
    repo = scratch(tmp_path, [], ["engine/src/a.cpp"])
    found = _licences.problems(repo, None)
    assert len(found) == 1
    assert "numpy" in found[0]
    assert "Fix:" in found[0]


def test_the_spdx_expressions_evaluate():
    """AND needs every term, OR one, WITH an exception is refused."""
    allowed = _licences.allowed_expression
    assert allowed("MIT")
    assert allowed("(BSD-2-Clause OR BSL-1.0) AND Zlib")
    assert allowed("BSD-3-Clause OR GPL-2.0-only")
    assert not allowed("MIT AND GPL-2.0-only")
    assert not allowed("Apache-2.0 WITH LLVM-exception")
    assert not allowed("CC-BY-SA-4.0")
    with pytest.raises(ValueError, match="SPDX"):
        allowed("MIT AND")


def test_the_real_file_passes_against_the_wheels_build():
    """THIRD_PARTY.md, NOTICE and numpy, against the last build of the wheel
    (``uv sync`` makes it)."""
    expression = metadata.metadata("numpy")["License-Expression"]
    assert _licences.problems(REPO, expression) == []

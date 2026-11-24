"""The licence check of what the wheel compiles in (``just check-licences``).

``THIRD_PARTY.md``'s table "Compiled into the wheel" lists each library the
wheel's binary is compiled from, with its licence as an SPDX expression and
the paths its code comes from. :func:`problems` checks that table against
the wheel's last build, read from its compile database
(``build/<cache tag>/compile_commands.json``, which every configure
writes):

- every source file the build compiled, and every include directory it
  read, lies in a row's paths, in sqlearn's own code (:data:`OURS`) or in
  the system's SDK (:data:`SYSTEM`); an include directory of the
  repository that does not exist is skipped, since nothing can be read
  from it, while one outside it is kept, since the build environment's
  ``site-packages`` is gone once the build ends;
- every row's licence is one ADR 0066 allows (:data:`ALLOWED`): AND needs
  each term allowed, OR one of them, and a WITH exception is refused;
- every row's licence text, when a path, is a file of the repository, and
  ``NOTICE`` has a section (``## <library>``) for every row;
- every input of ``_duckdb``'s link, read from the build's ``build.ninja``,
  was built in the build directory or is the system's (:data:`SYSTEM_LINK`):
  the compile database lists compiled sources, never a prebuilt archive;
- numpy's ``License-Expression``, the one runtime dependency's, is allowed
  as a row's is.

A licence term in :data:`AWAITING_RULING` passes for the rows it names
alone, printed with the row on every run, until it is ruled on.
"""

import fnmatch
import json
import re
import shlex
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ALLOWED = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "PSF-2.0",
        "BSL-1.0",
        "Zlib",
        "Unicode-3.0",
        "ISC",
    }
)
"""ADR 0066's licences, as SPDX identifiers."""

NUMPY = "numpy"
"""The name :data:`AWAITING_RULING` gives numpy's own licence."""

AWAITING_RULING: dict[str, tuple[frozenset[str], str]] = {
    "Unicode-DFS-2015": (
        frozenset({"utf8proc"}),
        "utf8proc's data (utf8proc_data.c) is under Unicode's 1991-2007 terms, "
        "whose text is SPDX's Unicode-DFS-2015: a Unicode licence, as ADR 0066 "
        "allows, but not on the OSI's list nor among ADR 0066's identifiers",
    ),
    "0BSD": (
        frozenset({NUMPY}),
        "numpy declares it, for pythoncapi-compat: OSI-approved, of the BSD "
        "family, not among ADR 0066's identifiers",
    ),
    "CC0-1.0": (
        frozenset({NUMPY}),
        "numpy declares it, for Highway's random-inl.h: a public-domain "
        "dedication, not an OSI-approved licence",
    ),
}
"""Terms outside :data:`ALLOWED` that the real file meets: each with the
rows (THIRD_PARTY.md's names, or :data:`NUMPY`) it passes for and why; it
fails for any other, and is printed with its row on every run."""

SYSTEM_LINK = (
    "/usr/lib/",
    "/System/",
    "/Library/Developer/",
    "/Applications/Xcode",
)
"""Where a library linked into ``_duckdb`` may come from outside the build:
the system's and the SDK's."""

OURS = ("engine/src", "engine/extension", "<build>/headers_alone")
"""sqlearn's own code, and the headers-alone units the build generates."""

SYSTEM = (
    "/Library/Developer/",
    "/Applications/Xcode",
    "/usr/include/",
    "/usr/lib/clang/",
    "/usr/lib/gcc/",
)
"""The system's SDK and compiler headers."""

IGNORED = {
    "engine/duckdb-python/external/duckdb/third_party": (
        "duckdb-python's include path names it as the parent of the libraries "
        "listed; no file includes through it"
    ),
}
"""Include directories that are no library of their own, each with why."""

SHIPPED = "## Compiled into the wheel"
"""The heading of THIRD_PARTY.md's table the check reads."""


@dataclass(frozen=True)
class Row:
    """One library of THIRD_PARTY.md's shipped table."""

    name: str
    """The library's name."""
    spdx: str
    """Its licence, an SPDX expression."""
    text: str
    """Its licence text: a path of the repository or a URL."""
    paths: tuple[str, ...]
    """Where its code is compiled from, as :func:`_matches` reads them."""


def rows(markdown: str) -> list[Row]:
    """Return the rows of the table under :data:`SHIPPED`.

    Parameters
    ----------
    markdown : str
        THIRD_PARTY.md's text.

    Returns
    -------
    list of Row
        Its libraries, in order; none when the table is missing.
    """
    found: list[Row] = []
    inside = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            inside = line.strip() == SHIPPED
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("Library", "---"):
            continue
        link = re.search(r"\]\(([^)]+)\)", cells[3])
        found.append(
            Row(
                name=cells[0],
                spdx=cells[2],
                text=link.group(1) if link else "",
                paths=tuple(re.findall(r"`([^`]+)`", cells[4])),
            )
        )
    return found


def _tokens(expression: str) -> list[str]:
    """Split an SPDX expression into identifiers, operators and parentheses."""
    return re.findall(r"\(|\)|[^\s()]+", expression)


def _terms(expression: str) -> set[str]:
    """Return the licence identifiers an SPDX expression names."""
    return {t for t in _tokens(expression) if t not in ("(", ")", "AND", "OR", "WITH")}


def allowed_expression(expression: str, extra: frozenset[str] = frozenset()) -> bool:
    """Return whether an SPDX expression is allowed.

    Parameters
    ----------
    expression : str
        The expression, as ``(BSD-2-Clause OR BSL-1.0) AND Zlib``.
    extra : frozenset of str
        Identifiers allowed beside :data:`ALLOWED`.

    Returns
    -------
    bool
        True when every AND term has an allowed choice; a WITH exception is
        never allowed.

    Raises
    ------
    ValueError
        When the expression is not one SPDX's grammar reads.
    """
    tokens = _tokens(expression)
    permitted = ALLOWED | extra
    at = 0

    def fail() -> ValueError:
        return ValueError(f"{expression!r} is not an SPDX expression")

    def peek() -> str | None:
        return tokens[at] if at < len(tokens) else None

    def atom() -> bool:
        nonlocal at
        token = peek()
        if token is None or token in (")", "AND", "OR", "WITH"):
            raise fail()
        at += 1
        if token == "(":
            value = either()
            if peek() != ")":
                raise fail()
            at += 1
            return value
        if peek() == "WITH":
            at += 1
            if peek() in (None, "(", ")", "AND", "OR", "WITH"):
                raise fail()
            at += 1
            return False
        return token in permitted

    def both() -> bool:
        nonlocal at
        value = atom()
        while peek() == "AND":
            at += 1
            value = atom() and value
        return value

    def either() -> bool:
        nonlocal at
        value = both()
        while peek() == "OR":
            at += 1
            value = both() or value
        return value

    value = either()
    if at != len(tokens):
        raise fail()
    return value


def _include_dirs(arguments: Sequence[str]) -> Iterator[str]:
    """Yield the include directories a compile command names."""
    flags = ("-I", "-isystem", "-iquote", "-idirafter")
    it = iter(arguments)
    for argument in it:
        if argument in flags:
            following = next(it, None)
            if following is not None:
                yield following
        elif argument.startswith("-I") and len(argument) > 2:
            yield argument[2:]


def _place(path: Path, repo: Path, build: Path) -> str:
    """Return `path` as the rows name it: ``<build>/...`` inside the build,
    repository-relative inside the repository, absolute elsewhere."""
    if path.is_relative_to(build):
        return "<build>/" + path.relative_to(build).as_posix()
    if path.is_relative_to(repo):
        return path.relative_to(repo).as_posix()
    return path.as_posix()


def compiled(build: Path, repo: Path) -> set[str]:
    """Return every source file and include directory of a build.

    Parameters
    ----------
    build : Path
        The build directory, holding ``compile_commands.json``.
    repo : Path
        The repository.

    Returns
    -------
    set of str
        Each as :func:`_place` gives it; an include directory of the
        repository that does not exist is left out.
    """
    resolved_repo = repo.resolve()
    resolved_build = build.resolve()
    found: set[str] = set()
    for entry in json.loads((build / "compile_commands.json").read_text()):
        directory = Path(entry["directory"])
        arguments = entry.get("arguments") or shlex.split(entry["command"])
        source = (directory / entry["file"]).resolve()
        found.add(_place(source, resolved_repo, resolved_build))
        for include in _include_dirs(arguments):
            path = (directory / include).resolve()
            if path.is_relative_to(resolved_repo) and not path.is_dir():
                continue
            found.add(_place(path, resolved_repo, resolved_build))
    return found


def _matches(path: str, pattern: str) -> bool:
    """Return whether `path` is `pattern` or lies under it; a pattern holding
    ``*`` is matched with fnmatch, its ``*`` crossing ``/``."""
    if "*" in pattern:
        return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(
            path, pattern + "/*"
        )
    return path == pattern or path.startswith(pattern + "/")


def owner(path: str, table: Sequence[Row]) -> Row | None:
    """Return the row whose most specific path holds `path`, or None."""
    best: tuple[int, Row] | None = None
    for row in table:
        for pattern in row.paths:
            if _matches(path, pattern) and (best is None or len(pattern) > best[0]):
                best = (len(pattern), row)
    return best[1] if best else None


def _builds(repo: Path) -> list[Path]:
    """Return the wheel's build directories (``build/<cache tag>``)."""
    return sorted(p.parent for p in (repo / "build").glob("*/compile_commands.json"))


def _awaiting(name: str) -> frozenset[str]:
    """Return the terms awaiting a ruling that pass for the row `name`."""
    return frozenset(t for t, (names, _) in AWAITING_RULING.items() if name in names)


def _licence_problem(what: str, name: str, expression: str) -> str | None:
    """Return the problem with `what`'s licence, or None when it is allowed;
    `name` is the row the terms of :data:`AWAITING_RULING` are scoped to."""
    extra = _awaiting(name)
    try:
        if allowed_expression(expression, extra):
            return None
    except ValueError as error:
        return f"{what}: {error}.\nFix: write its licence as an SPDX expression"
    refused = sorted(_terms(expression) - ALLOWED - extra)
    return (
        f"{what} is under {expression}, and "
        f"{', '.join(refused) or 'its WITH exception'} is not a licence "
        "ADR 0066 allows (permissive and OSI-approved, never copyleft).\n"
        "Fix: leave the library out of the build, or take the permissive "
        "licence it offers"
    )


def _link_statement(build: Path) -> str | None:
    """Return the text of ``_duckdb``'s link statement in ``build.ninja``,
    its continued lines joined and its variables after it; None when there
    is none."""
    ninja = build / "build.ninja"
    if not ninja.is_file():
        return None
    text = ninja.read_text(encoding="utf-8").replace("$\n", " ")
    lines = text.splitlines()
    for at, line in enumerate(lines):
        head = re.match(r"build ([^:]*?_duckdb[^ :]*\.(?:so|pyd)): (\S+)", line)
        if not head or head.group(2) == "phony":
            continue
        body = [line]
        for following in lines[at + 1 :]:
            if not following.startswith("  "):
                break
            body.append(following)
        return "\n".join(body)
    return None


def link_inputs(build: Path) -> list[str] | None:
    """Return the inputs of ``_duckdb``'s link: its explicit inputs and its
    LINK_LIBRARIES, as the linker gets them; None when ``build.ninja`` has
    no such link.

    Parameters
    ----------
    build : Path
        The build directory.

    Returns
    -------
    list of str or None
        The objects, archives, libraries and flags.
    """
    statement = _link_statement(build)
    if statement is None:
        return None
    first, *variables = statement.splitlines()
    # After the rule: the explicit inputs, which reach the linker, until
    # ninja's | (implicit) and || (order-only) dependencies, which do not.
    inputs: list[str] = []
    for token in first.split(":", 1)[1].split()[1:]:
        if token in ("|", "||"):
            break
        inputs.append(token)
    for variable in variables:
        name, _, value = variable.strip().partition(" = ")
        if name == "LINK_LIBRARIES":
            inputs += shlex.split(value)
    return inputs


def _system_link(path: str) -> bool:
    """Return whether an absolute path is the system's or the SDK's."""
    return path.startswith(SYSTEM_LINK)


def foreign_links(build: Path) -> list[str]:
    """Return the link inputs of ``_duckdb`` not built in `build` and not
    the system's, each as the link names it.

    Parameters
    ----------
    build : Path
        The build directory.

    Returns
    -------
    list of str
        An archive or library outside the build, or a search directory
        (``-L``, ``-F``) outside it; ``-l`` and ``-framework`` names are the
        system's when no such directory is given.
    """
    inside = build.resolve()
    foreign: list[str] = []

    def check(path: str, shown: str) -> None:
        resolved = (build / path).resolve()
        if not resolved.is_relative_to(inside) and not _system_link(
            resolved.as_posix()
        ):
            foreign.append(shown)

    inputs = link_inputs(build) or []
    for token in inputs:
        if token.startswith("-Wl,"):
            for part in token.split(",")[1:]:
                if "/" in part:
                    check(part, part)
        elif token.startswith(("-L", "-F")) and len(token) > 2:
            check(token[2:], token)
        elif token.startswith("-") or (
            "/" not in token and not token.endswith((".a", ".o", ".so", ".dylib"))
        ):
            continue
        else:
            check(token, token)
    return foreign


def problems(repo: Path, numpy_expression: str | None) -> list[str]:
    """Return every problem of THIRD_PARTY.md and NOTICE, one message each.

    Parameters
    ----------
    repo : Path
        The repository: its THIRD_PARTY.md, NOTICE and ``build/``.
    numpy_expression : str or None
        numpy's ``License-Expression``; None when its metadata has none.

    Returns
    -------
    list of str
        Each with a ``Fix:`` line; empty when all is well.
    """
    table = rows((repo / "THIRD_PARTY.md").read_text(encoding="utf-8"))
    found: list[str] = []
    builds = _builds(repo)
    if not builds:
        return [
            "No build of the wheel to check THIRD_PARTY.md against "
            "(no build/<cache tag>/compile_commands.json).\n"
            "Fix: uv sync --locked, which builds and installs the wheel"
        ]
    for row in table:
        problem = _licence_problem(row.name, row.name, row.spdx)
        if problem:
            found.append(problem)
        if (
            row.text
            and not re.match(r"https?://", row.text)
            and not (repo / row.text).is_file()
        ):
            found.append(
                f"{row.name}'s licence text {row.text} is not a file of the "
                "repository.\nFix: link the licence file in its submodule, or its "
                "URL at the pinned tag"
            )
    notice_path = repo / "NOTICE"
    notice = notice_path.read_text(encoding="utf-8") if notice_path.is_file() else ""
    sections = {
        line[3:].strip() for line in notice.splitlines() if line.startswith("## ")
    }
    for row in table:
        if row.name not in sections:
            found.append(
                f"NOTICE has no section for {row.name}.\n"
                f"Fix: add '## {row.name}' to NOTICE with its licence text and notices"
            )
    for build in builds:
        for path in sorted(compiled(build, repo)):
            if (
                any(_matches(path, p) for p in OURS)
                or path.startswith(SYSTEM)
                or path in IGNORED
                or owner(path, table)
            ):
                continue
            found.append(
                f"{path} is compiled into the wheel ({build.name}) but lies in no "
                "library of THIRD_PARTY.md.\n"
                "Fix: add its library's row (version, licence, licence text, path) "
                "to THIRD_PARTY.md and its section to NOTICE"
            )
        if link_inputs(build) is None:
            found.append(
                f"{build.name}/build.ninja has no link of _duckdb, so what it "
                "links cannot be checked.\nFix: uv sync --locked, which configures "
                "and builds the wheel"
            )
        for link in foreign_links(build):
            found.append(
                f"{link} is linked into _duckdb ({build.name}) but was not built "
                "from the submodules in the build directory, nor is it the "
                "system's.\nFix: build the library from a submodule, or leave it "
                "out of the link"
            )
    if numpy_expression is None:
        found.append(
            "numpy (the runtime dependency) declares no License-Expression in "
            "its metadata, so its licence cannot be checked.\nFix: pin a numpy "
            "whose metadata declares one (numpy 2.3 and later do)"
        )
    else:
        problem = _licence_problem(
            "numpy (the runtime dependency)", NUMPY, numpy_expression
        )
        if problem:
            found.append(problem)
    return found


def _numpy_expression() -> str | None:
    """Return numpy's ``License-Expression``, or None when it has none."""
    return metadata.metadata("numpy").get("License-Expression")


def awaiting_uses(table: Sequence[Row], numpy_expression: str | None) -> list[str]:
    """Return a line for each use of a term awaiting a ruling: the term,
    the row using it, and why it is there.

    Parameters
    ----------
    table : sequence of Row
        THIRD_PARTY.md's rows.
    numpy_expression : str or None
        numpy's ``License-Expression``.

    Returns
    -------
    list of str
        One line per term and row, for the terms that row may use.
    """
    uses = [(row.name, row.spdx) for row in table]
    if numpy_expression is not None:
        uses.append((NUMPY, numpy_expression))
    lines = []
    for name, expression in uses:
        for term in sorted(_terms(expression) & _awaiting(name)):
            reason = AWAITING_RULING[term][1]
            lines.append(
                f"licences: {term} passes for {name}, awaiting a ruling: {reason}"
            )
    return lines


def cli(argv: Sequence[str]) -> int:
    """Check the repository the current directory is in; print each problem.

    Parameters
    ----------
    argv : sequence of str
        Unused; the check takes no arguments.

    Returns
    -------
    int
        0 when there is no problem, else 1.
    """
    del argv
    repo = Path.cwd()
    expression = _numpy_expression()
    table = rows((repo / "THIRD_PARTY.md").read_text(encoding="utf-8"))
    for line in awaiting_uses(table, expression):
        print(line)  # noqa: T201
    found = problems(repo, expression)
    for problem in found:
        print(problem, file=sys.stderr)  # noqa: T201
    if found:
        return 1
    print(  # noqa: T201
        f"licences: {len(table)} libraries compiled in, each listed, each "
        "allowed; _duckdb links nothing from outside its build"
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))

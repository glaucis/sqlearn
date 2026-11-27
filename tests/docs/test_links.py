"""Every relative link in the tracked Markdown, and every `related:` path in
its frontmatter, names a file that exists."""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SKIPPED = ("engine/duckdb-python/", "engine/third_party/", "old_python/")
"""Trees whose Markdown is not ours to keep: others' sources, the old Python."""

LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)[^)]*\)")
"""An inline link or image; its target is group 1."""

DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
"""A reference definition, ``[name]: target``; its target is group 1."""

SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
"""A target with a scheme (``https:``, ``mailto:``) is not a file."""


def markdown(root: Path) -> list[str]:
    """Return the Markdown files under `root`, as paths from it, sorted.

    The files git tracks, or every ``*.md`` when `root` is not a repository.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.split("\0")
    except subprocess.CalledProcessError:
        listed = [p.relative_to(root).as_posix() for p in root.rglob("*.md")]
    return sorted(
        p for p in listed if p and not p.startswith(SKIPPED) and (root / p).is_file()
    )


def _prose(text: str) -> list[tuple[int, str]]:
    """Return each line, numbered from 1, with code blanked out.

    Fenced code goes whole; inline code goes too, even where a span runs
    over a line break (never over a blank line), its line breaks kept.
    """
    kept = []
    fence = None
    for line in text.splitlines():
        opened = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence is None and opened:
            fence = opened.group(1)
            kept.append("")
        elif fence is not None:
            if line.strip().startswith(fence):
                fence = None
            kept.append("")
        else:
            kept.append(line)
    prose = re.sub(
        r"(`+)(?:(?!\n\s*\n).)*?\1",
        lambda span: "\n" * span.group(0).count("\n"),
        "\n".join(kept),
        flags=re.S,
    )
    return list(enumerate(prose.split("\n"), 1))


def _resolves(root: Path, source: str, target: str) -> bool:
    """Return whether a link `target` written in `source` names a file."""
    path = target.strip("<>").split("#", 1)[0]
    if not path:
        return True
    base = root if path.startswith("/") else (root / source).parent
    return (base / path.lstrip("/")).exists()


def broken_links(root: Path) -> list[str]:
    """Return each relative link that names no file, as ``file:line: target``.

    Links with a scheme and bare ``#anchor`` links are skipped; an anchor is
    cut off before the file is looked for. Code, fenced or inline, holds no
    links.
    """
    broken = []
    for source in markdown(root):
        for number, line in _prose((root / source).read_text()):
            targets = [m.group(1) for m in LINK.finditer(line)]
            targets += [m.group(1) for m in DEFINITION.finditer(line)]
            broken.extend(
                f"{source}:{number}: {target}"
                for target in targets
                if not SCHEME.match(target.strip("<>"))
                and not _resolves(root, source, target)
            )
    return broken


def _related(text: str) -> list[tuple[int, str]]:
    """Return each ``related:`` entry of the frontmatter, with its line."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    entries: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            break
        found = re.match(r"^related:\s*(.*)$", line)
        if found:
            value = found.group(1).strip()
            inside = not value
            if value.startswith("["):
                entries += [
                    (number, e.strip().strip("'\""))
                    for e in value.strip("[]").split(",")
                    if e.strip()
                ]
        elif inside and re.match(r"^\s*-\s+", line):
            entries.append((number, re.sub(r"^\s*-\s+", "", line).strip("'\" ")))
        elif inside:
            inside = False
    return entries


def missing_related(root: Path) -> list[str]:
    """Return each ``related:`` path that names no file, as ``file:line: path``.

    A ``related:`` entry is a path from the repository's root.
    """
    return [
        f"{source}:{number}: {entry}"
        for source in markdown(root)
        for number, entry in _related((root / source).read_text())
        if not (root / entry).exists()
    ]


def test_every_relative_link_resolves():
    """A relative link in any tracked Markdown file names a file that exists."""
    assert broken_links(REPO) == []


def test_every_related_path_exists():
    """Every path in a file's `related:` frontmatter exists."""
    assert missing_related(REPO) == []


def test_a_broken_link_is_found(tmp_path):
    """The check finds a link to a missing file, with its line."""
    (tmp_path / "a.md").write_text("See [b](b.md).\n")
    assert broken_links(tmp_path) == ["a.md:1: b.md"]

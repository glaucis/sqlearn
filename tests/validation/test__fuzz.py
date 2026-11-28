"""The fuzz corpus's cap: at most 500 files and 1 MiB per target."""

import re
import subprocess
from pathlib import Path

from validation import _fuzz

REPO = Path(__file__).resolve().parents[2]


def _corpus(tmp_path: Path, files: int, size: int) -> Path:
    """Make a corpus of `files` inputs of `size` bytes each."""
    corpus = tmp_path / "engine" / "fuzz" / "corpus" / "parse_version"
    corpus.mkdir(parents=True)
    for i in range(files):
        (corpus / f"input-{i:04d}").write_bytes(b"7" * size)
    return corpus


def test_a_corpus_at_the_cap_keeps_it(tmp_path):
    """500 files of 2,097 bytes, 1,048,500 bytes in all: within both limits."""
    corpus = _corpus(tmp_path, 500, 2097)
    assert _fuzz.problems(corpus) == []


def test_one_file_over_the_cap_breaks_it(tmp_path):
    """501 files: the problem names the target, the count and the fix."""
    corpus = _corpus(tmp_path, 501, 1)
    found = _fuzz.problems(corpus)
    assert len(found) == 1
    assert "parse_version" in found[0]
    assert "501 files" in found[0]
    assert "at most 500" in found[0]
    assert "Fix:" in found[0]
    assert "-merge=1" in found[0]


def test_one_byte_over_the_cap_breaks_it(tmp_path):
    """1,048,577 bytes in all (two files): the problem names the bytes."""
    corpus = _corpus(tmp_path, 1, 1_048_576)
    (corpus / "one-more").write_bytes(b"7")
    found = _fuzz.problems(corpus)
    assert len(found) == 1
    assert "1048577 bytes" in found[0]
    assert "at most 1048576" in found[0]


def test_main_fails_naming_each_corpus_over_the_cap(tmp_path, capsys):
    """main checks every directory it is given and fails when one breaks the
    cap, printing its problem."""
    over = _corpus(tmp_path, 501, 1)
    assert _fuzz.main([str(over)]) == 1
    assert "501 files" in capsys.readouterr().out
    assert _fuzz.main([]) == 0


def test_the_fuzz_recipe_passes_max_len_and_checks_the_cap():
    """`just fuzz` gives libFuzzer -max_len=MAX_LEN, on the fuzzing run and on
    the merge, and checks each target's corpus after its merge."""
    shown = subprocess.run(
        ["just", "--justfile", str(REPO / "justfile"), "--show", "fuzz"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    runs = [line for line in shown.splitlines() if '"$binary"' in line]
    assert len(runs) == 2, runs
    for line in runs:
        assert f"-max_len={_fuzz.MAX_LEN}" in line, line
    merge = next(i for i, line in enumerate(shown.splitlines()) if "-merge=1" in line)
    after = shown.splitlines()[merge + 1 :]
    assert any(re.search(r"python -m validation\._fuzz .*\$corpus", x) for x in after)


def test_the_committed_corpus_keeps_the_cap():
    """Every target's committed corpus is within the cap today."""
    targets = sorted((REPO / "engine" / "fuzz" / "corpus").iterdir())
    assert targets
    for corpus in targets:
        assert _fuzz.problems(corpus) == [], corpus

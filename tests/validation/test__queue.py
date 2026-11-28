"""The queue: due benchmarks and profiles run in turn on an idle machine.

``_bench.due``, ``_bench.run``, ``_profile.run``, the waits and
``shutil.which`` are replaced by fakes that record their calls, so nothing
sleeps, runs samply or times anything.
"""

from pathlib import Path
from typing import cast

import pytest

from validation import _bench, _checks, _load, _profile, _queue


def _due(name: str, kind: str = "bench") -> _bench.Due:
    return _bench.Due(name, "", None, None, None, kind)


class Fakes:
    """What the queue called, and what the fakes answer."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, str]] = []
        self.codes: dict[tuple[str, str], int] = {}
        self.first_waits: list[bool] = []
        self.later_waits: list[bool] = []
        self.later_args: list[tuple[float, float]] = []

    def first(self) -> bool:
        """Answer the first wait."""
        self.calls.append(("wait", "first"))
        return self.first_waits.pop(0) if self.first_waits else True

    def later(self, limit: float = 300, every: float = 30) -> bool:
        """Answer a later wait."""
        self.later_args.append((limit, every))
        self.calls.append(("wait", "later"))
        return self.later_waits.pop(0) if self.later_waits else True


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    """Replace the benchmark, the profile, the load and samply's lookup."""
    fake = Fakes(tmp_path)
    monkeypatch.setattr(_checks, "record_dir", lambda root: tmp_path / "records")
    monkeypatch.setattr(_queue.shutil, "which", lambda name: "/bin/samply")
    monkeypatch.setattr(_load, "now", lambda: 7.5)
    monkeypatch.setattr(_load, "threshold", lambda cores: 2.0)

    def bench_run(root, name):
        fake.calls.append(("bench", name))
        code = fake.codes.get(("bench", name), 0)
        if code == 0:
            _checks.save(
                tmp_path / "records",
                f"bench-{name}",
                cast(
                    "_checks.Record",
                    {
                        "digest": "d",
                        "config": name,
                        "files": {},
                        "seconds": 3.5,
                        "uptime_before": "1.00",
                        "uptime_after": "1.10",
                        "loaded": True,
                    },
                ),
            )
        return code

    def profile_run(root, name):
        fake.calls.append(("profile", name))
        code = fake.codes.get(("profile", name), 0)
        if code == 0:
            run_dir = tmp_path / "build" / "profiles" / name / "20260101-000000"
            run_dir.mkdir(parents=True)
            _checks.save(
                tmp_path / "records",
                f"profile-{name}",
                cast(
                    "_checks.Record",
                    {
                        "digest": "d",
                        "config": name,
                        "files": {},
                        "seconds": 12.5,
                        "uptime_before": "0.40",
                        "uptime_after": "0.60",
                        "loaded": False,
                        "summary": str(
                            (run_dir / "summary.json").relative_to(tmp_path)
                        ),
                    },
                ),
            )
        return code

    monkeypatch.setattr(_bench, "run", bench_run)
    monkeypatch.setattr(_profile, "run", profile_run)
    return fake


def _set_due(monkeypatch, items):
    monkeypatch.setattr(_bench, "due", lambda root: list(items))


def _run(fakes) -> int:
    return _queue.run(fakes.root, wait=fakes.first, later_wait=fakes.later)


def test_the_queue_runs_a_benchmark_then_its_profile(fakes, monkeypatch, capsys):
    """A name's benchmark runs, then its profile, before the next name."""
    _set_due(
        monkeypatch, [_due("bench_a"), _due("bench_b"), _due("bench_a", "profile")]
    )
    assert _run(fakes) == 0
    assert [c for c in fakes.calls if c[0] != "wait"] == [
        ("bench", "bench_a"),
        ("profile", "bench_a"),
        ("bench", "bench_b"),
    ]
    out = capsys.readouterr().out
    assert "ran" in out
    assert "12.5 s" in out
    assert "0.40 before, 0.60 after" in out
    assert "3.5 s, load 1.00 before, 1.10 after (machine loaded" in out
    assert "build/profiles/bench_a/20260101-000000/compare.md" in out


def test_an_item_due_alone_runs_alone(fakes, monkeypatch):
    """A profile due without its benchmark runs by itself."""
    _set_due(monkeypatch, [_due("bench_a", "profile")])
    assert _run(fakes) == 0
    assert [c for c in fakes.calls if c[0] != "wait"] == [("profile", "bench_a")]


def test_the_queue_waits_before_each_later_item_and_stops_when_the_load_stays_up(
    fakes, monkeypatch, capsys
):
    """The queue stops at the first later item the load does not release."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_b"), _due("bench_c")])
    fakes.later_waits = [False]
    assert _run(fakes) == 1
    assert [c for c in fakes.calls if c[0] != "wait"] == [("bench", "bench_a")]
    assert fakes.later_args == [(300, 30)]
    out = capsys.readouterr().out
    assert "bench_a" in out
    assert "not run" in out
    assert "bench_b" in out
    assert "bench_c" in out


def test_a_machine_never_idle_runs_nothing_and_says_the_load(
    fakes, monkeypatch, capsys
):
    """A machine never idle runs nothing and exits 3 with the load."""
    _set_due(monkeypatch, [_due("bench_a")])
    fakes.first_waits = [False]
    assert _run(fakes) == 3
    assert [c for c in fakes.calls if c[0] != "wait"] == []
    out = capsys.readouterr().out
    assert "7.5" in out
    assert "2.0" in out


def test_a_failed_item_is_reported_and_the_queue_goes_on(fakes, monkeypatch, capsys):
    """A failed item is reported and the next one runs."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_b")])
    fakes.codes[("bench", "bench_a")] = 4
    assert _run(fakes) == 1
    assert [c for c in fakes.calls if c[0] != "wait"] == [
        ("bench", "bench_a"),
        ("bench", "bench_b"),
    ]
    out = capsys.readouterr().out
    assert "failed (exit 4)" in out


def test_nothing_due_runs_nothing(fakes, monkeypatch, capsys):
    """With nothing due the queue says so and exits 0."""
    _set_due(monkeypatch, [])
    assert _run(fakes) == 0
    assert fakes.calls == []
    assert "nothing is due" in capsys.readouterr().out


def test_a_due_profile_without_samply_runs_nothing(fakes, monkeypatch, capsys):
    """A due profile with samply missing stops everything with a Fix line."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_a", "profile")])
    monkeypatch.setattr(_queue.shutil, "which", lambda name: None)
    assert _run(fakes) == 1
    assert fakes.calls == []
    out = capsys.readouterr().out
    assert "samply is not installed." in out
    assert "Fix: brew install samply" in out


def test_the_presets_are_what_the_due_items_need(fakes, monkeypatch, capsys):
    """The presets are release for a program and profile for a profile."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_a", "profile")])
    assert _queue.cli(["presets"], fakes.root) == 0
    assert capsys.readouterr().out.split() == ["release", "profile"]


def test_a_page_script_needs_no_preset(fakes, monkeypatch, capsys):
    """A page script is due without needing a build."""
    _set_due(monkeypatch, [_due("explore_scale")])
    assert _queue.cli(["presets"], fakes.root) == 0
    assert capsys.readouterr().out == ""


def test_the_cli_runs_the_queue(fakes, monkeypatch, capsys):
    """The command line runs the queue and refuses an unknown argument."""
    _set_due(monkeypatch, [])
    assert _queue.cli(["run"], fakes.root) == 0
    assert "nothing is due" in capsys.readouterr().out
    assert _queue.cli(["bogus"], fakes.root) == 2


def test_an_unreadable_manifest_stops_the_presets_on_stderr(fakes, monkeypatch, capsys):
    """The presets say why on stderr and exit 1, so the recipe stops."""

    def broken(root):
        raise _queue._groups.Unreadable("no manifest")

    monkeypatch.setattr(_bench, "due", broken)
    assert _queue.cli(["presets"], fakes.root) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no manifest" in captured.err


def test_an_unreadable_item_is_reported_and_the_queue_goes_on(
    fakes, monkeypatch, capsys
):
    """A manifest that cannot be read fails one item, not the report."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_b")])
    run_a = _bench.run

    def broken(root, name):
        if name == "bench_a":
            raise _queue._groups.Unreadable("no manifest")
        return run_a(root, name)

    monkeypatch.setattr(_bench, "run", broken)
    assert _run(fakes) == 1
    out = capsys.readouterr().out
    assert "no manifest" in out
    assert "failed" in out
    assert "Queue report:" in out
    assert ("bench", "bench_b") in fakes.calls


def test_the_presets_stop_when_a_profile_is_due_and_samply_is_missing(
    fakes, monkeypatch, capsys
):
    """No samply with a profile due: exit 1 and the fix, so nothing is built."""
    _set_due(monkeypatch, [_due("bench_a"), _due("bench_a", "profile")])
    monkeypatch.setattr(_queue.shutil, "which", lambda name: None)
    assert _queue.cli(["presets"], fakes.root) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "samply is not installed." in captured.err
    assert "Fix: brew install samply" in captured.err

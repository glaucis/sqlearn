"""Whether the machine is idle, and waiting for it, with the load patched."""

from validation import _load


def test_idle_is_a_load_below_a_quarter_of_the_cores(monkeypatch):
    """A load under cores / 4 is idle; one at the threshold is not."""
    assert _load.threshold(8) == 2.0
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: 1.9)
    assert _load.idle()
    monkeypatch.setattr(_load, "now", lambda: 2.0)
    assert not _load.idle()


def test_wait_for_idle_returns_once_the_load_drops(monkeypatch):
    """The wait ends as soon as the load is idle, sleeping `every` between looks."""
    loads = iter([5.0, 5.0, 1.0])
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: next(loads))
    slept: list[float] = []
    assert _load.wait_for_idle(sleep=slept.append)
    assert slept == [30, 30]


def test_wait_for_idle_gives_up_at_its_limit(monkeypatch):
    """A machine that stays busy is given up on after `limit` seconds."""
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: 5.0)
    slept: list[float] = []
    assert not _load.wait_for_idle(limit=90, sleep=slept.append)
    assert sum(slept) == 90

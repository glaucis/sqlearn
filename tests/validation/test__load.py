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


def test_a_short_run_is_discounted_by_the_share_of_the_minute_it_filled(monkeypatch):
    """The 1-minute load holds a run of `wall` seconds as cores * (1 - e^(-wall/60))."""
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: 3.0)
    # 2 s on 8 cores adds about 0.26: 2.74 is at or above 2.0.
    assert _load.loaded_after(8.0, 2.0)


def test_a_long_run_is_discounted_by_most_of_its_cores(monkeypatch):
    """120 s on 4 cores adds about 3.46: 5.0 less that is 1.54, under 2.0."""
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: 5.0)
    assert not _load.loaded_after(4.0, 120.0)
    assert _load.loaded_after(1.0, 120.0)


def test_wait_for_idle_defaults_to_thirty_minutes_every_thirty_seconds(monkeypatch):
    """The defaults are 1800 s and 30 s."""
    monkeypatch.setattr(_load.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(_load, "now", lambda: 5.0)
    slept: list[float] = []
    assert not _load.wait_for_idle(sleep=slept.append)
    assert sum(slept) == 1800
    assert set(slept) == {30}

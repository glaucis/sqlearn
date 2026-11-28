"""Whether the machine is idle, and waiting for it.

A benchmark measured on a busy machine says little (ADR 0072), so a run
records whether the machine was idle when it started and when it ended
(less its own load), and the queue waits for idle before it starts. Idle is
a 1-minute load average below a quarter of the cores.
"""

import math
import os
import time
from collections.abc import Callable


def threshold(cores: int) -> float:
    """Return the load below which a machine of `cores` cores is idle.

    Parameters
    ----------
    cores : int
        The number of cores.

    Returns
    -------
    float
        A quarter of `cores`.
    """
    return cores / 4


def now() -> float:
    """Return the 1-minute load average (the seam the tests patch).

    Returns
    -------
    float
        The load of the last minute.
    """
    return os.getloadavg()[0]


def idle() -> bool:
    """Return whether the load is below the threshold for this machine's cores.

    Returns
    -------
    bool
        True when `now` is under ``threshold(os.cpu_count() or 1)``.
    """
    return now() < threshold(os.cpu_count() or 1)


def loaded_after(own_cores: float, wall: float) -> bool:
    """Return whether a run ended on a busy machine, discounting its own load.

    The 1-minute load average takes in a run of `wall` seconds on `own_cores`
    cores as only about ``own_cores * (1 - exp(-wall / 60))``, so that much
    is taken off before the load is compared with the threshold.

    Parameters
    ----------
    own_cores : float
        The cores the run used: user plus system time over the wall time.
    wall : float
        The run's wall time, in seconds.

    Returns
    -------
    bool
        True when ``now()`` less the run's own share of it is at or above
        ``threshold(os.cpu_count() or 1)``.
    """
    own = own_cores * (1 - math.exp(-wall / 60))
    return now() - own >= threshold(os.cpu_count() or 1)


def wait_for_idle(
    limit: float = 1800,
    every: float = 30,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait until the machine is idle, for at most `limit` seconds.

    Parameters
    ----------
    limit : float
        The most seconds to wait.
    every : float
        Seconds between two looks at the load.
    sleep : callable
        Called with the seconds to sleep; tests pass a recorder.

    Returns
    -------
    bool
        True as soon as the machine is idle; False after `limit` seconds.
    """
    waited = 0.0
    while not idle():
        if waited >= limit:
            return False
        step = min(every, limit - waited)
        sleep(step)
        waited += step
    return True

"""Look at a dataset: counts, shapes and gaps, answered now as relations.

Examples
--------
>>> import sqlearn as sq
>>> sq.explore.profile.__name__
'profile'
"""

from sqlearn.explore.histogram import histogram
from sqlearn.explore.missing import missing
from sqlearn.explore.profile import profile
from sqlearn.explore.top import top

__all__ = ["histogram", "missing", "profile", "top"]

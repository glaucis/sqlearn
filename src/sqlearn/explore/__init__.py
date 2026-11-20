"""Look at a dataset: counts, shapes and gaps, answered now as relations.

Examples
--------
>>> import sqlearn as sq
>>> sq.explore.profile.__name__
'profile'
"""

from sqlearn.explore.histogram import histogram
from sqlearn.explore.profile import profile

__all__ = ["histogram", "profile"]

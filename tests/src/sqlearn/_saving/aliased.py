"""A package a user might allow, which happens to import a sqlearn class.

A saved file names ``tests.src.sqlearn._saving.aliased:KeptFolds``: the path
starts outside sqlearn, but the class is sqlearn's own.
"""

from sqlearn.model_selection.kept import KeptFolds

__all__ = ["KeptFolds"]

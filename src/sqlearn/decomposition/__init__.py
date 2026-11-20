"""Decomposition: project the columns on fewer that keep what they share.

Examples
--------
>>> from sqlearn.decomposition import PCA
>>> PCA(n_components=2).n_components
2
"""

from sqlearn.decomposition.pca import PCA

__all__ = ["PCA"]

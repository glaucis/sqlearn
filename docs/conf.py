"""Sphinx configuration for the sqlearn site."""

import logging

import sqlearn

project = "sqlearn"
author = "Tomas Pecukevicius"
copyright = "2026, Tomas Pecukevicius"
release = version = sqlearn.__version__
language = "en"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "numpydoc",
    "sphinx_gallery.gen_gallery",
    "myst_nb",
    "sphinxcontrib.bibtex",
]

# Every cross-reference resolves, from the first build.
nitpicky = True
# In docs/ but not on the site: specs, plans, open questions and the agents'
# configuration; the folders' one-line READMEs; the build output; and
# notebooks, which are generated, since lessons are stored as text.
exclude_patterns = [
    "_build",
    "specs",
    "plans",
    "questions",
    "agents",
    "**/README.md",
    "**.ipynb",
]

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_theme_options = {
    "header_links_before_dropdown": 7,
    "switcher": {"json_url": "_static/switcher.json", "version_match": "dev"},
    "check_switcher": False,
    "show_version_warning_banner": False,
}

autosummary_generate = True
numpydoc_show_class_members = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", "_inventories/python.inv"),
    "duckdb": (
        "https://duckdb.org/docs/2.0/clients/python/reference/",
        "_inventories/duckdb.inv",
    ),
}

# mathjax_path and mathjax4_config point at the local copy, §11.3.

sphinx_gallery_conf = {
    "examples_dirs": "../examples",
    "gallery_dirs": "examples",
    "filename_pattern": ".",
    "doc_module": ("sqlearn",),
    "backreferences_dir": "reference/generated/backreferences",
    "image_scrapers": (),
    "reset_modules": (),
    "write_computation_times": False,
}

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence"]
nb_execution_mode = "cache"
nb_execution_raise_on_error = True

bibtex_bibfiles = ["references.bib"]


# Pages on the site link to folders that are not on it (specs, questions,
# agents), so MyST cannot resolve those links. Drop exactly those warnings and
# keep every other unresolved MyST link an error.
_OFF_SITE = ("specs/", "questions/", "agents/")


class _OffSiteLinks(logging.Filter):
    """Reject MyST's unresolved-link warnings that name an off-site folder."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "subtype", None) != "xref_missing":
            return True
        return not any(
            f"'{folder}" in record.getMessage() for folder in _OFF_SITE
        ) and ("'../agents/'" not in record.getMessage())


def setup(app) -> None:
    """Install the filter on Sphinx's warning handlers."""

    def install(_app) -> None:
        for handler in logging.getLogger("sphinx").handlers:
            handler.addFilter(_OffSiteLinks())

    app.connect("builder-inited", install)

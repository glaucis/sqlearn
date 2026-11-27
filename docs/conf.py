"""Sphinx configuration for the sqlearn site."""

from pathlib import Path
from posixpath import dirname, join, normpath

from docutils import nodes
from sphinx.addnodes import pending_xref

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
    "myst_nb",
    "sphinxcontrib.bibtex",
]

# Every cross-reference resolves, from the first build.
nitpicky = True
# Types that docstrings name and the reference does not list: the internal
# (underscored) classes, such as the selectors and a group's settings, the
# search-method and fold classes, DuckDB's private type module,
# and the part of a type such as "dict[str, list]" that numpydoc splits at its
# comma.
nitpick_ignore_regex = [
    ("py:class", r"sqlearn\.(.*\.)?_.*"),
    ("py:class", r"sqlearn\.model_selection\.(methods|folds)\..*"),
    ("py:class", r"dict\[str"),
    ("py:class", r"_duckdb\..*"),
    # Optuna is optional and has no inventory here.
    ("py:class", r"BaseSampler"),
    # numpy has no inventory here either (a Gram step's matrix, ADR 0058).
    ("py:class", r"numpy\.ndarray"),
]
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
templates_path = ["_templates"]
numpydoc_show_class_members = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", "_inventories/python.inv"),
    # DuckDB's current/ has no objects.inv, so the URL names the release.
    # Keep it at the major version of the duckdb floor in pyproject.toml.
    "duckdb": (
        "https://duckdb.org/docs/2.0/clients/python/reference/",
        "_inventories/duckdb.inv",
    ),
}

# MathJax comes from docs/_static/mathjax (`just fetch-mathjax`), never a CDN.
# MathJax's own files are found from the script's address, [mathjax]. Its font
# package is looked up under the loader's "fonts" path, which points at the
# copy in fonts/. The speech, braille and explorer features would fetch
# speech-rule-engine's mathmaps from a CDN, so they are off, both as options
# and as the menu settings that override them. The menu can still turn speech
# on, and the loader would then name a CDN for speech-rule-engine: its path
# points at the local copy's absent sre/ folder, so the request stays local and
# simply fails.
mathjax_path = "mathjax/tex-chtml.js"
mathjax4_config = {
    "loader": {"paths": {"fonts": "[mathjax]/fonts", "sre": "[mathjax]/sre"}},
    "options": {
        "enableSpeech": False,
        "enableBraille": False,
        "enableExplorer": False,
        "enableEnrichment": False,
        "enableComplexity": False,
        "menuOptions": {
            "settings": {
                "enrich": False,
                "speech": False,
                "braille": False,
                "collapsible": False,
            },
        },
    },
}

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence"]
nb_execution_mode = "cache"
nb_execution_raise_on_error = True

bibtex_bibfiles = ["references.bib"]


# Pages on the site link to docs/ folders that are not on it. Those links
# become links to the files on GitHub. The repository's address, in one place.
REPOSITORY = "https://github.com/glaucis/sqlearn"
BRANCH = "main"
OFF_SITE = ("specs", "plans", "questions", "agents")
_DOCS = Path(__file__).parent


def _off_site_uri(node: pending_xref) -> str | None:
    """Return the GitHub address a link into an off-site folder should have."""
    target = node["reftarget"]
    if node.get("refdomain") == "doc":
        # A document link: Sphinx has dropped the suffix and made the path
        # relative to docs/.
        path = normpath(target)
        suffixes = (".md", ".rst")
        found = [p for p in (path + s for s in suffixes) if (_DOCS / p).is_file()]
        if not found:
            return None
        kind, path = "blob", found[0]
    elif node.get("refdomain") is None and target.endswith("/"):
        # A folder link, relative to the page it is written on.
        path = normpath(join(dirname(node["refdoc"]), target))
        if not (_DOCS / path).is_dir():
            return None
        kind = "tree"
    else:
        return None
    if path.split("/", 1)[0] not in OFF_SITE:
        return None
    uri = f"{REPOSITORY}/{kind}/{BRANCH}/docs/{path}"
    if node.get("reftargetid"):
        uri += f"#{node['reftargetid']}"
    return uri


def _link_off_site(app, doctree) -> None:
    """Replace MyST links into off-site folders with GitHub links.

    A link whose target does not exist is left alone, so Sphinx warns.
    """
    for node in list(doctree.findall(pending_xref)):
        if node.get("reftype") != "myst":
            continue
        uri = _off_site_uri(node)
        if uri is None:
            continue
        reference = nodes.reference("", "", refuri=uri, internal=False)
        reference.extend(child.deepcopy() for child in node.children)
        node.replace_self(reference)


def setup(app) -> None:
    """Register the off-site link handler."""
    app.connect("doctree-read", _link_off_site)

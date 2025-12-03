# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information


"""
conf.py file
"""
from datetime import date, datetime
from typing import Final

project = "Conda Recipe Manager"
author = "various"
# TODO make this automatic, update README
release = "0.9.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.doctest",
    "sphinx.ext.autosummary",
]
autosummary_generate = True
# See this doc for more details on autosummary options:
#   https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#confval-autodoc_default_options
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "private-members": False,
    "show-inheritance": True,
    "inherited-members": True,
    "member-order": "groupwise",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "English"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_book_theme"
today_str: Final = date.today().strftime("%B %d, %Y")
html_theme_options = {
    "repository_provider": "github",
    "repository_url": "https://github.com/conda/conda-recipe-manager",
    "use_repository_button": True,
    "extra_footer": f"Last updated on: {today_str}",
}
author = "The Conda Community Maintainers"
copyright = str(datetime.now().year)  # pylint: disable=redefined-builtin

# html_static_path = ["_static"]

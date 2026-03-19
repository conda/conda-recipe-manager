"""
:Description: Top-level module for the conda-recipe-manager project.
"""

import logging
import warnings

from conda_recipe_manager.parser.exceptions import DuplicateKeyWarning

# Default to emitting no logs. It is up to the client program to define logging conditions.
logging.getLogger(__name__).addHandler(logging.NullHandler())
# Default to ignoring warnings. Client program can enable them with
# warnings.filterwarnings("always", category=DuplicateKeyWarning)
warnings.filterwarnings("ignore", category=DuplicateKeyWarning)

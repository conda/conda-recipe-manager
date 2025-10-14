"""
:Description: Provides library tooling to perform recipe version updates or recipe "bumps". Most of the work found
    here originates from the `crm bump-recipe` command line interface.
"""

import logging
from pathlib import Path
from typing import Final

from conda_recipe_manager.parser.recipe_parser import RecipeParser

log: Final = logging.getLogger(__name__)


class VersionBumper:
    """
    TODO
    """

    def __init__(self) -> None:
        """
        TODO
        """
        # TODO pass this in? or ditch class entirely
        self._recipe_parser = RecipeParser("")

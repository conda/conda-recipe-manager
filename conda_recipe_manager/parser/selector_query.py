"""
:Description: Provides an object that can be configured to perform complex selector queries.
"""

from typing import NamedTuple, Optional

from conda_recipe_manager.parser.platform_types import Platform


class SelectorQuery(NamedTuple):
    """
    Data structure that is used to represent complex selector queries.
    """

    platform: Optional[Platform] = None
    build_env_vars: set[str] = set()

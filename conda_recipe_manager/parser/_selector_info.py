"""
:Description: Provides the `SelectorInfo` class, used to store selector information.
"""

from __future__ import annotations

from typing import NamedTuple

from conda_recipe_manager.parser._node import Node
from conda_recipe_manager.parser._types import StrStack
from conda_recipe_manager.parser._utils import stack_path_to_str


class SelectorInfo(NamedTuple):
    """
    Immutable structure that tracks information about how a particular selector is used.
    """

    node: Node
    path: StrStack

    def __str__(self) -> str:
        """
        Generates the string form of a `SelectorInfo` object. Useful for debugging.

        :returns: String representation of a `SelectorInfo` instance
        """
        path_str = stack_path_to_str(self.path)
        return f"{self.node.short_str()} -> {path_str}"

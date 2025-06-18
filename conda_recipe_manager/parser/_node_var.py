"""
:Description: Provides a `NodeVar` class that represents a recipe/CBC variable line.
    This is some-what-analogous to the original `Node` class, but does not share any common lineage.
"""

from __future__ import annotations

from typing import Final, Optional

from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser._utils import search_any_regex
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import SchemaVersion
from conda_recipe_manager.types import JsonType


class NodeVar:
    """
    Simple representation of a variable found in a recipe or CBC file.

    This class was originally called `_CBCEntry` and was exclusively used in the `CbcParser` class. It has now been
    generalized for use in the `RecipeParser` class.
    """

    def __init__(self, value: JsonType, comment: Optional[str] = None):
        self._value = value
        # Raw comment string. This may or may not contain a V0 selector. Modeled after the `Node.comment` for
        # consistency (so this includes the leading `#`)
        self._comment = comment
        # TODO add V1 support
        selector_str: Final = SelectorParser._v0_extract_selector(comment)
        self._selector: Final = SelectorParser(selector_str, SchemaVersion.V0) if selector_str else None

    def __eq__(self, other: object) -> bool:
        """
        Determine if two nodes are equal.

        :param other: Other object to check against
        :returns: True if the two nodes are identical. False otherwise.
        """
        if not isinstance(other, NodeVar):
            return False
        # We don't directly compare the `_selector` field as it is calculated from `_comment`.
        return self._value == other._value and self._comment == other._comment

    def __str__(self) -> str:
        """
        Renders the node as a string. Useful for debugging purposes. This mimics the behavior of the `Node` and
        `RecipeReader` classes.

        :returns: The node, as a string
        """
        return (
            f"Node: {self._value}\n"
            f"  - Comment:          {self._comment!r}\n"
            f"  - Parsed Selector:  {self._selector!r}\n"
        )

    def __repr__(self) -> str:
        """
        Renders the Node as a simple string. Useful for other `__str__()` functions to call.

        :returns: The node, as a simplified string.
        """
        return str(self._value)

    def get_value(self) -> JsonType:
        """
        Retrieves the value associated with a variable node.

        :returns: The variable's value.
        """
        return self._value

    def render_v0_value(self) -> str:
        """
        Renders a variable's value as it would appear in a V0 recipe file. V1 recipes are handled as members of the
        `/context` object, so there is currently no equivalent function in V1.

        :returns: A string representing how a variable appears in a V0 recipe.
        """
        # Double quote strings, except for when we detect a env.get() expression or any JINJA functions.
        # See issues #271, #366 for more details.
        if (
            isinstance(self._value, str)
            and not self._value.startswith("env.get(")
            and not search_any_regex(Regex.JINJA_FUNCTIONS_SET, self._value)
        ):
            return f"'{self._value}'" if '"' in self._value else f'"{self._value}"'
        return str(self._value)

    def render_comment(self) -> str:
        """
        Renders a variable comment as it would appear in a recipe file. If there is no comment, this returns an empty
        string.

        :returns: A string representing how a comment would appear in a recipe file.
        """
        if self._comment is None:
            return ""
        return f"  {self._comment}"

    def contains_selector(self) -> bool:
        """
        Indicates if a selector is associated with a variable.

        :returns: True if a selector is present on the variable. Otherwise, False.
        """
        # TODO add V1 support
        return self._selector is not None

    def get_selector(self) -> Optional[SelectorParser]:
        """
        Provides access to a `SelectorParser` instance, if a selector applies to this variable.

        :returns: A `SelectorParser` instance, if one applies. Otherwise, `None`.
        """
        # TODO add V1 support
        return self._selector

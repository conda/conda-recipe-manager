"""
:Description: Provides a private node class only used by the parser. This class is fundamental to tree formation.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from conda_recipe_manager.parser._types import ROOT_NODE_VALUE
from conda_recipe_manager.parser.types import MultilineVariant, NodeValue
from conda_recipe_manager.types import SentinelType


class CommentPosition(Enum):
    """
    Enumerations
    """

    # "Default" comment position algorithm. In other words, what `render()` would show prior to this enum's creation.
    DEFAULT = auto()
    # Indicates the comment should be at the top of the file.
    TOP_OF_FILE = auto()


class Node:
    """
    Private class representing a node in a recipe parse tree.

    Each level of a path consists of a list of child nodes. Child nodes can recursively store more child nodes until a
    final value is found, indicated by having an empty list of children.

    Remember that YAML keys must be strings, but the `value` can another primitive type for leaf nodes.

    Comments on a recipe line are stored separately from the value.

    Variable names are not substituted. In other words, the raw strings from the file are stored as text.
    """

    # Sentinel used to discern a `null` in the YAML file and a defaulted, unset value. For example, comment-only lines
    # should always be set to the `_sentinel` object.
    _sentinel = SentinelType()

    def __init__(
        self,
        value: NodeValue | SentinelType = _sentinel,
        # TODO Future: Node comments should be Optional.
        comment: str = "",
        comment_pos: CommentPosition = CommentPosition.DEFAULT,
        children: Optional[list["Node"]] = None,
        list_member_flag: bool = False,
        multiline_variant: MultilineVariant = MultilineVariant.NONE,
        key_flag: bool = False,
    ):
        """
        Constructs a node.

        TODO members (or at least most members) of the `Node` class should be marked as private.

        :param value:               Value of the current node
        :param comment:             Comment on the line this node was found on
        :param comment_pos:         Special enum indicating full-line comment positioning.
        :param children:            List of children nodes, descendants of this node
        :param list_member_flag:    Indicates if this node is part of a list
        :param multiline_variant:   Indicates if the node represents a multiline value AND which syntax variant is used
        :param key_flag:            Indicates if the node represents a key that points to zero or more subsequent values
        """
        self.value = value
        self.comment = comment
        self.comment_pos = comment_pos
        self.children: list[Node] = children if children else []
        self.list_member_flag = list_member_flag
        self.multiline_variant = multiline_variant
        self.key_flag = key_flag

    def __eq__(self, other: object) -> bool:
        """
        Determine if two nodes are equal.

        :param other: Other object to check against
        :returns: True if the two nodes are identical. False otherwise.
        """
        if not isinstance(other, Node):
            return False
        return (
            self.value == other.value
            and self.comment == other.comment
            and self.list_member_flag == other.list_member_flag
            and self.multiline_variant == other.multiline_variant
            # Save recursive (most expensive) check for last
            and self.children == other.children
        )

    def __str__(self) -> str:
        """
        Renders the Node as a string. Useful for debugging purposes.

        :returns: The node, as a string
        """
        value = self.value
        if self.is_comment():
            value = "Comment node"
        if self.is_collection_element():
            value = "Collection node"
        return (
            f"Node: {value}\n"
            f"  - Comment:      {self.comment!r}\n"
            f"  - Child count:  {len(self.children)}\n"
            f"  - List?:        {self.list_member_flag}\n"
            f"  - Multiline?:   {self.multiline_variant}\n"
            f"  - Key?:         {self.key_flag}\n"
        )

    def short_str(self) -> str:
        """
        Renders the Node as a simple string. Useful for other `__str__()` functions to call.

        :returns: The node, as a simplified string.
        """
        if self.is_comment():
            return f"<Comment: {self.comment}>"
        if self.is_collection_element():
            return "<Collection Node>"
        return str(self.value)

    def is_leaf(self) -> bool:
        """
        Indicates if a node is a leaf node

        :returns: True if the node is a leaf. False otherwise.
        """
        return not self.children and not self.is_comment()

    def is_root(self) -> bool:
        """
        Indicates if a node is a root node

        :returns: True if the node is a root node. False otherwise.
        """
        return self.value == ROOT_NODE_VALUE

    def is_comment(self) -> bool:
        """
        Indicates if a line contains only a comment. When rendered, this will be a comment only-line.

        :returns: True if the node represents only a comment. False otherwise.
        """
        return self.value == Node._sentinel and bool(self.comment) and not self.children

    def is_tof_comment(self) -> bool:
        """
        Indicates if a line contains only a comment, located at the top of the file. When rendered, this will be a
        comment only-line. This only applies to V0 recipes.

        :returns: True if the node represents only a comment. False otherwise.
        """
        return self.is_comment() and self.comment_pos == CommentPosition.TOP_OF_FILE

    def is_empty_key(self) -> bool:
        """
        Indicates a line that is just a "label" and contains no child nodes. These are effectively leaf nodes that need
        to be rendered specially.

        Example empty key:
          foo:
        Versus a non-empty key:
          foo:
            - bar

        When converted into a Pythonic data structure, the key will point to an `None` value.

        :returns: True if the node represents an empty key. False otherwise.
        """
        return self.key_flag and self.is_leaf()

    def is_single_key(self) -> bool:
        """
        Indicates if a node contains a single child node and is a key.

        This special case is used in several edge cases. Namely, it allows the rendering algorithm to print such
        key-value pairs on the same line.

        :returns: True if the node represents a single key. False otherwise.
        """
        return self.key_flag and len(self.children) == 1 and self.children[0].is_leaf()

    def is_collection_element(self) -> bool:
        """
        Indicates if the node is a list member that contains other collection types. In other words, this node has no
        value itself BUT it contains children that do.

        :returns: True if the node represents an element that is a collection. False otherwise.
        """
        return self.value == Node._sentinel and self.list_member_flag and bool(self.children)

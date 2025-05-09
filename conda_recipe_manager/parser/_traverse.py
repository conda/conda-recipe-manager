"""
:Description: Provides tree traversal functions only used by the parser.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Optional

from conda_recipe_manager.parser._node import Node
from conda_recipe_manager.parser._types import ROOT_NODE_VALUE, StrStack, StrStackImmutable

# Indicates an array index that is not valid
INVALID_IDX: Final[int] = -1


def remap_child_indices_virt_to_phys(children: list[Node]) -> list[int]:
    """
    Given a list of child nodes, generate a look-up table to map the "virtual" index positions with the "physical"
    locations.

    A recipe file may have comment lines, represented as child nodes. For rendering, these nodes must be preserved,
    in-order.

    For manipulating and accessing list members, however, comments are to be ignored. The calling program should not
    rely on our implementation details and should be able to access a member of a list as expected. In other words,
    users will not consider comments in a list as indexable list members.

    :param children: Child node list to process.
    :returns: A list of indices. Indexing this list with the "virtual" (user-provided) index will return the "physical"
        list position.
    """
    mapping: list[int] = []
    cntr = 0
    for child in children:
        if child.is_comment():
            cntr += 1
            continue
        mapping.append(cntr)
        cntr += 1

    return mapping


def remap_child_indices_phys_to_virt(children: list[Node]) -> list[int]:
    """
    Produces the "inverted" table created by `remap_child_indices_virt_to_phys()`.
    See `remap_child_indices_virt_to_phys()` for more details.

    :param children: Child node list to process.
    :returns: A list of indices. Indexing this list with the "physical" (class-provided) index will return the "virtual"
        list position.
    """
    mapping: list[int] = remap_child_indices_virt_to_phys(children)
    new_mapping: list[int] = [0] * len(children)
    for i in range(len(mapping)):
        new_mapping[mapping[i]] = i
    return new_mapping


def _traverse_recurse(node: Node, path: StrStack) -> Optional[Node]:
    """
    Recursive helper function for traversing a tree.

    :param node: Current node on the tree.
    :param path: Path, as a stack, that describes a location in the tree.
    :returns: `Node` object if a node is found in the parse tree at that path. Otherwise returns `None`.
    """
    if len(path) == 0:
        return node

    path_part = path[-1]
    # Check if the path is attempting an array index.
    if path_part.isdigit():
        # Map virtual to physical indices and perform some out-of-bounds checks.
        idx_map = remap_child_indices_virt_to_phys(node.children)
        virtual_idx = int(path_part)
        max_idx = len(idx_map) - 1
        if virtual_idx < 0 or virtual_idx > max_idx:
            return None

        path_idx = idx_map[virtual_idx]
        # Edge case: someone attempts to use the index syntax on a non-list member. As children are stored as a list
        # per node, this could "work" with unintended consequences. In other words, users could accidentally abuse
        # underlying implementation details.
        if not node.children[path_idx].list_member_flag:
            return None

        path.pop()
        return _traverse_recurse(node.children[path_idx], path)

    for child in node.children:
        # Remember: for nodes that represent part of the path, the "value" stored in the node is part of the path-name.
        if child.value == path_part:
            path.pop()
            return _traverse_recurse(child, path)
    # Path not found
    return None


def traverse(node: Optional[Node], path: StrStack) -> Optional[Node]:
    """
    Given a path in the recipe tree, traverse the tree and return the node at that path.
    If no Node is found at that path, return `None`.

    :param node: Starting node of the tree/branch to traverse.
    :param path: Path, as a stack, that describes a location in the tree.
    :returns: `Node` object if a node is found in the parse tree at that path. Otherwise returns `None`.
    """
    # Bootstrap recursive edge cases
    if node is None:
        return None
    if len(path) == 0:
        return None
    if len(path) == 1:
        if path[0] == ROOT_NODE_VALUE:
            return node
        return None
    # Purge `root` from the path
    path.pop()
    return _traverse_recurse(node, path)


def traverse_with_index(root: Node, path: StrStack) -> tuple[Optional[Node], int, int]:
    """
    Given a path, return the node of interest OR the parent node with indexing information, if the node is in a list.

    :param root: Starting node of the tree/branch to traverse.
    :param path: Path, as a stack, that describes a location in the tree.
    :returns: A tuple containing: - `Node` object if a node is found in the parse tree at that path. Otherwise
          returns `None`. If the path terminates in an index, the parent is returned with the index location.
        - If the node is a member of a list, the VIRTUAL index returned will be >= 0
        - If the node is a member of a list, the PHYSICAL index returned will be >= 0
    """
    if len(path) == 0:
        return None, INVALID_IDX, INVALID_IDX

    node: Optional[Node]
    virt_idx: int = INVALID_IDX
    phys_idx: int = INVALID_IDX
    # Pre-determine if the path is targeting a list position. Patching only applies on the last index provided.
    if path[0].isdigit():
        # Find the index position of the target on the parent's list
        virt_idx = int(path.pop(0))

    node = traverse(root, path)
    if node is not None and virt_idx >= 0:
        phys_idx = remap_child_indices_virt_to_phys(node.children)[virt_idx]

        # If the node in a list is a "Collection Element", we want return that node and not the parent that contains
        # the list. Collection Nodes are abstract containers that will contain the rest of
        if node.children[phys_idx].is_collection_element():
            return node.children[phys_idx], INVALID_IDX, INVALID_IDX

    return node, virt_idx, phys_idx


def traverse_all(
    node: Optional[Node],
    func: Callable[[Node, StrStack], None],
    path: Optional[StrStackImmutable] = None,
    idx_num: int = 0,
) -> None:
    """
    Given a node, traverse all child nodes and apply a function to each node. Useful for updating or extracting
    information on the whole tree.

    NOTE: The paths provided will return virtual indices, not physical indices. In other words, comments in a list do
          not count towards the index position of a list member.

    :param node: Node to start with
    :param func: Function to apply against all traversed nodes.
    :param path: CALLERS: DO NOT SET. This value tracks the current path of a node. This should only be specified in
        recursive calls to this function. Tuples are used for their immutability, so paths change based on the current
        stack frame.
    :param idx_num: CALLERS: DO NOT SET. Used in recursive calls to track the index position of a list-member node.
    """
    if node is None:
        return
    # Initialize, if on the root node. Otherwise build-up the path
    if path is None:
        path = (ROOT_NODE_VALUE,)
    elif node.list_member_flag:
        path = (str(idx_num),) + path
    # Leafs do not contain their values in the path, unless the leaf is an empty key (as the key is part of the path).
    elif node.is_empty_key() or not node.is_leaf():
        path = (str(node.value),) + path
    func(node, list(path))
    # Used for paths that contain lists of items
    mapping = remap_child_indices_phys_to_virt(node.children)
    for i in range(len(node.children)):
        traverse_all(node.children[i], func, path, mapping[i])

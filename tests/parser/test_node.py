"""
:Description: Unit tests for the `Node` class
"""

from __future__ import annotations

from conda_recipe_manager.parser._node import Node


def test_is_inline_scalar_key_rejects_section_with_single_list_item() -> None:
    """
    Tests that `Node.is_inline_scalar_key()` does not mistake a section holding exactly one list item (e.g. `run:`
    followed by a single `- a` line) for a true in-line `key: value` pair. Both end up with exactly one "strong
    leaf" child, so `Node.is_single_key()` alone cannot tell them apart - the list item's `list_member_flag` is what
    disambiguates the two.
    """
    leaf_key = Node(value="script", key_flag=True, children=[Node(value="install.sh")])
    section_with_one_list_item = Node(value="run", key_flag=True, children=[Node(value="a", list_member_flag=True)])

    assert leaf_key.is_inline_scalar_key()
    assert not section_with_one_list_item.is_inline_scalar_key()

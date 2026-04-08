"""
:Description: Unit tests for the parser _utils
"""

from __future__ import annotations

from conda_recipe_manager.parser._utils import stack_path_to_str


def test_stack_path_to_str_does_not_modify_input() -> None:
    """
    Verify that stack_path_to_str does not modify the input stack.
    The old implementation would pop elements off the stack, leaving the list empty
    and unuseable after calling stack_path_to_str.
    """
    # path_stack is stored in reverse order
    # ex: path /build/skip is stored as ["skip", "build", "/"]
    path_stack: list[str] = ["skip", "build", "/"]

    stack_path_to_str(path_stack)

    assert path_stack == ["skip", "build", "/"]

"""
:Description: Unit tests for the parser _utils
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.parser._utils import stack_path_to_str, str_to_stack_path


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


def test_str_to_stack_path_rejects_empty_path() -> None:
    """
    An empty path string cannot be deconstructed and must fail with a clear
    error instead of an unhandled `IndexError`.
    """
    with pytest.raises(ValueError, match="must not be empty"):
        str_to_stack_path("")


def test_str_to_stack_path_round_trip() -> None:
    """
    A well-formed path deconstructs into a stack and back without changes.
    """
    assert str_to_stack_path("/foo/bar") == ["bar", "foo", "/"]

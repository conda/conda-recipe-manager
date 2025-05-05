"""
:Description: Unit tests for the RecipeParser class
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import cast

import pytest

from conda_recipe_manager.parser.enums import SelectorConflictMode
from conda_recipe_manager.parser.exceptions import JsonPatchValidationException
from conda_recipe_manager.parser.recipe_parser import RecipeParser, ReplacePatchFunc
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import SchemaVersion
from conda_recipe_manager.types import JsonType
from tests.constants import SIMPLE_DESCRIPTION
from tests.file_loading import load_file, load_recipe

## JINJA Variables ##


@pytest.mark.parametrize(
    "file",
    [
        "simple-recipe.yaml",
        "v1_format/v1_simple-recipe.yaml",
    ],
)
def test_set_variable(file: str) -> None:
    """
    Tests setting and adding a variable. Ensures post-op state is accurate.

    :param file: File to test against
    """
    parser = load_recipe(file, RecipeParser)
    parser.set_variable("name", "foobar")
    parser.set_variable("zz_non_alpha_first", 24)
    # Ensure a missing variable gets added
    parser.set_variable("DNE", "The limit doesn't exist")
    assert parser.is_modified()
    assert parser.list_variables() == [
        "zz_non_alpha_first",
        "name",
        "version",
        "DNE",
    ]
    assert parser.get_variable("name") == "foobar"
    assert parser.get_variable("zz_non_alpha_first") == 24
    assert parser.get_variable("DNE") == "The limit doesn't exist"


@pytest.mark.parametrize(
    "file",
    [
        "simple-recipe.yaml",
        "v1_format/v1_simple-recipe.yaml",
    ],
)
def test_del_variable(file: str) -> None:
    """
    Tests deleting a variable

    :param file: File to test against
    """
    parser = load_recipe(file, RecipeParser)
    parser.del_variable("name")
    assert parser.is_modified()
    # Ensure a missing variable doesn't crash a delete operation
    parser.del_variable("DNE")
    assert parser.list_variables() == ["zz_non_alpha_first", "version"]
    with pytest.raises(KeyError):
        parser.get_variable("name")


## Selectors ##


# TODO parameterize
# TODO Add V1 support
def test_add_selector() -> None:
    """
    Tests adding a selector to a recipe
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # Test that selector validation is working
    with pytest.raises(KeyError):
        parser.add_selector("/package/path/to/fake/value", "[unix]")
    with pytest.raises(ValueError):
        parser.add_selector("/build/number", "bad selector")
    assert not parser.is_modified()

    # Add selectors to lines without existing selectors
    parser.add_selector("/requirements/empty_field3", "[unix]")
    parser.add_selector("/multi_level/list_1/0", "[unix]")
    # SelectorParser equivalent
    parser.add_selector("/build/number", SelectorParser("[win]", SchemaVersion.V0))
    parser.add_selector("/multi_level/list_2/1", "[win]")
    assert parser.get_selector_paths("[unix]") == [
        "/package/name",
        "/requirements/host/0",
        "/requirements/host/1",
        "/requirements/empty_field3",
        "/multi_level/list_1/0",
    ]
    assert parser.get_selector_paths("[win]") == [
        "/build/number",
        "/multi_level/list_2/1",
    ]

    # Add selectors to existing selectors
    parser.add_selector("/requirements/host/0", "[win]", SelectorConflictMode.REPLACE)
    assert parser.get_selector_paths("[win]") == [
        "/build/number",
        "/requirements/host/0",
        "/multi_level/list_2/1",
    ]
    parser.add_selector("/requirements/host/1", "[win]", SelectorConflictMode.AND)
    assert parser.get_selector_paths("[unix and win]") == ["/requirements/host/1", "/requirements/empty_field2"]
    # SelectorParser equivalent
    parser.add_selector("/build/skip", SelectorParser("[win]", SchemaVersion.V0), SelectorConflictMode.OR)
    assert parser.get_selector_paths("[py<37 or win]") == ["/build/skip"]
    parser.add_selector("/requirements/run/0", "[win]", SelectorConflictMode.AND)
    assert parser.get_selector_paths("[win]") == [
        "/build/number",
        "/requirements/host/0",
        "/requirements/run/0",
        "/multi_level/list_2/1",
    ]

    assert parser.render() == load_file("simple-recipe_test_add_selector.yaml")
    assert parser.is_modified()


def test_remove_selector() -> None:
    """
    Tests removing a selector to a recipe
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # Test that selector validation is working
    with pytest.raises(KeyError):
        parser.remove_selector("/package/path/to/fake/value")

    # Don't fail when a selector doesn't exist on a line
    assert parser.remove_selector("/build/number") is None
    # Don't remove a non-selector comment
    assert parser.remove_selector("/requirements/run/0") is None
    assert not parser.is_modified()

    # Remove a selector
    assert parser.remove_selector("/package/name") == "[unix]"
    assert parser.get_selector_paths("[unix]") == [
        "/requirements/host/0",
        "/requirements/host/1",
    ]
    # Remove a selector with a comment
    assert parser.remove_selector("/requirements/host/1") == "[unix]"
    assert parser.get_selector_paths("[unix]") == [
        "/requirements/host/0",
    ]
    # Remove a selector with a "double comment (extra `#` symbols used)"
    assert parser.remove_selector("/requirements/empty_field2") == "[unix and win]"
    assert not parser.get_selector_paths("[unix and win]")

    assert parser.render() == load_file("simple-recipe_test_remove_selector.yaml")
    assert parser.is_modified()


@pytest.mark.parametrize(
    "file,ops,expected",
    [
        (
            "simple-recipe.yaml",
            [
                ("/package/name", "# Come on Jeffery"),
                ("/build/number", "# you can do it!"),
                ("/requirements/empty_field1", "Pave the way!"),
                ("/multi_level/list_1", "# Put your back into it!"),
                ("/multi_level/list_2/1", "# Tell us why"),
                ("/multi_level/list_2/2", " Show us how"),
                ("/multi_level/list_3/0", "# Look at where you came from"),
                ("/test_var_usage/foo", "Look at you now!"),
            ],
            "simple-recipe_test_add_comment.yaml",
        ),
    ],
)
def test_add_comment(file: str, ops: list[tuple[str, str]], expected: str) -> None:
    """
    Validates adding a comment to the target recipe.

    :param file: File to test against
    :param ops: List of comment operations to perform in this test
    :param expected: Expected result of the test
    """
    parser = load_recipe(file, RecipeParser)
    for path, comment in ops:
        parser.add_comment(path, comment)
    assert parser.is_modified()
    assert parser.render() == load_file(expected)


@pytest.mark.parametrize(
    "file,path,comment,exception",
    [
        ("simple-recipe.yaml", "/package/path/to/fake/value", "A comment", KeyError),
        ("simple-recipe.yaml", "/build/number", "[unix]", ValueError),
        ("simple-recipe.yaml", "/build/number", "", ValueError),
        ("simple-recipe.yaml", "/build/number", "    ", ValueError),
    ],
)
def test_add_comment_raises(file: str, path: str, comment: str, exception: BaseException) -> None:
    """
    Tests scenarios where `add_comment()` should raise an exception

    :param file: File to test against
    :param path: Path to add a comment
    :param comment: Comment to add
    :param exception: Exception expected to be raised
    """
    parser = load_recipe(file, RecipeParser)
    with pytest.raises(exception):  # type: ignore
        parser.add_comment(path, comment)


## Patch and Search ##


def test_patch_schema_validation() -> None:
    """
    Tests edge cases that should trigger an exception on JSON patch schema validation. Valid schemas are inherently
    tested in the other patching tests.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # Invalid enum/unknown op
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "fakeop",
                "path": "/build/number",
                "value": 42,
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "",
                "path": "/build/number",
                "value": 42,
            }
        )
    # Patch has extra field(s)
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "replace",
                "path": "/build/number",
                "value": 42,
                "extra": "field",
            }
        )
    # Patch is missing required fields
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "path": "/build/number",
                "value": 42,
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "replace",
                "value": 42,
            }
        )
    # Patch is missing required fields, based on `op`
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "add",
                "path": "/build/number",
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "replace",
                "path": "/build/number",
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "move",
                "path": "/build/number",
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "copy",
                "path": "/build/number",
            }
        )
    with pytest.raises(JsonPatchValidationException):
        parser.patch(
            {
                "op": "test",
                "path": "/build/number",
            }
        )
    # Patch has invalid types in critical fields
    with pytest.raises(JsonPatchValidationException):
        parser.patch({"op": "move", "path": 42, "value": 42})
    with pytest.raises(JsonPatchValidationException):
        parser.patch({"op": "move", "path": "/build/number", "from": 42})


def test_patch_path_invalid() -> None:
    """
    Tests if `patch` returns false on all ops when the path is not found. Also checks if the tree has been modified.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)

    # Passing an empty path fails at the JSON schema validation layer, so it applies to all patch functions.
    with pytest.raises(JsonPatchValidationException):
        assert not (
            parser.patch(
                {
                    "op": "test",
                    "path": "",
                    "value": 42,
                }
            )
        )

    # add
    assert not (
        parser.patch(
            {
                "op": "add",
                "path": "/package/path/to/fake/value",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "add",
                "path": "/build/number/0",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "add",
                "path": "/multi_level/list2/4",
                "value": 42,
            }
        )
    )
    # remove
    assert not (
        parser.patch(
            {
                "op": "remove",
                "path": "/package/path/to/fake/value",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "remove",
                "path": "/build/number/0",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "remove",
                "path": "/multi_level/list2/4",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "remove",
                "path": "/build/skip/true",
            }
        )
    )
    # replace
    assert not (
        parser.patch(
            {
                "op": "replace",
                "path": "/build/number/0",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "replace",
                "path": "/multi_level/list2/4",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "replace",
                "path": "/build/skip/true",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "replace",
                "path": "/package/path/to/fake/value",
                "value": 42,
            }
        )
    )

    # move, `path` is invalid
    assert not (
        parser.patch(
            {
                "op": "move",
                "path": "/package/path/to/fake/value",
                "from": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "move",
                "path": "/build/number/0",
                "from": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "move",
                "path": "/multi_level/list2/4",
                "from": "/about/summary",
            }
        )
    )
    # move, `from` is invalid
    assert not (
        parser.patch(
            {
                "op": "move",
                "from": "/package/path/to/fake/value",
                "path": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "move",
                "from": "/build/number/0",
                "path": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "move",
                "from": "/multi_level/list2/4",
                "path": "/about/summary",
            }
        )
    )

    # copy, `path` is invalid
    assert not (
        parser.patch(
            {
                "op": "copy",
                "path": "/package/path/to/fake/value",
                "from": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "copy",
                "path": "/build/number/0",
                "from": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "copy",
                "path": "/multi_level/list2/4",
                "from": "/about/summary",
            }
        )
    )
    # copy, `from` is invalid
    assert not (
        parser.patch(
            {
                "op": "copy",
                "from": "/package/path/to/fake/value",
                "path": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "copy",
                "from": "/build/number/0",
                "path": "/about/summary",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "copy",
                "from": "/multi_level/list2/4",
                "path": "/about/summary",
            }
        )
    )

    # test
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/package/path/to/fake/value",
                "value": 42,
            }
        )
    )

    assert not parser.is_modified()


def test_patch_test() -> None:
    """
    Tests the `test` patch op. The `test` op may be useful for other test assertions, so it is tested before the other
    patch operations.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)

    # Test that values match, as expected
    assert parser.patch(
        {
            "op": "test",
            "path": "/build/number",
            "value": 0,
        }
    )
    assert parser.patch(
        {
            "op": "test",
            "path": "/build",
            "value": {
                "number": 0,
                "skip": True,
                "is_true": True,
            },
        }
    )
    assert parser.patch(
        {
            "op": "test",
            "path": "/requirements/host",
            "value": ["setuptools", "fakereq"],
        }
    )
    assert parser.patch(
        {
            "op": "test",
            "path": "/requirements/host/1",
            "value": "fakereq",
        }
    )
    assert parser.patch(
        {
            "op": "test",
            "path": "/about/description",
            "value": SIMPLE_DESCRIPTION,
        }
    )
    # Test that values do not match, as expected
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/build/number",
                "value": 42,
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/build",
                "value": {
                    "number": 42,
                    "skip": True,
                },
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/requirements/host",
                "value": ["not_setuptools", "fakereq"],
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/requirements/host/1",
                "value": "other_fake",
            }
        )
    )
    assert not (
        parser.patch(
            {
                "op": "test",
                "path": "/about/description",
                "value": "other_fake\nmultiline",
            }
        )
    )

    # Ensure that `test` does not modify the tree
    assert not parser.is_modified()


def test_patch_add() -> None:
    """
    Tests the `add` patch op.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)

    # As per the RFC, `add` will not construct multiple-levels of non-existing structures. The containing
    # object(s)/list(s) must exist.
    assert not parser.patch(
        {
            "op": "add",
            "path": "/build/fake/meaning_of_life",
            "value": 42,
        }
    )
    # Similarly, appending to a list
    assert not parser.patch(
        {
            "op": "add",
            "path": "/requirements/empty_field1/-/blah",
            "value": 42,
        }
    )
    assert not parser.is_modified()

    # Add primitive values
    assert parser.patch(
        {
            "op": "add",
            "path": "/build/meaning_of_life",
            "value": 42,
        }
    )
    assert parser.patch(
        {
            "op": "add",
            "path": "/package/is_cool_name",
            "value": True,
        }
    )

    # Add to empty-key node
    assert parser.patch(
        {
            "op": "add",
            "path": "/requirements/empty_field2",
            "value": "Not so empty now",
        }
    )

    # Add list items
    assert parser.patch(
        {
            "op": "add",
            "path": "/multi_level/list_2/1",
            "value": "We got it all on UHF",
        }
    )
    assert parser.patch(
        {
            "op": "add",
            "path": "/multi_level/list_1/0",
            "value": "There's just one place to go for all your spatula needs!",
        }
    )
    assert parser.patch(
        {
            "op": "add",
            "path": "/multi_level/list_1/-",
            "value": "Spatula City!",
        }
    )

    # Add a complex value
    assert parser.patch(
        {
            "op": "add",
            "path": "/test_var_usage/Stanley",
            "value": [
                "Oh, Joel Miller, you've just found the marble in the oatmeal.",
                "You're a lucky, lucky, lucky little boy.",
                "'Cause you know why?",
                "You get to drink from... the FIRE HOOOOOSE!",
            ],
        }
    )

    # Add a top-level complex value
    assert parser.patch(
        {
            "op": "add",
            "path": "/U62",
            "value": {
                "George": ["How'd you like your own TV show?", "You're on"],
                "Stanley": ["Ok"],
            },
        }
    )

    # Add an object to a list
    assert parser.patch(
        {
            "op": "add",
            "path": "/multi_level/list_3/1",
            "value": {
                "George": {"role": "owner", "has_mop": False},
                "Stanley": {"role": "janitor", "has_mop": True},
            },
        }
    )

    # Edge case: adding a value to an existing key (non-list) actually replaces the value at that key, as per the RFC.
    assert parser.patch({"op": "add", "path": "/about/summary", "value": 62})

    # Add a value in a list with a comment
    assert parser.patch({"op": "add", "path": "/multi_level/list_1/1", "value": "ken"})
    assert parser.patch({"op": "add", "path": "/multi_level/list_1/3", "value": "barbie"})

    # Sanity check: validate all modifications
    assert parser.is_modified()
    assert parser.render() == load_file("simple-recipe_test_patch_add.yaml")


@pytest.mark.parametrize(
    "file,path,value",
    [
        # Can't add more than one path level
        ("types-toml.yaml", "/foo/bar", "baz"),
        ("types-toml.yaml", "/requirements/run/foo/bar", "baz"),
        # The RFC allows for 1 level of path to be added, but that does not include adding to a list.
        ("types-toml.yaml", "/requirements/run_constrained/0", "openssl"),
        ("types-toml.yaml", "/requirements/run_constrained/-", "openssl"),
        ("cctools-ld64.yaml", "/outputs/-/requirements/run/0", "openssl"),
        # TODO Add V1 support
    ],
)
def test_patch_add_illegal_op(file: str, path: str, value: JsonType) -> None:
    """
    Ensures that illegal add operations fail gracefully.

    :param file: Recipe file to test
    :parma path: Target path to add to
    :param value: Target value to add
    """
    parser = load_recipe(file, RecipeParser)
    assert not parser.patch({"op": "add", "path": path, "value": value})
    assert not parser.is_modified()


def test_patch_remove() -> None:
    """
    Tests the `remove` patch op.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)

    # Remove primitive values
    assert parser.patch(
        {
            "op": "remove",
            "path": "/build/number",
        }
    )
    assert parser.patch(
        {
            "op": "remove",
            "path": "/package/name",
        }
    )

    # Remove empty-key node
    assert parser.patch(
        {
            "op": "remove",
            "path": "/requirements/empty_field2",
        }
    )

    # Remove list items
    assert parser.patch(
        {
            "op": "remove",
            "path": "/multi_level/list_2/0",
        }
    )
    # Ensure comments don't get erased
    assert parser.patch(
        {
            "op": "remove",
            "path": "/multi_level/list_1/1",
        }
    )

    # Remove a complex value
    assert parser.patch(
        {
            "op": "remove",
            "path": "/multi_level/list_3",
        }
    )

    # Remove a top-level complex value
    assert parser.patch(
        {
            "op": "remove",
            "path": "/about",
        }
    )

    # Sanity check: validate all modifications
    assert parser.is_modified()
    assert parser.render() == load_file("simple-recipe_test_patch_remove.yaml")


def test_patch_replace() -> None:
    """
    Tests the `replace` patch op.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # Patch an integer
    assert parser.patch(
        {
            "op": "replace",
            "path": "/build/number",
            "value": 42,
        }
    )
    # Patch a bool
    assert parser.patch(
        {
            "op": "replace",
            "path": "/build/is_true",
            "value": False,
        }
    )
    # Patch a string
    assert parser.patch(
        {
            "op": "replace",
            "path": "/about/license",
            "value": "MIT",
        }
    )
    # Patch an array element
    assert parser.patch(
        {
            "op": "replace",
            "path": "/requirements/run/0",
            "value": "cpython",
        }
    )
    # Patch an element to become an array
    assert parser.patch(
        {
            "op": "replace",
            "path": "/about/summary",
            "value": [
                "The Trial",
                "Never Ends",
                "Picard",
            ],
        }
    )
    # Patch a multiline string
    assert parser.patch(
        {
            "op": "replace",
            "path": "/about/description",
            "value": ("This is a PEP 561\ntype stub package\nfor the toml package."),
        }
    )

    # Hard mode: replace a string with an object containing multiple types in a complex data structure.
    assert parser.patch(
        {
            "op": "replace",
            "path": "/multi_level/list_2/1",
            "value": {"build": {"number": 42, "skip": True}},
        }
    )

    # Patch-in strings with quotes
    assert parser.patch(
        {
            "op": "replace",
            "path": "/multi_level/list_3/2",
            "value": "{{ compiler('c') }}",
        }
    )

    # Patch lists with comments
    assert parser.patch(
        {
            "op": "replace",
            "path": "/multi_level/list_1/0",
            "value": "ken",
        }
    )
    assert parser.patch(
        {
            "op": "replace",
            "path": "/multi_level/list_1/1",
            "value": "barbie",
        }
    )

    # Sanity check: validate all modifications
    assert parser.is_modified()
    # NOTE: That patches, as of writing, cannot preserve selectors
    assert parser.render() == load_file("simple-recipe_test_patch_replace.yaml")


def test_patch_move() -> None:
    """
    Tests the `move` patch op.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # No-op moves should not corrupt our modification state.
    assert parser.patch(
        {
            "op": "move",
            "path": "/build/number",
            "from": "/build/number",
        }
    )
    # Special failure case: trying to "add" to an illegal path while the "remove" path is still valid
    assert not parser.patch(
        {
            "op": "move",
            "path": "/build/number/0",
            "from": "/build/number",
        }
    )
    assert not parser.is_modified()
    assert parser.render() == load_file("simple-recipe.yaml")

    # Simple move
    assert parser.patch(
        {
            "op": "move",
            "path": "/requirements/number",
            "from": "/build/number",
        }
    )

    # Moving list item to a new key (replaces existing value)
    assert parser.patch(
        {
            "op": "move",
            "path": "/build/is_true",
            "from": "/multi_level/list_3/0",
        }
    )

    # Moving list item to a different list
    assert parser.patch(
        {
            "op": "move",
            "path": "/requirements/host/-",
            "from": "/multi_level/list_1/1",
        }
    )

    # Moving a list entry to another list entry position
    assert parser.patch(
        {
            "op": "move",
            "path": "/multi_level/list_2/0",
            "from": "/multi_level/list_2/1",
        }
    )

    # Moving a compound type
    assert parser.patch(
        {
            "op": "move",
            "path": "/multi_level/bar",
            "from": "/test_var_usage/bar",
        }
    )

    # Sanity check: validate all modifications
    assert parser.is_modified()
    # NOTE: That patches, as of writing, cannot preserve selectors
    assert parser.render() == load_file("simple-recipe_test_patch_move.yaml")


def test_patch_copy() -> None:
    """
    Tests the `copy` patch op.
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)

    # Simple copy
    assert parser.patch(
        {
            "op": "copy",
            "path": "/requirements/number",
            "from": "/build/number",
        }
    )

    # Copying list item to a new key
    assert parser.patch(
        {
            "op": "copy",
            "path": "/build/is_true",
            "from": "/multi_level/list_3/0",
        }
    )

    # Copying list item to a different list
    assert parser.patch(
        {
            "op": "copy",
            "path": "/requirements/host/-",
            "from": "/multi_level/list_1/1",
        }
    )

    # Copying a list entry to another list entry position
    assert parser.patch(
        {
            "op": "copy",
            "path": "/multi_level/list_2/0",
            "from": "/multi_level/list_2/1",
        }
    )

    # Copying a compound type
    assert parser.patch(
        {
            "op": "copy",
            "path": "/multi_level/bar",
            "from": "/test_var_usage/bar",
        }
    )

    # Sanity check: validate all modifications
    assert parser.is_modified()
    # NOTE: That patches, as of writing, cannot preserve selectors
    assert parser.render() == load_file("simple-recipe_test_patch_copy.yaml")


@pytest.mark.parametrize(
    "file,regex,patch_with,preserve,expected_file,expected_is_modified",
    [
        ("simple-recipe.yaml", re.compile(r"py.*"), "conda", False, "simple-recipe_test_search_and_patch.yaml", True),
        (
            "simple-recipe.yaml",
            re.compile(r"py.*"),
            "conda",
            True,
            "simple-recipe_test_search_and_patch_preserve_comments.yaml",
            True,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"py.*"),
            cast(Callable[[JsonType], str], lambda _: "con" + "da"),
            False,
            "simple-recipe_test_search_and_patch.yaml",
            True,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"py.*"),
            cast(Callable[[JsonType], str], lambda _: "con" + "da"),
            True,
            "simple-recipe_test_search_and_patch_preserve_comments.yaml",
            True,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"REGEX DOES NOT EXIST IN FILE!!!"),
            "conda",
            False,
            "simple-recipe.yaml",
            False,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"REGEX DOES NOT EXIST IN FILE!!!"),
            "conda",
            True,
            "simple-recipe.yaml",
            False,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"REGEX DOES NOT EXIST IN FILE!!!"),
            cast(Callable[[JsonType], str], lambda _: "con" + "da"),
            False,
            "simple-recipe.yaml",
            False,
        ),
        (
            "simple-recipe.yaml",
            re.compile(r"REGEX DOES NOT EXIST IN FILE!!!"),
            cast(Callable[[JsonType], str], lambda _: "con" + "da"),
            True,
            "simple-recipe.yaml",
            False,
        ),
    ],
)
def test_search_and_patch_replace(
    file: str,
    regex: re.Pattern[str],
    patch_with: JsonType | ReplacePatchFunc,
    preserve: bool,
    expected_file: str,
    expected_is_modified: bool,
) -> None:
    """
    Tests the ability for the `RecipeParser` to patch and replace values in a recipe file by regex-matching.
    """
    parser = load_recipe(file, RecipeParser)
    assert parser.search_and_patch_replace(regex, patch_with, preserve)
    assert parser.render() == load_file(expected_file)
    assert parser.is_modified() == expected_is_modified


def test_diff() -> None:
    """
    Tests diffing output function
    """
    parser = load_recipe("simple-recipe.yaml", RecipeParser)
    # Ensure a lack of a diff works
    assert parser.diff() == ""

    assert parser.patch(
        {
            "op": "replace",
            "path": "/build/number",
            "value": 42,
        }
    )
    # Patch a bool
    assert parser.patch(
        {
            "op": "replace",
            "path": "/build/is_true",
            "value": False,
        }
    )
    # Patch a string
    assert parser.patch(
        {
            "op": "replace",
            "path": "/about/license",
            "value": "MIT",
        }
    )
    assert parser.diff() == (
        "--- original\n"
        "\n"
        "+++ current\n"
        "\n"
        "@@ -6,9 +6,9 @@\n"
        "\n"
        "   name: {{ name|lower }}  # [unix]\n"
        " \n"
        " build:\n"
        "-  number: 0\n"
        "+  number: 42\n"
        "   skip: true  # [py<37]\n"
        "-  is_true: true\n"
        "+  is_true: false\n"
        " \n"
        " # Comment above a top-level structure\n"
        " requirements:\n"
        "@@ -27,7 +27,7 @@\n"
        "\n"
        "     This is a PEP '561 type stub package for the toml package.\n"
        "     It can be used by type-checking tools like mypy, pyright,\n"
        "     pytype, PyCharm, etc. to check code that uses toml.\n"
        "-  license: Apache-2.0 AND MIT\n"
        "+  license: MIT\n"
        " \n"
        " multi_level:\n"
        "   list_1:"
    )

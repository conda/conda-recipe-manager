"""
:Description: Unit tests for the V0RecipeFormatter class
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.parser.v0_recipe_formatter import V0RecipeFormatter
from tests.file_loading import load_file


@pytest.mark.parametrize(
    "file",
    [
        ("types-toml.yaml"),
        ("boto.yaml"),
        ("cctools-ld64.yaml"),
        # V1 shouldn't really be used in this way, but we'll round trip one as a sanity check.
        ("v1_format/v1_types-toml.yaml"),
    ],
)
def test_to_str_round_trip(file: str) -> None:
    """
    Ensures that we can round-trip an unformatted recipe file.

    :param file: Recipe file to test with
    """
    content = load_file(file)
    assert str(V0RecipeFormatter(content)) == content


@pytest.mark.parametrize(
    "file,expected",
    [
        ("types-toml.yaml", True),
        ("boto.yaml", True),
        ("cctools-ld64.yaml", True),
        ("v1_format/v1_types-toml.yaml", False),
        ("v1_format/v1_boto.yaml", False),
        ("v1_format/v1_cctools-ld64.yaml", False),
    ],
)
def test_is_v0_recipe(file: str, expected: bool) -> None:
    """
    Validates that `is_v0_recipe()` can accurately identify V0 recipe files.

    :param file: Recipe file to test with
    :param expected: Expected result of the test
    """
    content = load_file(file)
    assert V0RecipeFormatter(content).is_v0_recipe() == expected


@pytest.mark.parametrize(
    "file,expected_file",
    [
        ## No change tests ##
        ("types-toml.yaml", "types-toml.yaml"),
        ("boto.yaml", "boto.yaml"),
        ("cctools-ld64.yaml", "cctools-ld64.yaml"),
        ## Formatter changed the file contents tests ##
        # Comments indented in really strange ways
        ("v0_formatter/types-toml_bad_comment_indent.yaml", "v0_formatter/types-toml_bad_comment_indent_fixed.yaml"),
        # Lists with really bad indentations entirely
        ("v0_formatter/types-toml_bad_indents.yaml", "v0_formatter/types-toml_bad_indents_fixed.yaml"),
    ],
)
def test_fmt_text(file: str, expected_file: str) -> None:
    """
    Validates that the `fmt_text()` command formats a recipe file as expected.

    :param file: Recipe file to test with
    :param expected_file: File containing the expected result
    """
    content = load_file(file)
    fmt = V0RecipeFormatter(content)
    fmt.fmt_text()
    assert str(fmt) == load_file(expected_file)

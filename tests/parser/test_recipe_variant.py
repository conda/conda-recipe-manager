"""
:Description: Unit tests for the RecipeVariant class
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.parser.recipe_variant import RecipeVariant
from tests.file_loading import load_file

## Build Variant Rendering ##


@pytest.mark.parametrize(
    "file,build_context,expected_file",
    [
        ("curl.yaml", BuildContext(platform=Platform.WIN_64), "selector_filtering/curl_win_64.yaml"),
        ("curl.yaml", BuildContext(platform=Platform.LINUX_AARCH_64), "selector_filtering/curl_linux_aarch_64.yaml"),
        ("curl.yaml", BuildContext(platform=Platform.OSX_ARM_64), "selector_filtering/curl_osx_arm_64.yaml"),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.6"}),
            "selector_filtering/huggingface_hub_py36.yaml",
        ),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.7"}),
            "selector_filtering/huggingface_hub_py37.yaml",
        ),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.8"}),
            "selector_filtering/huggingface_hub_py38.yaml",
        ),
        # Regression to check that comments are ignored when filtering by selectors.
        (
            "gluonts.yaml",
            BuildContext(platform=Platform.LINUX_AARCH_64, build_env_vars={"python": "3.7"}),
            "selector_filtering/gluonts_linux_aarch_64.yaml",
        ),
    ],
)
def test_filter_by_selectors(file: str, build_context: BuildContext, expected_file: str) -> None:
    """
    Tests the ability for the `RecipeParser` to filter the recipe by selectors.

    :param file: The file to load the recipe from.
    :param build_context: The build context to filter the recipe by.
    :param expected_file: The file to compare the filtered recipe to.
    """
    parser = RecipeVariant(load_file(file))
    parser._filter_by_selectors(build_context)  # pylint: disable=protected-access
    assert parser.render() == load_file(expected_file)


@pytest.mark.parametrize(
    "file,build_context,expected_file",
    [
        # Check that recipe JINJA variables take precedence over build context variables (openssl).
        (
            "jinja2_rendering/curl.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"openssl": "7.0.0", "zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_rendered.yaml",
        ),
        (
            "jinja2_rendering/curl.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_rendered.yaml",
        ),
        # Regression test for #471: JINJA rendering should only operate on JINJA expressions.
        (
            "jinja2_rendering/curl_regression.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_regression_rendered.yaml",
        ),
    ],
)
def test_evaluate_jinja_expressions(file: str, build_context: BuildContext, expected_file: str) -> None:
    """
    Tests the ability for the `RecipeParser` to replace Jinja expressions in the recipe with their evaluated values.

    :param file: The file to load the recipe from.
    :param build_context: The build context to evaluate the Jinja expressions for.
    :param expected_file: The file to compare the evaluated recipe to.
    """
    parser = RecipeVariant(load_file(file))
    parser._evaluate_jinja_expressions(build_context)  # pylint: disable=protected-access
    assert parser.render() == load_file(expected_file)
